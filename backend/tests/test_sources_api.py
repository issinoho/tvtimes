from __future__ import annotations

import uuid

import pytest
from app.ingest.models import Channel as ParsedChannel
from app.ingest.models import Playlist
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

M3U_BODY = {
    "kind": "m3u",
    "display_name": "My playlist",
    "url": "http://feed.example.com/list.m3u",
}


@pytest.fixture(autouse=True)
def _no_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_source_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr("app.api.routers.sources.enqueue_source_refresh", _noop)


async def _auth(
    app_client: AsyncClient, emails: list[dict[str, str]], email: str
) -> dict[str, str]:
    await register_and_verify(app_client, emails, email=email)
    return auth_header(await login(app_client, email=email))


async def _run_refresh(source_id: str) -> None:
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import sources as svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        await svc.refresh_source(session, source)
        await session.commit()


async def test_create_list_and_refresh_m3u_source(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")

    resp = await app_client.post("/api/sources", json=M3U_BODY, headers=headers)
    assert resp.status_code == 201, resp.text
    source = resp.json()
    assert source["kind"] == "m3u"
    assert source["last_status"] == "pending"
    assert source["config_summary"] == "http://feed.example.com/list.m3u"

    listed = await app_client.get("/api/sources", headers=headers)
    assert [s["id"] for s in listed.json()] == [source["id"]]

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[
                ParsedChannel(
                    name="News HD", stream_ref="http://s/1", tvg_id="news", group_title="News"
                ),
                ParsedChannel(name="Movies", stream_ref="http://s/2", group_title="Movies"),
            ],
            epg_url="http://epg.example.com/x.xml",
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    await _run_refresh(source["id"])

    detail = await app_client.get(f"/api/sources/{source['id']}", headers=headers)
    assert detail.json()["last_status"] == "ok"
    assert detail.json()["channel_count"] == 2
    assert detail.json()["epg_url"] == "http://epg.example.com/x.xml"

    channels = await app_client.get(f"/api/sources/{source['id']}/channels", headers=headers)
    body = channels.json()
    assert body["total"] == 2
    assert {c["name"] for c in body["items"]} == {"News HD", "Movies"}
    assert body["items"][0]["is_hd"] is True

    filtered = await app_client.get(
        f"/api/sources/{source['id']}/channels?search=news", headers=headers
    )
    assert [c["name"] for c in filtered.json()["items"]] == ["News HD"]


async def test_create_rejects_ssrf_url(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    resp = await app_client.post(
        "/api/sources",
        json={**M3U_BODY, "url": "http://169.254.169.254/latest/"},
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "source_error"


async def test_create_allows_a_lan_url_on_the_fetch_allowlist(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    headers = await _auth(app_client, captured_emails, "sam@example.com")

    rejected = await app_client.post(
        "/api/sources",
        json={**M3U_BODY, "url": "http://192.168.0.218:5523/feeds/pluto-us/m3u"},
        headers=headers,
    )
    assert rejected.status_code == 422  # blocked by default

    monkeypatch.setenv("TVTIMES_FETCH_ALLOWLIST", "192.168.0.0/24")
    get_settings.cache_clear()
    allowed = await app_client.post(
        "/api/sources",
        json={**M3U_BODY, "url": "http://192.168.0.218:5523/feeds/pluto-us/m3u"},
        headers=headers,
    )
    assert allowed.status_code == 201, allowed.text


async def test_xtream_config_summary_hides_password(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    resp = await app_client.post(
        "/api/sources",
        json={
            "kind": "xtream",
            "display_name": "Panel",
            "server_url": "http://panel.example.com:8080",
            "username": "bob",
            "password": "sup3rs3cret",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    assert "sup3rs3cret" not in resp.text
    assert "panel.example.com" in resp.json()["config_summary"]


async def test_same_tvg_id_different_names_are_kept_separate(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    source = (await app_client.post("/api/sources", json=M3U_BODY, headers=headers)).json()

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[
                # Same tvg-id, different names -> kept.
                ParsedChannel(name="TCM US East", stream_ref="http://s/e", tvg_id="TCM.us"),
                ParsedChannel(name="TCM US West", stream_ref="http://s/w", tvg_id="TCM.us"),
                # Same tvg-id AND name but a different stream -> still kept
                # (a playlist that labels both feeds just "TCM").
                ParsedChannel(name="TCM", stream_ref="http://s/east", tvg_id="TCM.us"),
                ParsedChannel(name="TCM", stream_ref="http://s/west", tvg_id="TCM.us"),
                # Byte-for-byte duplicate line -> collapsed.
                ParsedChannel(name="TCM US East", stream_ref="http://s/e", tvg_id="TCM.us"),
            ],
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    await _run_refresh(source["id"])

    body = (await app_client.get(f"/api/sources/{source['id']}/channels", headers=headers)).json()
    assert body["total"] == 4
    assert sorted(c["name"] for c in body["items"]) == ["TCM", "TCM", "TCM US East", "TCM US West"]


async def test_sources_can_be_reordered(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    ids = []
    for name in ("A", "B", "C"):
        r = await app_client.post(
            "/api/sources", json={**M3U_BODY, "display_name": name}, headers=headers
        )
        ids.append(r.json()["id"])
    initial = (await app_client.get("/api/sources", headers=headers)).json()
    assert [s["sort_rank"] for s in initial] == [0, 1, 2]

    reordered = [ids[2], ids[0], ids[1]]
    resp = await app_client.put("/api/sources/order", json={"ids": reordered}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert [s["id"] for s in resp.json()] == reordered
    assert [s["sort_rank"] for s in resp.json()] == [0, 1, 2]

    listed = await app_client.get("/api/sources", headers=headers)
    assert [s["display_name"] for s in listed.json()] == ["C", "A", "B"]


async def test_reorder_rejects_incomplete_id_list(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    a = (await app_client.post("/api/sources", json=M3U_BODY, headers=headers)).json()["id"]
    (await app_client.post("/api/sources", json=M3U_BODY, headers=headers)).json()

    resp = await app_client.put("/api/sources/order", json={"ids": [a]}, headers=headers)
    assert resp.status_code == 422


async def test_missing_logo_is_backfilled_from_iptv_org(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    source = (await app_client.post("/api/sources", json=M3U_BODY, headers=headers)).json()

    async def fake_index(**_kw: object) -> dict[str, str]:
        return {"bbc one": "https://logos/bbc1.png"}

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[
                ParsedChannel(name="BBC One", stream_ref="http://s/1"),  # no tvg-logo
                ParsedChannel(name="Some Local Channel", stream_ref="http://s/2"),
            ],
        )

    monkeypatch.setattr("app.services.sources.channel_logos.load_index", fake_index)
    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    await _run_refresh(source["id"])

    items = (await app_client.get(f"/api/sources/{source['id']}/channels", headers=headers)).json()[
        "items"
    ]
    by_name = {c["name"]: c for c in items}
    assert by_name["BBC One"]["logo_url"] == "https://logos/bbc1.png"
    assert by_name["Some Local Channel"]["logo_url"] is None


async def test_playlist_logo_wins_over_backfill(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    source = (await app_client.post("/api/sources", json=M3U_BODY, headers=headers)).json()

    async def fake_index(**_kw: object) -> dict[str, str]:
        return {"bbc one": "https://logos/generic.png"}

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[
                ParsedChannel(
                    name="BBC One", stream_ref="http://s/1", tvg_logo="https://feed/mine.png"
                )
            ],
        )

    monkeypatch.setattr("app.services.sources.channel_logos.load_index", fake_index)
    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    await _run_refresh(source["id"])

    items = (await app_client.get(f"/api/sources/{source['id']}/channels", headers=headers)).json()[
        "items"
    ]
    assert items[0]["logo_url"] == "https://feed/mine.png"


async def test_create_hdhomerun_source(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    resp = await app_client.post(
        "/api/sources",
        json={
            "kind": "hdhomerun",
            "display_name": "Living room tuner",
            "device_url": "http://192.168.1.50",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    source = resp.json()
    assert source["kind"] == "hdhomerun"
    assert source["config_summary"] == "http://192.168.1.50"

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[ParsedChannel(name="BBC One HD", stream_ref="http://192.168.1.50/auto/v2.1")],
            epg_url="https://api.hdhomerun.com/api/xmltv?DeviceAuth=x",
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    await _run_refresh(source["id"])
    detail = await app_client.get(f"/api/sources/{source['id']}", headers=headers)
    assert detail.json()["last_status"] == "ok"
    assert detail.json()["channel_count"] == 1


async def test_hdhomerun_blank_url_means_auto_discover(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    resp = await app_client.post(
        "/api/sources",
        json={"kind": "hdhomerun", "display_name": "Auto"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["config_summary"] == "auto-discover on LAN"


async def test_sources_are_tenant_isolated(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    a_headers = await _auth(app_client, captured_emails, "a@example.com")
    created = await app_client.post("/api/sources", json=M3U_BODY, headers=a_headers)
    source_id = created.json()["id"]

    b_headers = await _auth(app_client, captured_emails, "b@example.com")
    assert (await app_client.get(f"/api/sources/{source_id}", headers=b_headers)).status_code == 404
    assert (await app_client.get("/api/sources", headers=b_headers)).json() == []


async def test_patch_and_delete_source(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    source_id = (await app_client.post("/api/sources", json=M3U_BODY, headers=headers)).json()["id"]

    patched = await app_client.patch(
        f"/api/sources/{source_id}",
        json={"display_name": "Renamed", "enabled": False, "clock_shift_seconds": 3600},
        headers=headers,
    )
    assert patched.json()["display_name"] == "Renamed"
    assert patched.json()["enabled"] is False
    assert patched.json()["clock_shift_seconds"] == 3600

    deleted = await app_client.delete(f"/api/sources/{source_id}", headers=headers)
    assert deleted.status_code == 200
    assert (await app_client.get(f"/api/sources/{source_id}", headers=headers)).status_code == 404


async def test_requires_verified_email(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    resp = await app_client.get("/api/sources")
    assert resp.status_code == 401
