from __future__ import annotations

import uuid

import pytest
import respx
from app.ingest.models import Channel as ParsedChannel
from app.ingest.models import Playlist
from app.services import logos
from httpx import AsyncClient, Response

from tests.conftest import auth_header, login, register_and_verify

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


@pytest.fixture(autouse=True)
def _logo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    logos._cache.clear()
    # the sample logo lives on a LAN host — permit it, like a real deployment
    monkeypatch.setenv("TVTIMES_FETCH_ALLOWLIST", "192.168.0.0/24")
    from app.config import get_settings

    get_settings.cache_clear()


async def _channel_with_logo(
    app_client: AsyncClient,
    emails: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    logo_url: str = "http://192.168.0.218:5523/logos/x.png",
) -> str:
    await register_and_verify(app_client, emails)
    headers = auth_header(await login(app_client))

    async def fake_ingest(_kind: object, _config: object) -> Playlist:
        return Playlist(
            channels=[ParsedChannel(name="Pluto", stream_ref="http://s/1", tvg_logo=logo_url)]
        )

    monkeypatch.setattr("app.services.sources._ingest", fake_ingest)
    src = (
        await app_client.post(
            "/api/sources",
            json={"kind": "m3u", "display_name": "P", "url": "http://feed/x.m3u"},
            headers=headers,
        )
    ).json()["id"]

    from app.db import get_sessionmaker
    from app.models.source import Channel, Source
    from app.services import sources as svc
    from sqlalchemy import select

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(src))
        assert source is not None
        await svc.refresh_source(session, source)
        await session.commit()
        cid = await session.scalar(select(Channel.id).where(Channel.source_id == source.id))
    return str(cid)


@respx.mock
async def test_logo_is_proxied_with_cache_headers(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    respx.get("http://192.168.0.218:5523/logos/x.png").mock(
        return_value=Response(200, content=_PNG, headers={"content-type": "image/png"})
    )
    channel_id = await _channel_with_logo(app_client, captured_emails, monkeypatch)

    # No auth header — <img> can't send one.
    r = await app_client.get(f"/api/channels/{channel_id}/logo")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert "max-age=86400" in r.headers.get("cache-control", "")
    assert r.content == _PNG


@respx.mock
async def test_logo_404_when_upstream_fails(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    respx.get("http://192.168.0.218:5523/logos/x.png").mock(return_value=Response(503))
    channel_id = await _channel_with_logo(app_client, captured_emails, monkeypatch)
    r = await app_client.get(f"/api/channels/{channel_id}/logo")
    assert r.status_code == 404


async def test_logo_404_when_channel_has_none(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    channel_id = await _channel_with_logo(app_client, captured_emails, monkeypatch, logo_url="")
    r = await app_client.get(f"/api/channels/{channel_id}/logo")
    assert r.status_code == 404


async def test_logo_404_for_unknown_channel(app_client: AsyncClient) -> None:
    r = await app_client.get(f"/api/channels/{uuid.uuid4()}/logo")
    assert r.status_code == 404


@respx.mock
async def test_svg_logo_is_rejected_not_served_from_our_origin(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A script-bearing SVG served as image/svg+xml from our origin would be
    # stored XSS — the proxy must not accept it.
    respx.get("http://192.168.0.218:5523/logos/x.png").mock(
        return_value=Response(
            200,
            content=b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            headers={"content-type": "image/svg+xml"},
        )
    )
    channel_id = await _channel_with_logo(app_client, captured_emails, monkeypatch)
    r = await app_client.get(f"/api/channels/{channel_id}/logo")
    assert r.status_code == 404


def test_sniff_never_returns_svg() -> None:
    assert logos._sniff(b'<?xml version="1.0"?><svg onload="alert(1)"/>') is None
    assert logos._sniff(b"<svg/>") is None
    assert logos._sniff(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40) == "image/png"
