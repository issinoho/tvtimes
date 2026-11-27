"""An XMLTV URL attached on one source's page matches only that source's
channels; an unscoped one stays tenant-wide."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.ingest.models import Channel as ParsedChannel
from app.ingest.models import Playlist
from app.ingest.ssrf import BytesResult
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

_BASE = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
_GUIDE_URL = "http://guide.example.com/epg.xml"


def _xml() -> bytes:
    s = _BASE.strftime("%Y%m%d%H%M%S")
    e = (_BASE + timedelta(hours=1)).strftime("%Y%m%d%H%M%S")
    return f"""<?xml version="1.0"?>
    <tv>
      <channel id="tcm.us"><display-name>TCM</display-name></channel>
      <programme channel="tcm.us" start="{s} +0000" stop="{e} +0000">
        <title>Casablanca</title>
      </programme>
    </tv>""".encode()


@pytest.fixture(autouse=True)
def _stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_id: uuid.UUID) -> None:
        return None

    async def fake_fetch(url: str, **kw: object) -> BytesResult:
        return BytesResult(200, _xml(), etag='"v1"', last_modified=None)

    monkeypatch.setattr("app.api.routers.sources.enqueue_source_refresh", _noop)
    monkeypatch.setattr("app.api.routers.epg.enqueue_epg_refresh", _noop)
    monkeypatch.setattr("app.services.epg.fetch_bytes", fake_fetch)


async def _two_sources(
    client: AsyncClient, emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, str], str, str]:
    """Two playlist sources (no EPG of their own), each with one channel
    carrying the same tvg-id, so a tenant-wide feed would hit both."""
    await register_and_verify(client, emails)
    headers = auth_header(await login(client))

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[ParsedChannel(name="TCM", stream_ref="http://s/1", tvg_id="TCM.us")],
            epg_url=None,
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    ids = []
    for name in ("A", "B"):
        resp = await client.post(
            "/api/sources",
            json={"kind": "m3u", "display_name": name, "url": f"http://feed.example.com/{name}"},
            headers=headers,
        )
        ids.append(resp.json()["id"])

    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import sources as src_svc

    async with get_sessionmaker()() as session:
        for sid in ids:
            source = await session.get(Source, uuid.UUID(sid))
            assert source is not None
            await src_svc.refresh_source(session, source)
        await session.commit()
    return headers, ids[0], ids[1]


async def _refresh(epg_id: str) -> int:
    from app.db import get_sessionmaker
    from app.models.epg import EpgSource
    from app.services import epg as epg_svc

    async with get_sessionmaker()() as session:
        row = await session.get(EpgSource, uuid.UUID(epg_id))
        assert row is not None
        await epg_svc.refresh_epg_source(session, row)
        await session.commit()
        return row.programme_count


async def _titles_by_source(
    client: AsyncClient, headers: dict[str, str], source_id: str
) -> list[str]:
    guide = await client.get(
        "/api/guide",
        params={
            "from": (_BASE - timedelta(hours=1)).isoformat(),
            "to": (_BASE + timedelta(hours=3)).isoformat(),
            "source_id": source_id,
        },
        headers=headers,
    )
    assert guide.status_code == 200, guide.text
    return [p["title"] for r in guide.json()["channels"] for p in r["programmes"]]


async def test_unscoped_feed_matches_every_source(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, a, b = await _two_sources(app_client, captured_emails, monkeypatch)
    resp = await app_client.post("/api/epg-sources", json={"url": _GUIDE_URL}, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["scope_source_id"] is None
    assert await _refresh(resp.json()["id"]) == 2
    assert await _titles_by_source(app_client, headers, a) == ["Casablanca"]
    assert await _titles_by_source(app_client, headers, b) == ["Casablanca"]


async def test_scoped_feed_matches_only_its_source(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, a, b = await _two_sources(app_client, captured_emails, monkeypatch)
    resp = await app_client.post(
        "/api/epg-sources", json={"url": _GUIDE_URL, "scope_source_id": a}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["scope_source_id"] == a
    assert await _refresh(resp.json()["id"]) == 1
    assert await _titles_by_source(app_client, headers, a) == ["Casablanca"]
    assert await _titles_by_source(app_client, headers, b) == []


async def test_reattaching_on_a_source_narrows_a_tenant_wide_feed(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, a, b = await _two_sources(app_client, captured_emails, monkeypatch)
    first = await app_client.post("/api/epg-sources", json={"url": _GUIDE_URL}, headers=headers)
    epg_id = first.json()["id"]
    assert await _refresh(epg_id) == 2

    again = await app_client.post(
        "/api/epg-sources", json={"url": _GUIDE_URL, "scope_source_id": a}, headers=headers
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] == epg_id
    assert again.json()["scope_source_id"] == a
    assert again.json()["last_status"] == "pending"

    # The refresh drops what the wide feed had written onto source B.
    assert await _refresh(epg_id) == 1
    assert await _titles_by_source(app_client, headers, b) == []

    # Re-attaching without a scope leaves the narrowed row alone.
    unscoped = await app_client.post("/api/epg-sources", json={"url": _GUIDE_URL}, headers=headers)
    assert unscoped.json()["scope_source_id"] == a


async def test_cannot_attach_a_feed_scoped_to_another_source(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, a, b = await _two_sources(app_client, captured_emails, monkeypatch)
    await app_client.post(
        "/api/epg-sources", json={"url": _GUIDE_URL, "scope_source_id": a}, headers=headers
    )
    resp = await app_client.post(
        "/api/epg-sources", json={"url": _GUIDE_URL, "scope_source_id": b}, headers=headers
    )
    assert resp.status_code == 409
    assert "A" in resp.json()["detail"]


async def test_scope_must_be_one_of_your_sources(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    headers = auth_header(await login(app_client))
    resp = await app_client.post(
        "/api/epg-sources",
        json={"url": _GUIDE_URL, "scope_source_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_deleting_the_source_removes_its_scoped_feed(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, a, _ = await _two_sources(app_client, captured_emails, monkeypatch)
    await app_client.post(
        "/api/epg-sources", json={"url": _GUIDE_URL, "scope_source_id": a}, headers=headers
    )
    deleted = await app_client.delete(f"/api/sources/{a}", headers=headers)
    assert deleted.status_code in (200, 204), deleted.text
    listed = await app_client.get("/api/epg-sources", headers=headers)
    assert listed.json() == []


async def _advertise(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[ParsedChannel(name="TCM", stream_ref="http://s/1", tvg_id="TCM.us")],
            epg_url=url,
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)


async def _refresh_source(source_id: str) -> tuple[str, uuid.UUID | None]:
    """The worker's refresh_source body: channels, then the discovered feed,
    in one transaction. Returns the source's status and the feed row id."""
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import epg as epg_svc
    from app.services import sources as src_svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        changed = await src_svc.refresh_source(session, source)
        row = await epg_svc.ensure_epg_source_for(session, source, reset_cache=changed)
        await session.commit()
        return source.last_status.value, row.id if row else None


