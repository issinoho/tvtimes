from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from app.ingest.models import Channel as ParsedChannel
from app.ingest.models import Playlist
from app.ingest.ssrf import BytesResult
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

# A window the refresh will accept: today .. +2 days.
_BASE = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)


def _xml() -> bytes:
    s = _BASE.strftime("%Y%m%d%H%M%S")
    e = (_BASE + timedelta(hours=1)).strftime("%Y%m%d%H%M%S")
    return f"""<?xml version="1.0"?>
    <tv>
      <channel id="news.uk"><display-name>News HD</display-name></channel>
      <programme channel="news.uk" start="{s} +0000" stop="{e} +0000">
        <title>Headlines</title><category>News</category>
      </programme>
    </tv>""".encode()


@pytest.fixture(autouse=True)
def _no_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr("app.api.routers.sources.enqueue_source_refresh", _noop)
    monkeypatch.setattr("app.api.routers.epg.enqueue_epg_refresh", _noop)


async def _seed_source_with_channels(
    client: AsyncClient, emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, str], str]:
    await register_and_verify(client, emails)
    headers = auth_header(await login(client))

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[ParsedChannel(name="News HD", stream_ref="http://s/1", tvg_id="news.uk")],
            epg_url="http://epg.example.com/guide.xml",
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    resp = await client.post(
        "/api/sources",
        json={"kind": "m3u", "display_name": "P", "url": "http://feed.example.com/l.m3u"},
        headers=headers,
    )
    source_id = resp.json()["id"]

    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import epg as epg_svc
    from app.services import sources as src_svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        await src_svc.refresh_source(session, source)
        await epg_svc.ensure_epg_source_for(session, source)
        await session.commit()
    return headers, source_id


async def _run_epg_refresh(tenant_headers_ignored: object = None) -> int:
    from app.db import get_sessionmaker
    from app.models.epg import EpgSource
    from app.services import epg as epg_svc
    from sqlalchemy import select

    async with get_sessionmaker()() as session:
        row = await session.scalar(select(EpgSource))
        assert row is not None
        await epg_svc.refresh_epg_source(session, row)
        await session.commit()
        return row.programme_count


