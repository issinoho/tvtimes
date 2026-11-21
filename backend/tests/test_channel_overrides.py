"""Hand-set channel category and logo: applied at once, kept across source
refreshes, cleared back to the source's own, and carried into the exports."""

from __future__ import annotations

import uuid

import pytest
from app.ingest.models import Channel as ParsedChannel
from app.ingest.models import Playlist
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

STREAM = "https://cdn.example.com/live/abc/master.m3u8"
SOURCE = {"kind": "m3u", "display_name": "SFB Sports 1", "url": STREAM}


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _skip(_source_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr("app.api.routers.sources.enqueue_source_refresh", _skip)


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    """What the fake source says; tests change it between refreshes."""
    says: dict[str, str | None] = {"group": None, "logo": None}

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[
                ParsedChannel(
                    name="SFB Sports 1",
                    stream_ref=STREAM,
                    group_title=says["group"],
                    tvg_logo=says["logo"],
                )
            ]
        )

    async def no_logo_index() -> dict[str, str]:
        return {}

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    monkeypatch.setattr("app.services.sources.channel_logos.load_index", no_logo_index)
    return says


async def _refresh(source_id: str) -> None:
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import sources as svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        await svc.refresh_source(session, source)
        await session.commit()


async def _setup(client: AsyncClient, emails: list[dict[str, str]]) -> tuple[dict[str, str], str]:
    await register_and_verify(client, emails)
    headers = auth_header(await login(client))
    sid = (await client.post("/api/sources", json=SOURCE, headers=headers)).json()["id"]
    await _refresh(sid)
    return headers, sid


async def _channel(client: AsyncClient, headers: dict[str, str], sid: str) -> dict[str, object]:
    items = (await client.get(f"/api/sources/{sid}/channels", headers=headers)).json()["items"]
    assert len(items) == 1
    channel: dict[str, object] = items[0]
    return channel


async def test_a_category_survives_refresh_and_clears_to_the_sources(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], upstream: dict[str, str | None]
) -> None:
    upstream["group"] = "Live"
    headers, sid = await _setup(app_client, captured_emails)
    cid = (await _channel(app_client, headers, sid))["id"]

    resp = await app_client.patch(
        f"/api/channels/{cid}", json={"group_override": " Sports "}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["group_override"] == "Sports"
    assert resp.json()["group_title"] == "Sports"

    # The source changing its own category doesn't undo the override...
    upstream["group"] = "Events"
    await _refresh(sid)
    ch = await _channel(app_client, headers, sid)
    assert ch["group_title"] == "Sports"
    assert ch["upstream_group_title"] == "Events"
    assert ch["id"] == cid

    # ...and the guide's category filter finds it there.
    guide = await app_client.get("/api/guide", params={"group": "Sports"}, headers=headers)
    assert guide.status_code == 200, guide.text
    assert [c["id"] for c in guide.json()["channels"]] == [cid]

    # Clearing restores what the source says now, without waiting for a refresh.
    resp = await app_client.patch(
        f"/api/channels/{cid}", json={"group_override": ""}, headers=headers
    )
    assert resp.json()["group_override"] is None
    assert resp.json()["group_title"] == "Events"


async def test_a_logo_survives_refresh_and_clears_to_the_sources(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], upstream: dict[str, str | None]
) -> None:
    headers, sid = await _setup(app_client, captured_emails)
    cid = (await _channel(app_client, headers, sid))["id"]
    assert (await _channel(app_client, headers, sid))["logo_url"] is None

    logo = "https://img.example.com/sfb.png"
    resp = await app_client.patch(
        f"/api/channels/{cid}", json={"logo_override": logo}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["logo_url"] == logo

    upstream["logo"] = "http://192.168.0.2/upstream.png"
    await _refresh(sid)
    ch = await _channel(app_client, headers, sid)
    assert ch["logo_url"] == logo
    assert ch["upstream_logo_url"] == "http://192.168.0.2/upstream.png"

    resp = await app_client.patch(
        f"/api/channels/{cid}", json={"logo_override": ""}, headers=headers
    )
    assert resp.json()["logo_url"] == "http://192.168.0.2/upstream.png"


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:image/png;base64,AAAA", "sfb.png"])
async def test_a_logo_must_be_an_http_url(
    bad: str,
    app_client: AsyncClient,
    captured_emails: list[dict[str, str]],
    upstream: dict[str, str | None],
) -> None:
    headers, sid = await _setup(app_client, captured_emails)
    cid = (await _channel(app_client, headers, sid))["id"]
    resp = await app_client.patch(
        f"/api/channels/{cid}", json={"logo_override": bad}, headers=headers
    )
    assert resp.status_code == 422
    assert (await _channel(app_client, headers, sid))["logo_url"] is None


async def test_overrides_reach_the_export_playlist(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], upstream: dict[str, str | None]
) -> None:
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.models.tenant import Tenant
    from app.services import exports

    headers, sid = await _setup(app_client, captured_emails)
    cid = (await _channel(app_client, headers, sid))["id"]
    body = {"group_override": "Sports", "logo_override": "https://img.example.com/sfb.png"}
    assert (await app_client.patch(f"/api/channels/{cid}", json=body, headers=headers)).is_success

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(sid))
        assert source is not None
        tenant = await session.get(Tenant, source.tenant_id)
        assert tenant is not None
        m3u = await exports.render_m3u(session, tenant, base_url="https://tv.example", token="T")
    assert 'tvg-logo="https://img.example.com/sfb.png"' in m3u
    assert 'group-title="Sports"' in m3u


async def test_groups_lists_the_accounts_categories(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], upstream: dict[str, str | None]
) -> None:
    upstream["group"] = "news"
    headers, sid = await _setup(app_client, captured_emails)
    cid = (await _channel(app_client, headers, sid))["id"]
    assert (await app_client.get("/api/channels/groups", headers=headers)).json() == ["news"]

    await app_client.patch(
        f"/api/channels/{cid}", json={"group_override": "Sports"}, headers=headers
    )
    assert (await app_client.get("/api/channels/groups", headers=headers)).json() == ["Sports"]
