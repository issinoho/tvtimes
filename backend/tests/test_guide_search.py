"""Programme search — /api/guide/search and epg.search_programmes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.db import get_sessionmaker
from app.models.epg import EpgSource, Programme
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.services import epg as svc
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

SOON = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)


async def _seed() -> uuid.UUID:
    """One tenant, two channels (one with a US tz override), a handful of
    programmes including the same film on both channels."""
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="Europe/London")
        session.add(tenant)
        await session.flush()
        source = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            timezone_override="America/New_York",
            last_status=SourceStatus.ok,
        )
        session.add(source)
        await session.flush()
        epg = EpgSource(tenant_id=tenant.id, source_id=source.id, url="http://x")
        session.add(epg)
        await session.flush()

        ch_a = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="a",
            name="Movies 24",
            number=1,
            stream_ref_encrypted="x",
        )
        ch_b = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="b",
            name="Film Four",
            number=2,
            stream_ref_encrypted="x",
        )
        session.add_all([ch_a, ch_b])
        await session.flush()

        def prog(
            ch: Channel, offset_h: int, title: str, *, movie: bool, sub: str | None = None
        ) -> Programme:
            s = SOON + timedelta(hours=offset_h)
            return Programme(
                tenant_id=tenant.id,
                channel_id=ch.id,
                epg_source_id=epg.id,
                start_utc=s,
                stop_utc=s + timedelta(hours=2),
                title=title,
                sub_title=sub,
                is_movie=movie,
                categories=["Movie"] if movie else ["News"],
            )

        session.add_all(
            [
                prog(ch_a, 0, "Blade Runner", movie=True),
                prog(ch_b, 5, "Blade Runner", movie=True),  # same film, later, other channel
                prog(ch_a, 2, "The News at Ten", movie=False, sub="Blade Runner retrospective"),
                prog(ch_a, 8, "Cooking Live", movie=False),
            ]
        )
        await session.commit()
        return tenant.id


async def test_matches_title_and_subtitle(db_schema: None) -> None:
    tenant_id = await _seed()
    async with get_sessionmaker()() as session:
        hits = await svc.search_programmes(
            session,
            tenant_id,
            query="blade runner",
            start=SOON - timedelta(hours=1),
            end=SOON + timedelta(days=2),
            limit=50,
        )
    titles = [h.programme.title for h in hits]
    # two airings of the film + the news item whose sub-title mentions it
    assert titles.count("Blade Runner") == 2
    assert "The News at Ten" in titles
    assert "Cooking Live" not in titles
    # earliest first
    assert hits == sorted(hits, key=lambda h: h.local_start)


async def test_movies_only_filter(db_schema: None) -> None:
    tenant_id = await _seed()
    async with get_sessionmaker()() as session:
        hits = await svc.search_programmes(
            session,
            tenant_id,
            query="blade runner",
            movies_only=True,
            start=SOON - timedelta(hours=1),
            end=SOON + timedelta(days=2),
            limit=50,
        )
    assert [h.programme.title for h in hits] == ["Blade Runner", "Blade Runner"]


async def test_times_resolved_to_channel_zone(db_schema: None) -> None:
    tenant_id = await _seed()
    async with get_sessionmaker()() as session:
        hits = await svc.search_programmes(
            session,
            tenant_id,
            query="blade runner",
            movies_only=True,
            start=SOON - timedelta(hours=1),
            end=SOON + timedelta(days=2),
            limit=50,
        )
    first = hits[0]
    assert first.timezone == "America/New_York"
    assert first.local_start.utcoffset() in {timedelta(hours=-4), timedelta(hours=-5)}
    assert first.local_start == SOON.astimezone(first.local_start.tzinfo)


async def test_window_excludes_out_of_range(db_schema: None) -> None:
    tenant_id = await _seed()
    async with get_sessionmaker()() as session:
        hits = await svc.search_programmes(
            session,
            tenant_id,
            query="blade runner",
            start=SOON - timedelta(hours=1),
            end=SOON + timedelta(hours=3),  # only the first airing falls in here
            limit=50,
        )
    assert len(hits) == 2  # the ch_a film (offset 0) + the news sub-title (offset 2)
    assert {h.channel.name for h in hits} == {"Movies 24"}


async def test_search_endpoint(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    access = await login(app_client)
    h = auth_header(access)
    me = (await app_client.get("/api/account/me", headers=h)).json()
    tenant_id = uuid.UUID(me["tenant_id"])

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
        session.add(epg)
        await session.flush()
        ch = Channel(
            tenant_id=tenant_id,
            source_id=src.id,
            dedupe_key="c",
            name="BBC One",
            number=1,
            stream_ref_encrypted="x",
        )
        session.add(ch)
        await session.flush()
        session.add(
            Programme(
                tenant_id=tenant_id,
                channel_id=ch.id,
                epg_source_id=epg.id,
                start_utc=SOON,
                stop_utc=SOON + timedelta(hours=1),
                title="Match of the Day",
                is_movie=False,
            )
        )
        await session.commit()

    # too short
    assert (
        await app_client.get("/api/guide/search", params={"q": "a"}, headers=h)
    ).status_code == 422

    resp = await app_client.get("/api/guide/search", params={"q": "match of"}, headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "match of"
    assert len(body["results"]) == 1
    hit = body["results"][0]
    assert hit["programme"]["title"] == "Match of the Day"
    assert hit["channel"]["name"] == "BBC One"
    assert "programmes" not in hit["channel"]

    # unauthenticated
    assert (await app_client.get("/api/guide/search", params={"q": "match"})).status_code == 401