async def test_epg_refresh_populates_schedule(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, source_id = await _seed_source_with_channels(app_client, captured_emails, monkeypatch)

    async def fake_fetch(url: str, **kw: object) -> BytesResult:
        return BytesResult(200, _xml(), etag='"v1"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT")

    monkeypatch.setattr("app.services.epg.fetch_bytes", fake_fetch)
    assert await _run_epg_refresh() == 1

    # EPG source shows up on the list, tied to the source.
    listed = await app_client.get("/api/epg-sources", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["source_id"] == source_id
    assert listed.json()[0]["last_status"] == "ok"
    assert listed.json()[0]["programme_count"] == 1

    channels = await app_client.get(f"/api/sources/{source_id}/channels", headers=headers)
    channel_id = channels.json()["items"][0]["id"]

    sched = await app_client.get(
        f"/api/channels/{channel_id}/schedule",
        params={
            "from": (_BASE - timedelta(hours=1)).isoformat(),
            "to": (_BASE + timedelta(hours=3)).isoformat(),
        },
        headers=headers,
    )
    assert sched.status_code == 200, sched.text
    body = sched.json()
    assert body["timezone"] == "UTC"
    assert [p["title"] for p in body["programmes"]] == ["Headlines"]


async def test_guide_returns_rows_per_channel(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, source_id = await _seed_source_with_channels(app_client, captured_emails, monkeypatch)

    async def fake_fetch(url: str, **kw: object) -> BytesResult:
        return BytesResult(200, _xml(), etag=None, last_modified=None)

    monkeypatch.setattr("app.services.epg.fetch_bytes", fake_fetch)
    await _run_epg_refresh()

    resp = await app_client.get(
        "/api/guide",
        params={
            "from": (_BASE - timedelta(hours=1)).isoformat(),
            "to": (_BASE + timedelta(hours=3)).isoformat(),
            "source_id": source_id,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["channels"][0]["name"] == "News HD"
    assert body["channels"][0]["timezone"] == "UTC"
    assert [p["title"] for p in body["channels"][0]["programmes"]] == ["Headlines"]
    assert "from" in body


async def test_source_refresh_keeps_channel_ids_and_programmes(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, source_id = await _seed_source_with_channels(app_client, captured_emails, monkeypatch)

    async def fake_fetch(url: str, **kw: object) -> BytesResult:
        return BytesResult(200, _xml(), etag='"v1"', last_modified=None)

    monkeypatch.setattr("app.services.epg.fetch_bytes", fake_fetch)
    await _run_epg_refresh()

    before = await app_client.get(f"/api/sources/{source_id}/channels", headers=headers)
    channel_id = before.json()["items"][0]["id"]

    # A plain re-refresh with an unchanged playlist must not churn channel rows
    # (which would cascade-delete their programmes and leave the guide blank
    # until the EPG feed happens to change).
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import epg as epg_svc
    from app.services import sources as src_svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        changed = await src_svc.refresh_source(session, source)
        await epg_svc.ensure_epg_source_for(session, source, reset_cache=changed)
        await session.commit()
    assert changed is False

    after = await app_client.get(f"/api/sources/{source_id}/channels", headers=headers)
    assert after.json()["items"][0]["id"] == channel_id

    sched = await app_client.get(
        f"/api/channels/{channel_id}/schedule",
        params={
            "from": (_BASE - timedelta(hours=1)).isoformat(),
            "to": (_BASE + timedelta(hours=3)).isoformat(),
        },
        headers=headers,
    )
    assert [p["title"] for p in sched.json()["programmes"]] == ["Headlines"]


async def test_programmes_fan_out_to_channels_sharing_a_tvg_id(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two channels with the same tvg-id (mixed case vs the XMLTV's lower case)
    both get the schedule."""
    await register_and_verify(app_client, captured_emails)
    headers = auth_header(await login(app_client))

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        # Playlist stores mixed-case tvg-ids; the XMLTV below uses lower-case.
        return Playlist(
            channels=[
                ParsedChannel(name="TCM US East", stream_ref="http://s/e", tvg_id="TCM.us"),
                ParsedChannel(name="TCM US West", stream_ref="http://s/w", tvg_id="TCM.us"),
            ],
            epg_url="http://epg.example.com/guide.xml",
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    source_id = (
        await app_client.post(
            "/api/sources",
            json={"kind": "m3u", "display_name": "P", "url": "http://feed.example.com/l.m3u"},
            headers=headers,
        )
    ).json()["id"]

    s = _BASE.strftime("%Y%m%d%H%M%S")
    e = (_BASE + timedelta(hours=2)).strftime("%Y%m%d%H%M%S")
    xml = f"""<?xml version="1.0"?>
    <tv>
      <channel id="tcm.us"><display-name>TCM</display-name></channel>
      <programme channel="tcm.us" start="{s} +0000" stop="{e} +0000">
        <title>Casablanca</title><category>Movie</category>
      </programme>
    </tv>""".encode()

    async def fake_fetch(url: str, **kw: object) -> BytesResult:
        return BytesResult(200, xml, etag=None, last_modified=None)

    monkeypatch.setattr("app.services.epg.fetch_bytes", fake_fetch)

    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import epg as epg_svc
    from app.services import sources as src_svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        await src_svc.refresh_source(session, source)
        await epg_svc.ensure_epg_source_for(session, source)
        await session.commit()
    assert await _run_epg_refresh() == 2  # one programme row per channel

    guide = await app_client.get(
        "/api/guide",
        params={
            "from": (_BASE - timedelta(hours=1)).isoformat(),
            "to": (_BASE + timedelta(hours=4)).isoformat(),
            "source_id": source_id,
        },
        headers=headers,
    )
    rows = guide.json()["channels"]
    assert {r["name"] for r in rows} == {"TCM US East", "TCM US West"}
    for r in rows:
        assert [p["title"] for p in r["programmes"]] == ["Casablanca"]
        assert r["clock_shift_seconds"] == 0

    west = next(r for r in rows if r["name"] == "TCM US West")
    east = next(r for r in rows if r["name"] == "TCM US East")

    # Shift only the West feed by +2h.
    patched = await app_client.patch(
        f"/api/channels/{west['id']}", json={"clock_shift_seconds": 7200}, headers=headers
    )
    assert patched.status_code == 200, patched.text
    assert patched.json() == {"id": west["id"], "clock_shift_seconds": 7200}

    guide2 = await app_client.get(
        "/api/guide",
        params={
            "from": (_BASE - timedelta(hours=1)).isoformat(),
            "to": (_BASE + timedelta(hours=6)).isoformat(),
            "source_id": source_id,
        },
        headers=headers,
    )
    rows2 = {r["name"]: r for r in guide2.json()["channels"]}
    assert rows2["TCM US East"]["programmes"][0]["start"] == east["programmes"][0]["start"]
    east_start = datetime.fromisoformat(east["programmes"][0]["start"])
    west_start = datetime.fromisoformat(rows2["TCM US West"]["programmes"][0]["start"])
    assert (west_start - east_start) == timedelta(hours=2)
    assert rows2["TCM US West"]["clock_shift_seconds"] == 7200


async def test_patch_unknown_channel_is_404(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    headers = auth_header(await login(app_client))
    resp = await app_client.patch(
        f"/api/channels/{uuid.uuid4()}", json={"clock_shift_seconds": 0}, headers=headers
    )
    assert resp.status_code == 404


async def test_guide_orders_channels_by_source_rank(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    await register_and_verify(app_client, captured_emails)
    headers = auth_header(await login(app_client))

    def _ingest_named(chan_name: str, tvg: str) -> Callable[[object, object], Awaitable[Playlist]]:
        async def fake(_kind: object, _config: object) -> Playlist:
            return Playlist(
                channels=[ParsedChannel(name=chan_name, stream_ref=f"http://s/{tvg}", tvg_id=tvg)]
            )

        return fake

    src_ids = []
    for name, tvg in (("Alpha", "a.tv"), ("Bravo", "b.tv")):
        monkeypatch.setattr("app.services.sources._ingest", _ingest_named(f"{name} One", tvg))
        r = await app_client.post(
            "/api/sources",
            json={"kind": "m3u", "display_name": name, "url": f"http://feed/{tvg}.m3u"},
            headers=headers,
        )
        sid = r.json()["id"]
        src_ids.append(sid)
        from app.db import get_sessionmaker
        from app.models.source import Source
        from app.services import sources as src_svc

        async with get_sessionmaker()() as session:
            src = await session.get(Source, uuid.UUID(sid))
            assert src is not None
            await src_svc.refresh_source(session, src)
            await session.commit()

    def names(resp: object) -> list[str]:
        return [c["name"] for c in resp["channels"]]  # type: ignore[index]

    params = {
        "from": (_BASE - timedelta(hours=1)).isoformat(),
        "to": (_BASE + timedelta(hours=3)).isoformat(),
    }
    g1 = await app_client.get("/api/guide", params=params, headers=headers)
    assert names(g1.json()) == ["Alpha One", "Bravo One"]

    await app_client.put(
        "/api/sources/order", json={"ids": [src_ids[1], src_ids[0]]}, headers=headers
    )
    g2 = await app_client.get("/api/guide", params=params, headers=headers)
    assert names(g2.json()) == ["Bravo One", "Alpha One"]


async def test_guide_rejects_over_wide_window(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    headers = auth_header(await login(app_client))
    resp = await app_client.get(
        "/api/guide",
        params={
            "from": _BASE.isoformat(),
            "to": (_BASE + timedelta(days=3)).isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 422


async def test_conditional_get_304_keeps_programmes(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_source_with_channels(app_client, captured_emails, monkeypatch)

    async def first(url: str, **kw: object) -> BytesResult:
        return BytesResult(200, _xml(), etag='"v1"', last_modified=None)

    monkeypatch.setattr("app.services.epg.fetch_bytes", first)
    assert await _run_epg_refresh() == 1

    seen: dict[str, object] = {}

    async def second(url: str, **kw: object) -> BytesResult:
        seen.update(kw)
        return BytesResult(304, b"", kw.get("etag"), kw.get("last_modified"))  # type: ignore[arg-type]

    monkeypatch.setattr("app.services.epg.fetch_bytes", second)
    assert await _run_epg_refresh() == 1  # unchanged
    assert seen["etag"] == '"v1"'  # the stored validator was sent back


async def test_reset_cache_forces_a_full_reparse_even_on_304(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manual "Refresh" button passes force_epg=True, which clears the
    conditional-GET validators so stale programmes are always rebuilt."""
    _headers, source_id = await _seed_source_with_channels(app_client, captured_emails, monkeypatch)

    async def fetch(url: str, **kw: object) -> BytesResult:
        # Always a 200 with a validator; the point is whether we still *send*
        # If-None-Match after a reset.
        assert kw.get("etag") is None, "reset_cache should have cleared the stored etag"
        return BytesResult(200, _xml(), etag='"v1"', last_modified=None)

    monkeypatch.setattr("app.services.epg.fetch_bytes", fetch)
    assert await _run_epg_refresh() == 1

    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import epg as epg_svc
    from app.services import sources as src_svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        changed = await src_svc.refresh_source(session, source)
        assert changed is False  # nothing about the channels changed
        await epg_svc.ensure_epg_source_for(session, source, reset_cache=changed or True)
        await session.commit()

    # The next EPG refresh must re-fetch with no validator (assertion in fetch()).
    assert await _run_epg_refresh() == 1


async def test_create_standalone_epg_source_rejects_ssrf(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    headers = auth_header(await login(app_client))
    resp = await app_client.post(
        "/api/epg-sources", json={"url": "http://127.0.0.1/guide.xml"}, headers=headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "source_error"


async def test_cannot_delete_source_managed_epg(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _ = await _seed_source_with_channels(app_client, captured_emails, monkeypatch)
    epg_id = (await app_client.get("/api/epg-sources", headers=headers)).json()[0]["id"]
    resp = await app_client.request("DELETE", f"/api/epg-sources/{epg_id}", headers=headers)
    assert resp.status_code == 409


async def test_schedule_is_tenant_isolated(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, source_id = await _seed_source_with_channels(app_client, captured_emails, monkeypatch)
    channel_id = (
        await app_client.get(f"/api/sources/{source_id}/channels", headers=headers)
    ).json()["items"][0]["id"]

    await register_and_verify(app_client, captured_emails, email="other@example.com")
    other = auth_header(await login(app_client, email="other@example.com"))
    resp = await app_client.get(f"/api/channels/{channel_id}/schedule", headers=other)
    assert resp.status_code == 404
