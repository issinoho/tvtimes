"""TVTIMES_STREAM_ORIGIN: export, stream, relay and pairing URLs follow the
host a request arrived on, choosing only between the two configured origins."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
import respx
from app.config import Settings, get_settings
from app.models.source import SourceKind
from app.services import relay
from httpx import AsyncClient, Response
from pydantic import ValidationError

from tests.test_devices import _auth, _start
from tests.test_relay import UPSTREAM, _seed

PUBLIC = "http://localhost:5173"  # conftest's TVTIMES_PUBLIC_ORIGIN
STREAM = "https://stream.example.com"
STREAM_HOST = {"host": "stream.example.com"}


@pytest.fixture(autouse=True)
def _stream_origin(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TVTIMES_STREAM_ORIGIN", STREAM + "/")
    monkeypatch.setenv("TVTIMES_RELAY_LAN_DIRECT", "false")  # the test client is 127.0.0.1
    get_settings.cache_clear()
    relay.registry.clear()
    yield
    relay.registry.clear()
    get_settings.cache_clear()


def test_origin_for_picks_only_a_configured_origin() -> None:
    s = get_settings()
    assert s.stream_origin == STREAM  # trailing slash dropped
    assert s.origin_for("stream.example.com") == STREAM
    assert s.origin_for("Stream.Example.COM") == STREAM
    assert s.origin_for("tvtimes.lan") == PUBLIC
    assert s.origin_for("evil.example.net") == PUBLIC
    assert s.origin_for(None) == PUBLIC


def test_origin_for_without_a_stream_origin_is_the_public_one() -> None:
    s = Settings(stream_origin="")
    assert s.origin_for("stream.example.com") == s.public_origin.rstrip("/")


@pytest.mark.parametrize(
    "bad", ["stream.example.com", "ftp://x.example.com", "https://x.example.com/tv"]
)
def test_stream_origin_must_be_a_bare_http_origin(bad: str) -> None:
    with pytest.raises(ValidationError):
        Settings(stream_origin=bad)


async def test_playlist_urls_follow_the_host_it_was_fetched_on(app_client: AsyncClient) -> None:
    token, cid, _ = await _seed(f"{UPSTREAM}/live/c.ts")
    params = {"token": token}

    outside = (
        await app_client.get("/api/exports/playlist.m3u", params=params, headers=STREAM_HOST)
    ).text
    assert f"{STREAM}/api/exports/stream/{cid}?token=" in outside
    assert f"{STREAM}/api/exports/epg.xml?token=" in outside
    assert PUBLIC not in outside

    inside = (await app_client.get("/api/exports/playlist.m3u", params=params)).text
    assert f"{PUBLIC}/api/exports/stream/{cid}?token=" in inside
    assert STREAM not in inside

    forged = (
        await app_client.get(
            "/api/exports/playlist.m3u", params=params, headers={"host": "evil.example.net"}
        )
    ).text
    assert "evil.example.net" not in forged and f"{PUBLIC}/api/exports/stream/" in forged


@respx.mock
async def test_relay_urls_stay_on_the_stream_host(app_client: AsyncClient) -> None:
    token, cid, _ = await _seed(f"{UPSTREAM}/hls/index.m3u8")
    respx.get(f"{UPSTREAM}/hls/index.m3u8").mock(
        return_value=Response(
            200,
            text="#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nseg1.ts\n",
            headers={"content-type": "application/vnd.apple.mpegurl"},
        )
    )
    first = await app_client.get(
        f"/api/exports/stream/{cid}", params={"token": token}, headers=STREAM_HOST
    )
    assert first.status_code == 302
    entry = first.headers["location"]
    assert entry.startswith(f"{STREAM}/api/exports/relay/passthrough/"), entry

    manifest = await app_client.get(urlparse(entry).path, headers=STREAM_HOST)
    assert manifest.status_code == 200
    segments = [line for line in manifest.text.splitlines() if line and not line.startswith("#")]
    assert segments and all(
        u.startswith(f"{STREAM}/api/exports/relay/passthrough/") for u in segments
    )

    # The same channel fetched on the LAN host stays on the LAN host.
    inside = await app_client.get(f"/api/exports/stream/{cid}", params={"token": token})
    assert inside.headers["location"].startswith(f"{PUBLIC}/api/exports/relay/")


async def test_pairing_hands_back_the_host_the_device_paired_through(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "away@example.com")
    for host, origin in ((STREAM_HOST, STREAM), ({}, PUBLIC)):
        started = await _start(app_client)
        approved = await app_client.post(
            "/api/devices", json={"code": started["code"]}, headers=headers
        )
        assert approved.status_code == 200
        polled = await app_client.post(
            "/api/pairing/poll", json={"poll_secret": started["poll_secret"]}, headers=host
        )
        assert polled.json()["origin"] == origin


def test_rewrite_uses_the_given_origin() -> None:
    target = relay.RelayTarget(uuid.uuid4(), uuid.uuid4(), SourceKind.m3u, f"{UPSTREAM}/a.m3u8")
    out = relay.rewrite_playlist(
        "#EXTM3U\n#EXTINF:6,\nseg.ts\n",
        base_url=f"{UPSTREAM}/a.m3u8",
        target=target,
        profile=relay.PROFILE_PASSTHROUGH,
        origin=STREAM,
    )
    assert re.search(
        rf"^{re.escape(STREAM)}/api/exports/relay/passthrough/[^/]+/seg\.ts$", out, re.M
    )
