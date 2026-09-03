"""Reported watch intervals, and deriving watched-ness from them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.db import get_sessionmaker
from app.models.epg import EpgSource, Programme
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.models.watch import WatchEvent
from app.services import watch as svc
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import auth_header, login, register_and_verify

# 20:00-21:00 on a shifted channel; the shift is what the export feed (and so
# the reporter) already applied, so reported times are start+1h.
PROG_START = datetime(2026, 9, 3, 20, 0, tzinfo=UTC)
SHIFT = timedelta(hours=1)


async def _seed(*, shift_seconds: int = 3600) -> dict[str, uuid.UUID]:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add(source)
        await session.flush()
        epg = EpgSource(tenant_id=tenant.id, source_id=source.id, url="http://x")
        channel = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="a",
            name="BBC One",
            stream_ref_encrypted="x",
            clock_shift_seconds=shift_seconds,
        )
        session.add_all([epg, channel])
        await session.flush()
        prog = Programme(
            tenant_id=tenant.id,
            channel_id=channel.id,
            epg_source_id=epg.id,
            start_utc=PROG_START,
            stop_utc=PROG_START + timedelta(hours=1),
            title="The Nine O'Clock News",
        )
        session.add(prog)
        await session.commit()
        return {"tenant": tenant.id, "channel": channel.id, "prog": prog.id}


async def _watched(ids: dict[str, uuid.UUID]) -> set[uuid.UUID]:
    async with get_sessionmaker()() as session:
        progs = list(await session.scalars(select(Programme)))
        return await svc.watched_programme_ids(session, ids["tenant"], progs)


async def _report(ids: dict[str, uuid.UUID], *rows: svc.ReportedWatch) -> tuple[int, int]:
    async with get_sessionmaker()() as session:
        result = await svc.record_watch_events(session, ids["tenant"], list(rows))
        await session.commit()
        return result


def _watch(ids: dict[str, uuid.UUID], start: datetime, minutes: int) -> svc.ReportedWatch:
    return svc.ReportedWatch(
        channel_id=ids["channel"], started_at=start, ended_at=start + timedelta(minutes=minutes)
    )


async def test_a_full_viewing_marks_the_programme_watched(db_schema: None) -> None:
    ids = await _seed()
    # the reporter played the export feed, whose guide is already shifted
    await _report(ids, _watch(ids, PROG_START + SHIFT, 60))
    assert await _watched(ids) == {ids["prog"]}


async def test_a_brief_flick_past_does_not_count(db_schema: None) -> None:
    ids = await _seed()
    await _report(ids, _watch(ids, PROG_START + SHIFT, 2))
    assert await _watched(ids) == set()


async def test_joining_late_still_counts_once_past_the_threshold(db_schema: None) -> None:
    ids = await _seed()
    # 35 of 60 minutes — over half, so it counts even though the start was missed
    await _report(ids, _watch(ids, PROG_START + SHIFT + timedelta(minutes=25), 35))
    assert await _watched(ids) == {ids["prog"]}


async def test_split_viewings_add_up(db_schema: None) -> None:
    ids = await _seed()
    await _report(
        ids,
        _watch(ids, PROG_START + SHIFT, 20),
        _watch(ids, PROG_START + SHIFT + timedelta(minutes=30), 20),
    )
    assert await _watched(ids) == {ids["prog"]}


async def test_the_channels_clock_shift_is_applied(db_schema: None) -> None:
    ids = await _seed()
    # raw (unshifted) times: right for the DB row, wrong for what was on air
    await _report(ids, _watch(ids, PROG_START, 60))
    assert await _watched(ids) == set()


async def test_reports_are_idempotent_and_extend_in_place(db_schema: None) -> None:
    ids = await _seed()
    start = PROG_START + SHIFT
    await _report(ids, _watch(ids, start, 10))
    await _report(ids, _watch(ids, start, 10))  # exact resend
    await _report(ids, _watch(ids, start, 60))  # the viewing ran on
    async with get_sessionmaker()() as session:
        events = list(await session.scalars(select(WatchEvent)))
    assert len(events) == 1
    assert events[0].ended_at == start + timedelta(minutes=60)
    assert await _watched(ids) == {ids["prog"]}


async def test_foreign_channels_and_daft_durations_are_skipped_not_fatal(
    db_schema: None,
) -> None:
    ids = await _seed()
    good = _watch(ids, PROG_START + SHIFT, 60)
    stored, skipped = await _report(
        ids,
        good,
        svc.ReportedWatch(  # another tenant's channel
            channel_id=uuid.uuid4(),
            started_at=PROG_START,
            ended_at=PROG_START + timedelta(hours=1),
        ),
        _watch(ids, PROG_START + SHIFT + timedelta(days=1), -30),  # ends before it starts
        _watch(ids, PROG_START + SHIFT + timedelta(days=2), 60 * 24),  # left running overnight
    )
    assert (stored, skipped) == (1, 3)
    assert await _watched(ids) == {ids["prog"]}


async def test_pruning_drops_only_old_intervals(db_schema: None) -> None:
    ids = await _seed()
    old = datetime.now(UTC) - timedelta(days=200)
    await _report(ids, _watch(ids, old, 60), _watch(ids, PROG_START + SHIFT, 60))
    async with get_sessionmaker()() as session:
        dropped = await svc.prune_watch_events(session, ids["tenant"])
        await session.commit()
    assert dropped == 1
    async with get_sessionmaker()() as session:
        assert len(list(await session.scalars(select(WatchEvent)))) == 1


# --- the ingest endpoint -------------------------------------------------------


async def test_watch_events_endpoint_is_token_gated(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    anon = await app_client.post("/api/exports/watch-events", json={"events": []})
    assert anon.status_code == 401
    assert (
        await app_client.post("/api/exports/watch-events?token=nope", json={"events": []})
    ).status_code == 401

    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))
    token = (await app_client.post("/api/account/export-token", headers=h)).json()["token"]

    resp = await app_client.post(f"/api/exports/watch-events?token={token}", json={"events": []})
    assert resp.status_code == 200
    assert resp.json() == {"stored": 0, "skipped": 0}


async def test_watch_events_endpoint_stores_and_reports_counts(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))
    token = (await app_client.post("/api/account/export-token", headers=h)).json()["token"]
    me = (await app_client.get("/api/account/me", headers=h)).json()

    async with get_sessionmaker()() as session:
        src = Source(
            tenant_id=uuid.UUID(me["tenant_id"]),
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add(src)
        await session.flush()
        ch = Channel(
            tenant_id=uuid.UUID(me["tenant_id"]),
            source_id=src.id,
            dedupe_key="c",
            name="BBC One",
            stream_ref_encrypted="x",
        )
        session.add(ch)
        await session.commit()
        channel_id = str(ch.id)

    body = {
        "events": [
            {
                "channel_id": channel_id,
                "started_at": "2026-09-03T20:00:00+00:00",
                "ended_at": "2026-09-03T21:00:00+00:00",
                "title": "The News",
                "device": "living room",
            },
            {  # not this tenant's channel
                "channel_id": str(uuid.uuid4()),
                "started_at": "2026-09-03T20:00:00+00:00",
                "ended_at": "2026-09-03T21:00:00+00:00",
            },
        ]
    }
    resp = await app_client.post(f"/api/exports/watch-events?token={token}", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"stored": 1, "skipped": 1}

    async with get_sessionmaker()() as session:
        events = list(await session.scalars(select(WatchEvent)))
    assert len(events) == 1
    assert events[0].title == "The News" and events[0].device == "living room"


def _watch_on(
    ids: dict[str, uuid.UUID], start: datetime, minutes: int, device: str | None
) -> svc.ReportedWatch:
    return svc.ReportedWatch(
        channel_id=ids["channel"],
        started_at=start,
        ended_at=start + timedelta(minutes=minutes),
        device=device,
    )


async def _devices(ids: dict[str, uuid.UUID]) -> list[svc.ReportingDevice]:
    async with get_sessionmaker()() as session:
        return await svc.reporting_devices(session, ids["tenant"])


async def test_reporting_devices_lists_each_player_most_recent_first(
    db_schema: None,
) -> None:
    ids = await _seed()
    start = PROG_START + SHIFT
    await _report(
        ids,
        _watch_on(ids, start, 30, "bedroom"),
        _watch_on(ids, start + timedelta(hours=2), 30, "living room"),
        _watch_on(ids, start + timedelta(hours=4), 30, "living room"),
    )
    devices = await _devices(ids)
    assert [d.name for d in devices] == ["living room", "bedroom"]
    assert [d.events for d in devices] == [2, 1]
    assert devices[0].last_reported_at == start + timedelta(hours=4, minutes=30)


async def test_reporting_devices_groups_unlabelled_reports_under_one_entry(
    db_schema: None,
) -> None:
    # Two unlabelled players are indistinguishable; claiming otherwise
    # would be a guess. Pre-1.40 tvdinner reports land here.
    ids = await _seed()
    start = PROG_START + SHIFT
    await _report(
        ids,
        _watch_on(ids, start, 30, None),
        _watch_on(ids, start + timedelta(hours=2), 30, None),
    )
    devices = await _devices(ids)
    assert [(d.name, d.events) for d in devices] == [(None, 2)]


async def test_reporting_devices_is_empty_before_anything_reports(
    db_schema: None,
) -> None:
    assert await _devices(await _seed()) == []