async def _epg_rows() -> list[tuple[uuid.UUID | None, uuid.UUID | None]]:
    from app.db import get_sessionmaker
    from app.models.epg import EpgSource
    from sqlalchemy import select

    async with get_sessionmaker()() as session:
        rows = await session.scalars(select(EpgSource).where(EpgSource.url == _GUIDE_URL))
        return [(r.source_id, r.scope_source_id) for r in rows]


async def test_playlist_advertising_an_attached_url_reuses_it(
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A playlist that advertises a URL already attached by hand must not try
    to insert a second row (unique per tenant): that rolled the whole refresh
    back and left the source stuck at "pending"."""
    headers, a, _b = await _two_sources(app_client, captured_emails, monkeypatch)
    resp = await app_client.post(
        "/api/epg-sources", json={"url": _GUIDE_URL, "scope_source_id": a}, headers=headers
    )
    assert resp.status_code in (200, 201), resp.text
    attached = uuid.UUID(resp.json()["id"])

    await _advertise(monkeypatch, _GUIDE_URL)
    status, row_id = await _refresh_source(a)
    assert status == "ok"
    assert row_id == attached
    assert await _epg_rows() == [(None, uuid.UUID(a))]


async def test_two_playlists_advertising_one_url_share_the_row(
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _headers, a, b = await _two_sources(app_client, captured_emails, monkeypatch)
    await _advertise(monkeypatch, _GUIDE_URL)
    status_a, row_a = await _refresh_source(a)
    status_b, row_b = await _refresh_source(b)
    assert (status_a, status_b) == ("ok", "ok")
    assert row_a is not None and row_a == row_b
    assert await _epg_rows() == [(uuid.UUID(a), None)]  # discovered: tenant-wide


async def test_advertised_url_scoped_to_another_source_is_left_alone(
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, a, b = await _two_sources(app_client, captured_emails, monkeypatch)
    resp = await app_client.post(
        "/api/epg-sources", json={"url": _GUIDE_URL, "scope_source_id": a}, headers=headers
    )
    assert resp.status_code in (200, 201), resp.text

    await _advertise(monkeypatch, _GUIDE_URL)
    status, row_id = await _refresh_source(b)
    assert status == "ok"
    assert row_id is None
    assert await _epg_rows() == [(None, uuid.UUID(a))]  # scope not widened


async def test_switching_to_an_already_known_url_drops_the_old_row(
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _headers, a, b = await _two_sources(app_client, captured_emails, monkeypatch)
    await _advertise(monkeypatch, "http://guide.example.com/other.xml")
    await _refresh_source(b)  # b discovers its own feed first
    await _advertise(monkeypatch, _GUIDE_URL)
    _, row_a = await _refresh_source(a)
    status, row_b = await _refresh_source(b)  # b now advertises the URL a already has
    assert status == "ok"
    assert row_b == row_a
    assert await _epg_rows() == [(uuid.UUID(a), None)]
