"""Editing a source's connection in place: PATCH ``config`` merges over the
stored config (omitted fields kept), re-checks the URL, and queues a refresh
only when something actually changed."""

from __future__ import annotations

import uuid

import pytest
from app.ingest.models import Channel as ParsedChannel
from app.ingest.models import Playlist
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

M3U = {"kind": "m3u", "display_name": "Pluto", "url": "http://feed.example.com/old.m3u"}
XTREAM = {
    "kind": "xtream",
    "display_name": "Panel",
    "server_url": "http://panel.example.com:8080",
    "username": "alice",
    "password": "s3cret",
}


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    calls: list[uuid.UUID] = []

    async def _record(source_id: uuid.UUID) -> None:
        calls.append(source_id)

    monkeypatch.setattr("app.api.routers.sources.enqueue_source_refresh", _record)
    return calls


async def _headers(client: AsyncClient, emails: list[dict[str, str]]) -> dict[str, str]:
    await register_and_verify(client, emails)
    return auth_header(await login(client))


async def _config(source_id: str) -> dict[str, object]:
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import sources as svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        return svc.decrypt_config(source)


async def _run_refresh(source_id: str) -> None:
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import sources as svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        await svc.refresh_source(session, source)
        await session.commit()


async def test_new_playlist_url_queues_a_refresh_and_keeps_channel_ids(
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    enqueued: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await _headers(app_client, captured_emails)
    seen: list[object] = []

    async def fake_ingest(_kind: object, config: object) -> Playlist:
        seen.append(config)
        return Playlist(
            channels=[ParsedChannel(name="TCM", stream_ref="http://s/1", tvg_id="TCM.us")],
            epg_url=None,
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    sid = (await app_client.post("/api/sources", json=M3U, headers=headers)).json()["id"]
    await _run_refresh(sid)
    before = await app_client.get(f"/api/sources/{sid}/channels", headers=headers)
    enqueued.clear()

    resp = await app_client.patch(
        f"/api/sources/{sid}",
        json={"config": {"kind": "m3u", "url": "http://feed.example.com/new.m3u"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["config_summary"] == "http://feed.example.com/new.m3u"
    assert resp.json()["last_status"] == "pending"
    assert enqueued == [uuid.UUID(sid)]

    await _run_refresh(sid)
    assert seen[-1] == {"url": "http://feed.example.com/new.m3u"}
    after = await app_client.get(f"/api/sources/{sid}/channels", headers=headers)
    assert [c["id"] for c in after.json()["items"]] == [c["id"] for c in before.json()["items"]]


async def test_omitted_fields_keep_the_stored_credentials(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    sid = (await app_client.post("/api/sources", json=XTREAM, headers=headers)).json()["id"]

    resp = await app_client.patch(
        f"/api/sources/{sid}",
        json={"config": {"kind": "xtream", "server_url": "http://new-panel.example.com/"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert await _config(sid) == {
        "server_url": "http://new-panel.example.com",
        "username": "alice",
        "password": "s3cret",
        "output": "ts",
    }


async def test_an_unchanged_connection_does_not_refresh(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    sid = (await app_client.post("/api/sources", json=M3U, headers=headers)).json()["id"]
    enqueued.clear()

    resp = await app_client.patch(
        f"/api/sources/{sid}",
        json={"display_name": "Pluto TV", "config": {"kind": "m3u", "url": M3U["url"]}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Pluto TV"
    assert enqueued == []


async def test_config_for_another_kind_is_rejected(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    sid = (await app_client.post("/api/sources", json=M3U, headers=headers)).json()["id"]
    resp = await app_client.patch(
        f"/api/sources/{sid}",
        json={"config": {"kind": "hdhomerun", "device_url": "http://192.168.1.50"}},
        headers=headers,
    )
    assert resp.status_code == 422
    assert await _config(sid) == {"url": M3U["url"]}


async def test_a_rejected_url_leaves_the_whole_edit_unapplied(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    sid = (await app_client.post("/api/sources", json=M3U, headers=headers)).json()["id"]
    resp = await app_client.patch(
        f"/api/sources/{sid}",
        json={
            "display_name": "Renamed",
            "config": {"kind": "m3u", "url": "http://169.254.169.254/latest/"},
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "source_error"
    got = await app_client.get(f"/api/sources/{sid}", headers=headers)
    assert got.json()["display_name"] == "Pluto"
    assert await _config(sid) == {"url": M3U["url"]}


async def test_hdhomerun_blank_address_switches_to_auto_discover(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    created = await app_client.post(
        "/api/sources",
        json={"kind": "hdhomerun", "display_name": "Tuner", "device_url": "http://192.168.1.50"},
        headers=headers,
    )
    sid = created.json()["id"]

    kept = await app_client.patch(
        f"/api/sources/{sid}", json={"config": {"kind": "hdhomerun"}}, headers=headers
    )
    assert kept.json()["config_summary"] == "http://192.168.1.50"

    cleared = await app_client.patch(
        f"/api/sources/{sid}",
        json={"config": {"kind": "hdhomerun", "device_url": ""}},
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["config_summary"] == "auto-discover on LAN"


async def test_stalker_serial_can_be_cleared(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    created = await app_client.post(
        "/api/sources",
        json={
            "kind": "stalker",
            "display_name": "Portal",
            "portal_url": "http://portal.example.com/c/",
            "mac": "00:1a:79:00:00:01",
            "serial": "ABC123",
        },
        headers=headers,
    )
    sid = created.json()["id"]
    resp = await app_client.patch(
        f"/api/sources/{sid}",
        json={"config": {"kind": "stalker", "serial": ""}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    cfg = await _config(sid)
    assert cfg["serial"] is None
    assert cfg["mac"] == "00:1A:79:00:00:01"
