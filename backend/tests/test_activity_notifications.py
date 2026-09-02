"""The 4 per-tenant activity notifications: the settings endpoint and the
router wiring that enqueues a push when a user acts."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app import queue
from app.auth.crypto import encrypt
from app.db import get_sessionmaker
from app.models.epg import EpgSource, Programme
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tmdb import MediaType, TmdbEnrichment
from app.services.tmdb import cache_key
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

Jobs = list[tuple[str, ...]]


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> Iterator[Jobs]:
    """Capture every queue job so no Redis is touched. All enqueue args are
    already strings (see app.queue), so record them as such."""
    jobs: Jobs = []

    async def _fake_enqueue(job: str, *args: object) -> None:
        jobs.append((job, *(str(a) for a in args)))

    monkeypatch.setattr(queue, "_enqueue", _fake_enqueue)
    yield jobs


def _activity_jobs(jobs: Jobs) -> list[tuple[str, ...]]:
    return [j for j in jobs if j[0] == "activity_notification"]


async def _seed_channel(tenant_id: uuid.UUID) -> tuple[str, str]:
    async with get_sessionmaker()() as session:
        src = Source(
            tenant_id=tenant_id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add(src)
        await session.flush()
        epg = EpgSource(tenant_id=tenant_id, source_id=src.id, url="http://x")
        ch = Channel(
            tenant_id=tenant_id,
            source_id=src.id,
            dedupe_key="c",
            name="BBC One",
            number="1",
            stream_ref_encrypted=encrypt("http://provider.example/bbc.ts"),
        )
        session.add_all([epg, ch])
        await session.flush()
        now = datetime.now(UTC)
        prog = Programme(
            tenant_id=tenant_id,
            channel_id=ch.id,
            epg_source_id=epg.id,
            start_utc=now + timedelta(days=1),
            stop_utc=now + timedelta(days=1, hours=1),
            title="Later Film",
            is_movie=True,
        )
        # what's on the channel right now, plus a TMDB poster for it
        now_on = Programme(
            tenant_id=tenant_id,
            channel_id=ch.id,
            epg_source_id=epg.id,
            start_utc=now - timedelta(minutes=20),
            stop_utc=now + timedelta(minutes=40),
            title="The Thing",
            year="1982",
            is_movie=True,
        )
        key, year_key = cache_key("The Thing", "1982")
        art = TmdbEnrichment(
            media_type=MediaType.movie,
            query_key=key,
            query_year=year_key,
            fetched_at=now,
            negative=False,
            tmdb_id=1091,
            poster_url="https://image.tmdb.org/t/p/w500/the-thing.jpg",
        )
        session.add_all([prog, now_on, art])
        await session.commit()
        return str(ch.id), str(prog.id)


# --- settings endpoint ----------------------------------------------------


async def test_me_exposes_activity_flags_defaulting_off(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))
    me = (await app_client.get("/api/account/me", headers=h)).json()
    assert me["notify_on_reminder_set"] is False
    assert me["notify_on_title_watch_set"] is False
    assert me["notify_on_play"] is False
    assert me["notify_on_watchlist_remove"] is False


async def test_activity_notifications_patch_semantics(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))

    r = await app_client.put("/api/account/activity-notifications", headers=h, json={"play": True})
    assert r.status_code == 200, r.text
    me = (await app_client.get("/api/account/me", headers=h)).json()
    assert me["notify_on_play"] is True
    assert me["notify_on_reminder_set"] is False  # untouched

    # a second patch leaves the first field alone
    await app_client.put(
        "/api/account/activity-notifications", headers=h, json={"reminder_set": True}
    )
    me = (await app_client.get("/api/account/me", headers=h)).json()
    assert (me["notify_on_play"], me["notify_on_reminder_set"]) == (True, True)

    # turn one back off
    await app_client.put("/api/account/activity-notifications", headers=h, json={"play": False})
    me = (await app_client.get("/api/account/me", headers=h)).json()
    assert me["notify_on_play"] is False


async def test_activity_notifications_requires_auth(app_client: AsyncClient) -> None:
    assert (
        await app_client.put("/api/account/activity-notifications", json={"play": True})
    ).status_code == 401


# --- router wiring ------------------------------------------------------------


async def test_watchlist_actions_enqueue_pushes(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: Jobs
) -> None:
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))
    me = (await app_client.get("/api/account/me", headers=h)).json()
    _channel_id, programme_id = await _seed_channel(uuid.UUID(me["tenant_id"]))

    created = await app_client.post(
        "/api/watchlist", headers=h, json={"kind": "programme", "programme_id": programme_id}
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    # idempotent re-add: no second push
    again = await app_client.post(
        "/api/watchlist", headers=h, json={"kind": "programme", "programme_id": programme_id}
    )
    assert again.status_code == 201

    await app_client.post(
        "/api/watchlist", headers=h, json={"kind": "title", "title": "Later Film"}
    )
    assert (await app_client.delete(f"/api/watchlist/{item_id}", headers=h)).status_code == 200

    cats = [j[2] for j in _activity_jobs(enqueued)]
    assert cats == ["reminder_set", "title_watch_set", "watchlist_remove"]
    # every job carries the tenant id and a title/body
    for _job, tid, _cat, title, body, *_rest in _activity_jobs(enqueued):
        assert tid == me["tenant_id"]
        assert title and body


async def test_play_link_enqueues_push(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: Jobs
) -> None:
    await register_and_verify(app_client, captured_emails)
    h = auth_header(await login(app_client))
    me = (await app_client.get("/api/account/me", headers=h)).json()
    channel_id, _programme_id = await _seed_channel(uuid.UUID(me["tenant_id"]))

    resp = await app_client.post(f"/api/channels/{channel_id}/play-link", headers=h)
    assert resp.status_code == 200, resp.text

    jobs = _activity_jobs(enqueued)
    assert len(jobs) == 1
    _job, _tid, category, title, body, image_url = jobs[0]
    assert category == "play"
    assert title == "The Thing"  # what's on the channel now, not "Playing now"
    assert "BBC One" in body
    assert image_url == "https://image.tmdb.org/t/p/w500/the-thing.jpg"
