from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.ingest.models import Channel as ParsedChannel
from app.ingest.models import Playlist
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

_BASE = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)

SEARCH_RESULT = {"id": 99, "vote_average": 8.1, "backdrop_path": "/fallback.jpg"}
DETAIL = {
    "id": 99,
    "title": "The Big Film",
    "release_date": "1999-03-31",
    "overview": "Reality is a simulation.",
    "runtime": 136,
    "genres": [{"name": "Sci-Fi"}],
    "credits": {
        "crew": [{"job": "Director", "name": "The Directors"}],
        "cast": [{"name": "Star One", "character": "Hero"}],
    },
    "images": {
        "backdrops": [{"file_path": "/hero.jpg", "iso_639_1": None, "width": 3840}],
        "logos": [{"file_path": "/logo.png", "iso_639_1": "en", "width": 800}],
    },
}


@pytest.fixture(autouse=True)
def _stub_tmdb(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a: object, **_k: object) -> None:
        return None

    async def _valid(_token: str) -> bool:
        return True

    monkeypatch.setattr("app.api.routers.sources.enqueue_source_refresh", _noop)
    monkeypatch.setattr("app.api.routers.epg.enqueue_epg_refresh", _noop)
    monkeypatch.setattr("app.api.routers.hero.enqueue_programme_enrich", _noop)
    monkeypatch.setattr("app.services.tmdb.token_looks_valid", _valid)


def _stub_search(monkeypatch: pytest.MonkeyPatch, result: dict[str, Any] | None) -> None:
    async def fake_search(*_a: object, **_k: object) -> dict[str, Any] | None:
        return result

    async def fake_details(*_a: object, **_k: object) -> dict[str, Any]:
        return DETAIL

    monkeypatch.setattr("app.services.tmdb.client.search", fake_search)
    monkeypatch.setattr("app.services.tmdb.client.details", fake_details)


async def _seed(
    client: AsyncClient, emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, str], str]:
    await register_and_verify(client, emails)
    headers = auth_header(await login(client))

    async def fake_ingest(*_a: object) -> Playlist:
        return Playlist(
            channels=[ParsedChannel(name="Film4", stream_ref="s", tvg_id="film4")],
            epg_url="http://epg.example.com/x.xml",
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    src = (
        await client.post(
            "/api/sources",
            json={"kind": "m3u", "display_name": "P", "url": "http://feed.example.com/l.m3u"},
            headers=headers,
        )
    ).json()["id"]

    from app.db import get_sessionmaker
    from app.models.epg import EpgSource, Programme
    from app.models.source import Channel, Source
    from app.services import sources as src_svc
    from sqlalchemy import select

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(src))
        await src_svc.refresh_source(session, source)  # type: ignore[arg-type]
        await session.flush()
        channel = await session.scalar(select(Channel).where(Channel.source_id == uuid.UUID(src)))
        assert channel is not None
        epg = EpgSource(tenant_id=channel.tenant_id, source_id=uuid.UUID(src), url="http://x")
        session.add(epg)
        await session.flush()
        prog = Programme(
            tenant_id=channel.tenant_id,
            channel_id=channel.id,
            epg_source_id=epg.id,
            start_utc=_BASE,
            stop_utc=_BASE + timedelta(hours=2),
            title="The Big Film",
            categories=["Movie"],
            is_movie=True,
            year="1999",
        )
        session.add(prog)
        await session.commit()
        return headers, str(prog.id)


async def _hero(client: AsyncClient, headers: dict[str, str], programme_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/guide/programme/{programme_id}/hero", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def test_hero_without_token_returns_programme_only(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, programme_id = await _seed(app_client, captured_emails, monkeypatch)
    body = await _hero(app_client, headers, programme_id)
    assert body["title"] == "The Big Film"
    assert body["tmdb_connected"] is False
    assert body["enriching"] is False
    assert body["enrichment"] is None
    assert body["categories"] == ["Movie"]


async def test_connect_token_then_enrich_populates_hero(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, programme_id = await _seed(app_client, captured_emails, monkeypatch)

    connect = await app_client.put(
        "/api/account/tmdb-token", json={"token": "x" * 40}, headers=headers
    )
    assert connect.status_code == 200
    me = await app_client.get("/api/account/me", headers=headers)
    assert me.json()["tmdb_connected"] is True

    # Cold cache: hero is flagged as enriching, no data yet.
    cold = await _hero(app_client, headers, programme_id)
    assert cold["tmdb_connected"] is True
    assert cold["enriching"] is True
    assert cold["enrichment"] is None

    # Run the enrichment job directly, then the hero has TMDB data.
    _stub_search(monkeypatch, SEARCH_RESULT)
    from app.db import get_sessionmaker
    from app.models.user import User
    from app.services import tmdb as tmdb_svc
    from sqlalchemy import select

    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User))
        await tmdb_svc.enrich_programme(session, user.tenant_id, uuid.UUID(programme_id))  # type: ignore[union-attr]
        await session.commit()

    warm = await _hero(app_client, headers, programme_id)
    assert warm["enriching"] is False
    e = warm["enrichment"]
    assert e["rating"] == 8.1
    assert e["genres"] == ["Sci-Fi"]
    assert e["director"] == "The Directors"
    assert e["cast"][0]["name"] == "Star One"
    assert e["backdrop_url"].endswith("/hero.jpg")
    assert e["logo_url"].endswith("/logo.png")

    disconnect = await app_client.request("DELETE", "/api/account/tmdb-token", headers=headers)
    assert disconnect.status_code == 200
    me2 = await app_client.get("/api/account/me", headers=headers)
    assert me2.json()["tmdb_connected"] is False


