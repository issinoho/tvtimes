"""Hiding channels: unticked ones leave the guide, search, highlights and the
exports, survive a source refresh, and can be shown or hidden in bulk by the
channel list's own filter."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.ingest.models import Channel as ParsedChannel
from app.ingest.models import Playlist
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

SOURCE = {"kind": "m3u", "display_name": "UK", "url": "http://feed.example.com/uk.m3u"}
CHANNELS = [
    ParsedChannel(name="BBC One", stream_ref="http://s/1", tvg_id="bbc1", group_title="UK"),
    ParsedChannel(name="BBC Two", stream_ref="http://s/2", tvg_id="bbc2", group_title="UK"),
    ParsedChannel(name="Film4", stream_ref="http://s/3", tvg_id="film4", group_title="Movies"),
]


@pytest.fixture(autouse=True)
def _fake_source(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _skip(_source_id: uuid.UUID) -> None:
        return None

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(channels=list(CHANNELS))

    async def no_logo_index() -> dict[str, str]:
        return {}

    monkeypatch.setattr("app.api.routers.sources.enqueue_source_refresh", _skip)
    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    monkeypatch.setattr("app.services.sources.channel_logos.load_index", no_logo_index)


async def _refresh(source_id: str) -> None:
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import sources as svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        await svc.refresh_source(session, source)
        await session.commit()


async def _setup(
    client: AsyncClient, emails: list[dict[str, str]]
) -> tuple[dict[str, str], str, dict[str, str]]:
    """Headers, source id, and channel name -> id; each channel has a film on
    air now called "<name> Film"."""
    from app.db import get_sessionmaker
    from app.models.epg import EpgSource, EpgStatus, Programme
    from app.models.source import Source

    await register_and_verify(client, emails)
    headers = auth_header(await login(client))
    sid = (await client.post("/api/sources", json=SOURCE, headers=headers)).json()["id"]
    await _refresh(sid)
    items = (await client.get(f"/api/sources/{sid}/channels", headers=headers)).json()["items"]
    ids = {c["name"]: c["id"] for c in items}

    now = datetime.now(UTC)
    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(sid))
        assert source is not None
        feed = EpgSource(
            tenant_id=source.tenant_id, url="http://epg.example/x.xml", last_status=EpgStatus.ok
        )
        session.add(feed)
        await session.flush()
        for name, cid in ids.items():
            session.add(
                Programme(
                    tenant_id=source.tenant_id,
                    channel_id=uuid.UUID(cid),
                    epg_source_id=feed.id,
                    start_utc=now - timedelta(minutes=10),
                    stop_utc=now + timedelta(minutes=50),
                    title=f"{name} Film",
                    is_movie=True,
                )
            )
        await session.commit()
    return headers, sid, ids


async def _guide_ids(client: AsyncClient, headers: dict[str, str]) -> set[str]:
    guide = await client.get("/api/guide", headers=headers)
    assert guide.status_code == 200, guide.text
    return {c["id"] for c in guide.json()["channels"]}


async def _export_m3u(sid: str) -> str:
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.models.tenant import Tenant
    from app.services import exports

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(sid))
        assert source is not None
        tenant = await session.get(Tenant, source.tenant_id)
        assert tenant is not None
        return await exports.render_m3u(session, tenant, base_url="https://tv.example", token="T")


async def test_a_hidden_channel_leaves_the_guide_and_exports_and_survives_refresh(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers, sid, ids = await _setup(app_client, captured_emails)
    two = ids["BBC Two"]

    resp = await app_client.patch(f"/api/channels/{two}", json={"hidden": True}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["hidden"] is True

    assert await _guide_ids(app_client, headers) == {ids["BBC One"], ids["Film4"]}
    now_next = (await app_client.get("/api/guide/now-next", headers=headers)).json()
    assert two not in {r["channel"]["id"] for r in now_next["channels"]}
    search = (
        await app_client.get("/api/guide/search", params={"q": "Film"}, headers=headers)
    ).json()
    assert "BBC Two Film" not in {r["programme"]["title"] for r in search["results"]}
    assert "BBC One Film" in {r["programme"]["title"] for r in search["results"]}
    highlights = (await app_client.get("/api/guide/highlights", headers=headers)).json()
    assert two not in {h["channel"]["id"] for h in highlights["films_soon"]}
    m3u = await _export_m3u(sid)
    assert "BBC Two" not in m3u
    assert "BBC One" in m3u

    # still listed on the source (so it can be ticked again), and still hidden
    # after the source refreshes in place
    await _refresh(sid)
    items = (await app_client.get(f"/api/sources/{sid}/channels", headers=headers)).json()["items"]
    assert {c["name"]: c["hidden"] for c in items} == {
        "BBC One": False,
        "BBC Two": True,
        "Film4": False,
    }

    resp = await app_client.patch(f"/api/channels/{two}", json={"hidden": False}, headers=headers)
    assert resp.json()["hidden"] is False
    assert two in await _guide_ids(app_client, headers)


async def test_bulk_show_and_hide_follow_the_list_filter(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers, sid, ids = await _setup(app_client, captured_emails)
    url = f"/api/sources/{sid}/channels/visibility"

    resp = await app_client.post(url, json={"hidden": True, "group": "UK"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated": 2}
    assert await _guide_ids(app_client, headers) == {ids["Film4"]}

    # only channels that actually change are counted
    resp = await app_client.post(url, json={"hidden": True}, headers=headers)
    assert resp.json() == {"updated": 1}
    assert await _guide_ids(app_client, headers) == set()

    resp = await app_client.post(url, json={"hidden": False, "search": "bbc o"}, headers=headers)
    assert resp.json() == {"updated": 1}
    assert await _guide_ids(app_client, headers) == {ids["BBC One"]}


async def test_bulk_visibility_is_scoped_to_your_own_source(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers, _sid, _ids = await _setup(app_client, captured_emails)
    resp = await app_client.post(
        f"/api/sources/{uuid.uuid4()}/channels/visibility", json={"hidden": True}, headers=headers
    )
    assert resp.status_code == 404
