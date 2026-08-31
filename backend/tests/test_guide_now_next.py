"""now/next and the highlights buckets."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.db import get_sessionmaker
from app.ingest.xmltv import normalize_name
from app.models.epg import EpgSource, Programme
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.models.tmdb import MediaType, TmdbEnrichment
from app.services import epg as svc
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

NOW = datetime(2026, 9, 1, 20, 0, tzinfo=UTC)


async def _seed() -> dict[str, uuid.UUID]:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="America/New_York")
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
        alpha = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="a",
            name="Alpha",
            number=1,
            stream_ref_encrypted="x",
        )
        beta = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="b",
            name="Beta",
            number=2,
            stream_ref_encrypted="x",
        )
        session.add_all([epg, alpha, beta])
        await session.flush()

        def prog(ch: Channel, start: datetime, hours: int, title: str, *, movie: bool) -> Programme:
            return Programme(
                tenant_id=tenant.id,
                channel_id=ch.id,
                epg_source_id=epg.id,
                start_utc=start,
                stop_utc=start + timedelta(hours=hours),
                title=title,
                year="2014" if movie else None,
                is_movie=movie,
            )

        session.add_all(
            [
                # Alpha: something on now, then a film next.
                prog(alpha, NOW - timedelta(minutes=30), 1, "Evening News", movie=False),
                prog(alpha, NOW + timedelta(minutes=30), 2, "Interstellar", movie=True),
                # Beta: nothing on now (gap), a film in 3h.
                prog(beta, NOW + timedelta(hours=3), 2, "Whiplash", movie=True),
                # Alpha: a highly-rated film later this week (outside 10h window).
                prog(alpha, NOW + timedelta(days=3), 2, "The Dark Knight", movie=True),
            ]
        )
        # ratings: Interstellar 8.4, Whiplash 8.5, Dark Knight 9.0
        for title, rating in [("Interstellar", 8.4), ("Whiplash", 8.5), ("The Dark Knight", 9.0)]:
            session.add(
                TmdbEnrichment(
                    media_type=MediaType.movie,
                    query_key=normalize_name(title)[:300],
                    query_year="2014",
                    rating=rating,
                    fetched_at=NOW,
                )
            )
        await session.commit()
        return {"tenant": tenant.id, "alpha": alpha.id, "beta": beta.id}


async def test_now_next_current_and_upcoming(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        rows = await svc.now_next(session, ids["tenant"], now=NOW)
    by_name = {r.channel.name: r for r in rows}

    alpha = by_name["Alpha"]
    assert alpha.current is not None and alpha.current[0].title == "Evening News"
    assert alpha.upcoming is not None and alpha.upcoming[0].title == "Interstellar"
    # times resolved into the channel's zone (America/New_York -> -04:00 in Sept)
    assert alpha.timezone == "America/New_York"
    assert alpha.current[1].utcoffset() == timedelta(hours=-4)

    beta = by_name["Beta"]
    assert beta.current is None
    assert beta.upcoming is not None and beta.upcoming[0].title == "Whiplash"


async def test_highlights_soon_and_top_rated(db_schema: None) -> None:
    ids = await _seed()
    async with get_sessionmaker()() as session:
        films_soon, top_rated = await svc.highlights(session, ids["tenant"], now=NOW)

    # within 10h: Interstellar (+30m) and Whiplash (+3h); Dark Knight (+3d) is not
    assert [h.programme.title for h in films_soon] == ["Interstellar", "Whiplash"]

    # ranked by TMDB rating desc across the week
    assert [h.programme.title for h in top_rated] == ["The Dark Knight", "Whiplash", "Interstellar"]


async def test_highlights_empty_without_enrichment(db_schema: None) -> None:
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T2", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        src = Source(
            tenant_id=tenant.id,
            kind=SourceKind.m3u,
            display_name="S",
            config_encrypted="x",
            last_status=SourceStatus.ok,
        )
        session.add(src)
        await session.flush()
        epg = EpgSource(tenant_id=tenant.id, source_id=src.id, url="http://x")
        ch = Channel(
            tenant_id=tenant.id,
            source_id=src.id,
            dedupe_key="c",
            name="C",
            stream_ref_encrypted="x",
        )
        session.add_all([epg, ch])
        await session.flush()
        session.add(
            Programme(
                tenant_id=tenant.id,
                channel_id=ch.id,
                epg_source_id=epg.id,
                start_utc=NOW + timedelta(hours=2),
                stop_utc=NOW + timedelta(hours=4),
                title="Unknown Film",
                is_movie=True,
            )
        )
        await session.commit()
        tenant_id = tenant.id

    async with get_sessionmaker()() as session:
        films_soon, top_rated = await svc.highlights(session, tenant_id, now=NOW)
    assert [h.programme.title for h in films_soon] == ["Unknown Film"]
    assert top_rated == []


async def test_endpoints(app_client: AsyncClient, captured_emails: list[dict[str, str]]) -> None:
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
        ch = Channel(
            tenant_id=tenant_id,
            source_id=src.id,
            dedupe_key="c",
            name="BBC One",
            number=1,
            stream_ref_encrypted="x",
        )
        session.add_all([epg, ch])
        await session.flush()
        start = datetime.now(UTC) - timedelta(minutes=10)
        session.add(
            Programme(
                tenant_id=tenant_id,
                channel_id=ch.id,
                epg_source_id=epg.id,
                start_utc=start,
                stop_utc=start + timedelta(hours=1),
                title="On Air Now",
                is_movie=False,
            )
        )
        await session.commit()

    nn = await app_client.get("/api/guide/now-next", headers=h)
    assert nn.status_code == 200, nn.text
    body = nn.json()
    assert body["channels"][0]["channel"]["name"] == "BBC One"
    assert body["channels"][0]["current"]["title"] == "On Air Now"
    assert "programmes" not in body["channels"][0]["channel"]

    hl = await app_client.get("/api/guide/highlights", headers=h)
    assert hl.status_code == 200
    assert hl.json() == {"films_soon": [], "top_rated": []}

    assert (await app_client.get("/api/guide/now-next")).status_code == 401
    assert (await app_client.get("/api/guide/highlights")).status_code == 401