async def test_negative_match_is_cached_not_reenriched(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, programme_id = await _seed(app_client, captured_emails, monkeypatch)
    await app_client.put("/api/account/tmdb-token", json={"token": "x" * 40}, headers=headers)

    calls = {"n": 0}

    async def fake_search(*_a: object, **_k: object) -> None:
        calls["n"] += 1
        return None

    monkeypatch.setattr("app.services.tmdb.client.search", fake_search)

    from app.db import get_sessionmaker
    from app.models.user import User
    from app.services import tmdb as tmdb_svc
    from sqlalchemy import select

    for _ in range(2):
        async with get_sessionmaker()() as session:
            user = await session.scalar(select(User))
            await tmdb_svc.enrich_programme(session, user.tenant_id, uuid.UUID(programme_id))  # type: ignore[union-attr]
            await session.commit()

    assert calls["n"] == 1  # second call served from the cached negative

    body = await _hero(app_client, headers, programme_id)
    assert body["enrichment"] is None
    assert body["enriching"] is False


async def test_hero_is_tenant_isolated(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _headers, programme_id = await _seed(app_client, captured_emails, monkeypatch)
    await register_and_verify(app_client, captured_emails, email="other@example.com")
    other = auth_header(await login(app_client, email="other@example.com"))
    resp = await app_client.get(f"/api/guide/programme/{programme_id}/hero", headers=other)
    assert resp.status_code == 404


async def test_artwork_for_is_cache_only_and_prefers_backdrop(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Tonight rails render dozens of cards at once, so their artwork
    lookup reads the enrichment cache and never enriches. A programme TMDB
    hasn't matched is simply absent -- not a queued fetch, and not an error."""
    _, programme_id = await _seed(app_client, captured_emails, monkeypatch)

    from app.db import get_sessionmaker
    from app.models.epg import Programme
    from app.models.tmdb import MediaType, TmdbEnrichment
    from app.services import tmdb as tmdb_svc

    async with get_sessionmaker()() as session:
        programme = await session.get(Programme, uuid.UUID(programme_id))
        assert programme is not None

        # Nothing cached yet: absent, and no enrichment triggered.
        assert await tmdb_svc.artwork_for(session, [programme]) == {}

        key, year_key = tmdb_svc.cache_key(programme.title, programme.year)
        session.add(
            TmdbEnrichment(
                media_type=MediaType.movie,
                query_key=key,
                query_year=year_key,
                fetched_at=datetime.now(UTC),
                backdrop_url="https://img.example.com/backdrop.jpg",
                poster_url="https://img.example.com/poster.jpg",
            )
        )
        await session.commit()

        art = await tmdb_svc.artwork_for(session, [programme])
        # Backdrop wins: the card it washes is wide and short, a shape a 2:3
        # poster only shows a narrow band of.
        assert art == {programme.id: "https://img.example.com/backdrop.jpg"}


async def test_artwork_for_falls_back_to_poster_and_skips_negatives(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, programme_id = await _seed(app_client, captured_emails, monkeypatch)

    from app.db import get_sessionmaker
    from app.models.epg import Programme
    from app.models.tmdb import MediaType, TmdbEnrichment
    from app.services import tmdb as tmdb_svc

    async with get_sessionmaker()() as session:
        programme = await session.get(Programme, uuid.UUID(programme_id))
        assert programme is not None
        key, year_key = tmdb_svc.cache_key(programme.title, programme.year)

        row = TmdbEnrichment(
            media_type=MediaType.movie,
            query_key=key,
            query_year=year_key,
            fetched_at=datetime.now(UTC),
            backdrop_url=None,
            poster_url="https://img.example.com/poster.jpg",
        )
        session.add(row)
        await session.commit()
        assert await tmdb_svc.artwork_for(session, [programme]) == {
            programme.id: "https://img.example.com/poster.jpg"
        }

        # A cached no-match is excluded on the negative flag alone. Leaving the
        # poster URL in place is the point: clearing it too would let this pass
        # with the flag ignored entirely, which is the bug it exists to catch.
        row.negative = True
        await session.commit()
        assert await tmdb_svc.artwork_for(session, [programme]) == {}
