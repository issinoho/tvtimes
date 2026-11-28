"""The stream relay: a relayed source's /stream is proxied, not 302'd."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any
from urllib.parse import urlparse

import anyio
import httpx
import pytest
import respx
import structlog
import structlog.testing
from app.auth import tokens
from app.auth.crypto import encrypt
from app.config import get_settings
from app.db import get_sessionmaker
from app.models.source import Channel, Source, SourceKind, SourceStatus
from app.models.tenant import Tenant
from app.services import exports as exports_svc
from app.services import relay
from httpx import AsyncClient, Response

UPSTREAM = "http://93.184.216.34"  # public IP literals: no DNS in the suite
CDN = "http://93.184.216.35"
TS_BODY = b"\x47" + bytes(range(256)) * 8  # 0x47: an MPEG-TS sync byte


@pytest.fixture(autouse=True)
def _relay_lan_clients(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # The test client connects from 127.0.0.1, which counts as LAN; relay it
    # anyway unless a test is about the LAN shortcut itself.
    monkeypatch.setenv("TVTIMES_RELAY_LAN_DIRECT", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_registry() -> Iterator[None]:
    relay.registry.clear()
    yield
    relay.registry.clear()


async def _seed(
    url: str,
    *,
    kind: SourceKind = SourceKind.m3u,
    relay_streams: bool = True,
) -> tuple[str, uuid.UUID, uuid.UUID]:
    """A tenant with an export token and one channel; returns (token, channel, tenant)."""
    async with get_sessionmaker()() as session:
        tenant = Tenant(name="T", default_timezone="UTC")
        session.add(tenant)
        await session.flush()
        token = await exports_svc.generate_token(session, tenant)
        source = Source(
            tenant_id=tenant.id,
            kind=kind,
            display_name="S",
            config_encrypted="x",
            last_status=SourceStatus.ok,
            relay_streams=relay_streams,
        )
        session.add(source)
        await session.flush()
        channel = Channel(
            tenant_id=tenant.id,
            source_id=source.id,
            dedupe_key="c",
            name="C",
            stream_ref_encrypted=encrypt(url),
        )
        session.add(channel)
        await session.commit()
        return token, channel.id, tenant.id


def _relay_path(url: str) -> str:
    assert url.startswith("http://localhost:5173/api/exports/relay/passthrough/"), url
    return urlparse(url).path


def _token_of(url: str) -> str:
    return _relay_path(url).split("/")[5]


def _relay_urls(playlist: str) -> list[str]:
    urls = re.findall(r'URI="([^"]+)"', playlist)
    urls += [line for line in playlist.splitlines() if line and not line.startswith("#")]
    return urls


async def _get_stream(client: AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
    """GET an export stream URL; when it redirects into the relay (a relayed
    source), follow that one hop, as a player would."""
    resp = await client.get(url, **kwargs)
    location = resp.headers.get("location", "")
    if resp.status_code == 302 and "/api/exports/relay/" in location:
        kwargs.pop("params", None)
        resp = await client.get(urlparse(location).path, **kwargs)
    return resp


# --- TS passthrough ---------------------------------------------------------


@respx.mock
async def test_ts_passthrough_streams_bytes_and_filters_headers(app_client: AsyncClient) -> None:
    token, cid, tid = await _seed(f"{UPSTREAM}/live/c.ts")
    respx.get(f"{UPSTREAM}/live/c.ts").mock(
        return_value=Response(
            200,
            content=TS_BODY,
            headers={
                "content-type": "video/mp2t",
                "set-cookie": "sid=provider-session",
                "server": "provider-panel/1.0",
                "x-provider-user": "user1",
            },
        )
    )
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 200
    assert resp.content == TS_BODY
    assert resp.headers["content-type"] == "video/mp2t"
    assert resp.headers["content-length"] == str(len(TS_BODY))
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-accel-buffering"] == "no"
    for leaked in ("set-cookie", "server", "x-provider-user"):
        assert leaked not in resp.headers
    sent = respx.calls.last.request
    assert sent.headers["accept-encoding"] == "identity"
    assert sent.headers["user-agent"].startswith("tvtimes/")
    # the TS slot lasted exactly as long as the connection
    assert relay.registry.live_count(tid) == 0


@respx.mock
async def test_range_is_forwarded_and_206_passed_back(app_client: AsyncClient) -> None:
    token, cid, _ = await _seed(f"{UPSTREAM}/vod/film.mp4")

    def upstream(request: httpx.Request) -> Response:
        assert request.headers["range"] == "bytes=0-99"
        assert request.headers["if-range"] == '"etag1"'
        return Response(
            206,
            content=TS_BODY[:100],
            headers={
                "content-type": "video/mp4",
                "content-range": f"bytes 0-99/{len(TS_BODY)}",
                "accept-ranges": "bytes",
            },
        )

    respx.get(f"{UPSTREAM}/vod/film.mp4").mock(side_effect=upstream)
    resp = await _get_stream(
        app_client,
        f"/api/exports/stream/{cid}",
        params={"token": token},
        headers={"Range": "bytes=0-99", "If-Range": '"etag1"', "Cookie": "a=b"},
    )
    assert resp.status_code == 206
    assert resp.content == TS_BODY[:100]
    assert resp.headers["content-range"] == f"bytes 0-99/{len(TS_BODY)}"
    assert resp.headers["accept-ranges"] == "bytes"
    assert "cookie" not in respx.calls.last.request.headers


async def test_toggle_off_still_redirects(app_client: AsyncClient) -> None:
    token, cid, _ = await _seed(f"{UPSTREAM}/live/c.ts", relay_streams=False)
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{UPSTREAM}/live/c.ts"


@respx.mock
@pytest.mark.parametrize(
    ("trusted", "xff", "relayed"),
    [
        ("", None, False),  # straight from a LAN (loopback) client: direct
        ("", "8.8.8.8", True),  # forwarded by an untrusted proxy: never LAN
        ("", "192.168.1.20", True),  # ...even when the header claims a LAN address
        ("127.0.0.1", "192.168.1.20", False),  # trusted proxy, LAN viewer: direct
        ("127.0.0.1", "8.8.8.8", True),  # trusted proxy, outside viewer: relayed
        ("127.0.0.1", "100.101.102.103", True),  # CGNAT / Tailscale isn't LAN
    ],
)
async def test_lan_viewers_get_the_direct_redirect(
    app_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    trusted: str,
    xff: str | None,
    relayed: bool,
) -> None:
    monkeypatch.setenv("TVTIMES_RELAY_LAN_DIRECT", "true")
    monkeypatch.setenv("TVTIMES_TRUSTED_PROXIES", trusted)
    get_settings.cache_clear()
    token, cid, _ = await _seed(f"{UPSTREAM}/live/c.ts")
    respx.get(f"{UPSTREAM}/live/c.ts").mock(
        return_value=Response(200, content=TS_BODY, headers={"content-type": "video/mp2t"})
    )
    headers = {"x-forwarded-for": xff} if xff else {}
    resp = await _get_stream(
        app_client, f"/api/exports/stream/{cid}", params={"token": token}, headers=headers
    )
    if relayed:
        assert resp.status_code == 200
        assert resp.content == TS_BODY
    else:
        assert resp.status_code == 302
        assert resp.headers["location"] == f"{UPSTREAM}/live/c.ts"


async def test_relay_disabled_globally_redirects(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TVTIMES_RELAY_ENABLED", "false")
    get_settings.cache_clear()
    token, cid, _ = await _seed(f"{UPSTREAM}/live/c.ts")
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{UPSTREAM}/live/c.ts"


@respx.mock
async def test_relay_logs_hostname_only(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, cid, _ = await _seed(f"{UPSTREAM}/live/user1/pass1/c.ts")
    respx.get(f"{UPSTREAM}/live/user1/pass1/c.ts").mock(
        return_value=Response(200, content=TS_BODY, headers={"content-type": "video/mp2t"})
    )
    saved = structlog.get_config()
    cap = structlog.testing.LogCapture()
    processors: list[Any] = [cap]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(0),
        cache_logger_on_first_use=False,
    )
    try:
        monkeypatch.setattr(relay, "_log", structlog.get_logger("services.relay"))
        resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    finally:
        structlog.configure(**saved)
    assert resp.status_code == 200
    logs = cap.entries
    events = [e for e in logs if e["event"] in {"relay.start", "relay.end"}]
    assert [e["event"] for e in events] == ["relay.start", "relay.end"]
    assert events[0]["host"] == "93.184.216.34"
    assert events[1]["bytes"] == len(TS_BODY) and events[1]["reason"] == "complete"
    assert "pass1" not in json.dumps(logs, default=str)


# --- HLS --------------------------------------------------------------------

MASTER = """#EXTM3U
#EXT-X-VERSION:6
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",URI="/audio/en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1280000,AUDIO="aud"
low/index.m3u8
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=86000,URI="http://93.184.216.36/iframes.m3u8"
"""

MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:100
#EXT-X-KEY:METHOD=AES-128,URI="keys/k1.bin",IV=0x1
#EXT-X-MAP:URI="init.mp4"
#EXTINF:6.0,
seg100.ts
#EXTINF:6.0,
/abs/seg101.ts?sig=abc
#EXTINF:6.0,
http://93.184.216.37/other/seg102.ts
"""


@respx.mock
async def test_hls_master_and_media_are_rewritten(app_client: AsyncClient) -> None:
    token, cid, tid = await _seed(f"{UPSTREAM}/hls/master.m3u8?u=user1&p=pass1")
    # The provider redirects to a CDN; relative URIs resolve against the CDN.
    respx.get(f"{UPSTREAM}/hls/master.m3u8").mock(
        return_value=Response(302, headers={"location": f"{CDN}/cdn/abc/master.m3u8"})
    )
    respx.get(f"{CDN}/cdn/abc/master.m3u8").mock(
        return_value=Response(
            200, text=MASTER, headers={"content-type": "application/vnd.apple.mpegurl"}
        )
    )
    respx.get(f"{CDN}/cdn/abc/low/index.m3u8").mock(
        # served as text/plain: detected by its #EXTM3U, not its content type
        return_value=Response(200, text=MEDIA, headers={"content-type": "text/plain"})
    )
    respx.get(f"{CDN}/cdn/abc/low/seg100.ts").mock(
        return_value=Response(200, content=TS_BODY, headers={"content-type": "video/mp2t"})
    )

    before = int(time.time())
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/vnd.apple.mpegurl"
    assert resp.headers["cache-control"] == "no-store"
    master = resp.text
    assert "93.184.216" not in master and "pass1" not in master
    urls = _relay_urls(master)
    assert len(urls) == 3
    targets = {
        relay.decode_token(_token_of(u), profile="passthrough").url: u.rsplit("/", 1)[-1]
        for u in urls
    }
    assert targets == {
        f"{CDN}/audio/en.m3u8": "en.m3u8",  # root-relative
        f"{CDN}/cdn/abc/low/index.m3u8": "index.m3u8",  # relative to the final URL
        "http://93.184.216.36/iframes.m3u8": "iframes.m3u8",  # absolute
    }
    # tags and attributes other than URI= survive
    assert '#EXT-X-STREAM-INF:BANDWIDTH=1280000,AUDIO="aud"' in master
    # an HLS session keeps its slot for a while after the playlist fetch
    assert relay.registry.live_count(tid) == 1

    low = next(u for u in urls if "index.m3u8" in u and "en.m3u8" not in u)
    media_resp = await app_client.get(_relay_path(low))
    assert media_resp.status_code == 200, media_resp.text
    media = media_resp.text
    assert "93.184.216" not in media
    assert "#EXT-X-MEDIA-SEQUENCE:100" in media and "IV=0x1" in media
    media_urls = _relay_urls(media)
    decoded = {
        relay.decode_token(_token_of(u), profile="passthrough").url: u.rsplit("/", 1)[-1]
        for u in media_urls
    }
    assert decoded == {
        f"{CDN}/cdn/abc/low/keys/k1.bin": "k1.bin",
        f"{CDN}/cdn/abc/low/init.mp4": "init.mp4",
        f"{CDN}/cdn/abc/low/seg100.ts": "seg100.ts",
        f"{CDN}/abs/seg101.ts?sig=abc": "seg101.ts",
        "http://93.184.216.37/other/seg102.ts": "seg102.ts",
    }
    # segment tokens are short-lived on a live playlist, playlist tokens long
    seg_exp = _exp_of(next(u for u in media_urls if u.endswith("seg100.ts")))
    playlist_exp = _exp_of(low)
    assert before + 590 <= seg_exp <= int(time.time()) + 600
    assert playlist_exp >= before + 43200 - 10

    seg = next(u for u in media_urls if u.endswith("seg100.ts"))
    seg_resp = await app_client.get(_relay_path(seg))
    assert seg_resp.status_code == 200
    assert seg_resp.content == TS_BODY
    assert seg_resp.headers["content-type"] == "video/mp2t"
    assert relay.registry.live_count(tid) == 1  # still the one session


def _exp_of(url: str) -> int:
    token = _token_of(url)
    raw = relay._fernet().decrypt(token + "=" * (-len(token) % 4))
    return int(json.loads(raw)["exp"])


@respx.mock
async def test_vod_playlist_tokens_all_live_long(app_client: AsyncClient) -> None:
    token, cid, _ = await _seed(f"{UPSTREAM}/vod/film.m3u8")
    respx.get(f"{UPSTREAM}/vod/film.m3u8").mock(
        return_value=Response(
            200,
            text="#EXTM3U\n#EXTINF:10,\nseg1.ts\n#EXT-X-ENDLIST\n",
            headers={"content-type": "application/x-mpegurl"},
        )
    )
    before = int(time.time())
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    [seg] = _relay_urls(resp.text)
    assert _exp_of(seg) >= before + 43200 - 10


@respx.mock
async def test_stream_redirects_to_a_relay_url_without_opening_the_upstream(
    app_client: AsyncClient,
) -> None:
    # /stream answers from the DB alone; the upstream is opened once, by the
    # player's fetch of the relay URL. Then a live playlist's re-polls land on
    # the relay route (token only, own limit), not /stream (DB + EXPORT_LIMIT).
    token, cid, _ = await _seed(f"{UPSTREAM}/live/chan.m3u8?u=user1&p=pass1")
    route = respx.get(f"{UPSTREAM}/live/chan.m3u8").mock(
        return_value=Response(
            200,
            text="#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nseg1.ts\n",
            headers={"content-type": "application/vnd.apple.mpegurl"},
        )
    )
    resp = await app_client.get(f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 302
    assert route.call_count == 0
    location = resp.headers["location"]
    assert location.endswith("/chan.m3u8")
    assert "user1" not in location and "pass1" not in location
    assert _exp_of(location) >= int(time.time()) + 43200 - 10

    for _ in range(2):  # the player polling its playlist
        polled = await app_client.get(urlparse(location).path)
        assert polled.status_code == 200
        [seg] = _relay_urls(polled.text)
        assert seg.endswith("/seg1.ts")
    assert route.call_count == 2


@pytest.mark.parametrize(
    ("kind", "url", "name"),
    [
        # An HDHomeRun only serves MPEG-TS and its URLs don't say so.
        (SourceKind.hdhomerun, "http://192.168.1.50:5004/auto/v7", "stream.ts"),
        # An Xtream-style URL keeps its file name, but not the login before it.
        (SourceKind.m3u, f"{UPSTREAM}/live/user1/pass1/123.ts", "123.ts"),
        (SourceKind.m3u, f"{UPSTREAM}/play", "play"),  # nothing to go on
    ],
)
async def test_relay_entry_url_carries_an_extension_where_known(
    app_client: AsyncClient, kind: SourceKind, url: str, name: str
) -> None:
    token, cid, _ = await _seed(url, kind=kind)
    resp = await app_client.get(f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.rsplit("/", 1)[-1] == name
    assert "user1" not in location and "pass1" not in location


@respx.mock
async def test_oversized_manifest_is_refused(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TVTIMES_RELAY_MANIFEST_MAX_BYTES", "64")
    get_settings.cache_clear()
    token, cid, _ = await _seed(f"{UPSTREAM}/big.m3u8")
    respx.get(f"{UPSTREAM}/big.m3u8").mock(
        return_value=Response(200, text="#EXTM3U\n" + "seg.ts\n" * 50)
    )
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 502


# --- relay tokens -----------------------------------------------------------


def _target() -> relay.RelayTarget:
    return relay.RelayTarget(uuid.uuid4(), uuid.uuid4(), SourceKind.m3u, f"{UPSTREAM}/s.ts")


def test_token_roundtrip_hides_the_url() -> None:
    target = _target()
    tok = relay.issue_token(target, profile="passthrough", ttl_seconds=60)
    assert "93.184" not in tok and "=" not in tok
    assert relay.decode_token(tok, profile="passthrough") == target


def test_token_rejects_tampering_expiry_and_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    tok = relay.issue_token(_target(), profile="passthrough", ttl_seconds=60)
    flipped = tok[:20] + ("A" if tok[20] != "A" else "B") + tok[21:]
    for bad in (flipped, "garbage", "", tok + "x"):
        with pytest.raises(relay.InvalidRelayToken):
            relay.decode_token(bad, profile="passthrough")
    with pytest.raises(relay.InvalidRelayToken):
        relay.decode_token(tok, profile="mobile")
    monkeypatch.setattr(relay, "_now", lambda: time.time() + 61)
    with pytest.raises(relay.InvalidRelayToken):
        relay.decode_token(tok, profile="passthrough")


def test_token_from_another_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    tok = relay.issue_token(_target(), profile="passthrough", ttl_seconds=60)
    monkeypatch.setenv("TVTIMES_ENCRYPTION_KEY", "some-other-key")
    get_settings.cache_clear()
    with pytest.raises(relay.InvalidRelayToken):
        relay.decode_token(tok, profile="passthrough")


async def test_segment_route_rejects_bad_tokens_and_profiles(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tok = relay.issue_token(_target(), profile="passthrough", ttl_seconds=60)
    resp = await app_client.get("/api/exports/relay/passthrough/garbage/s.ts")
    assert resp.status_code == 401
    resp = await app_client.get(f"/api/exports/relay/mobile/{tok}/s.ts")
    assert resp.status_code == 404
    monkeypatch.setattr(relay, "_now", lambda: time.time() + 3600)
    resp = await app_client.get(f"/api/exports/relay/passthrough/{tok}/s.ts")
    assert resp.status_code == 401


def test_relay_route_is_not_in_the_schema() -> None:
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    assert not any("/relay/" in p for p in paths)


# --- destination policy -----------------------------------------------------


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9981/stream/1", "http://169.254.169.254/latest/meta-data/"]
)
async def test_m3u_relay_to_non_public_is_rejected(app_client: AsyncClient, url: str) -> None:
    token, cid, tid = await _seed(url)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(url).mock(return_value=Response(200, content=TS_BODY))
        resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 502
    assert "127.0.0.1" not in resp.text and "169.254" not in resp.text
    assert not route.called
    assert relay.registry.live_count(tid) == 0


async def test_m3u_relay_redirect_into_the_lan_is_rejected(app_client: AsyncClient) -> None:
    token, cid, _ = await _seed(f"{UPSTREAM}/live/c.ts")
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{UPSTREAM}/live/c.ts").mock(
            return_value=Response(302, headers={"location": "http://169.254.169.254/latest/"})
        )
        metadata = mock.get("http://169.254.169.254/latest/").mock(return_value=Response(200))
        resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 502
    assert not metadata.called


@respx.mock
async def test_m3u_relay_to_lan_needs_the_allowlist(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    lan = "http://192.168.1.60:9981/stream/channel/1"
    respx.get(lan).mock(
        return_value=Response(200, content=TS_BODY, headers={"content-type": "video/mp2t"})
    )
    token, cid, _ = await _seed(lan)
    assert (
        await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    ).status_code == 502
    monkeypatch.setenv("TVTIMES_FETCH_ALLOWLIST", "192.168.1.0/24")
    get_settings.cache_clear()
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 200
    assert resp.content == TS_BODY


@respx.mock
async def test_hdhomerun_relays_lan_without_allowlist(app_client: AsyncClient) -> None:
    url = "http://192.168.1.50:5004/auto/v7.1"
    respx.get(url).mock(
        return_value=Response(200, content=TS_BODY, headers={"content-type": "video/mpeg"})
    )
    token, cid, _ = await _seed(url, kind=SourceKind.hdhomerun)
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 200
    assert resp.content == TS_BODY


async def test_hdhomerun_relay_to_public_is_rejected(app_client: AsyncClient) -> None:
    token, cid, _ = await _seed(f"{UPSTREAM}/auto/v7.1", kind=SourceKind.hdhomerun)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{UPSTREAM}/auto/v7.1").mock(return_value=Response(200, content=TS_BODY))
        resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 502
    assert not route.called


async def test_hdhomerun_redirect_off_the_lan_is_rejected(app_client: AsyncClient) -> None:
    url = "http://192.168.1.50:5004/auto/v7.1"
    token, cid, _ = await _seed(url, kind=SourceKind.hdhomerun)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url).mock(return_value=Response(302, headers={"location": f"{UPSTREAM}/x.ts"}))
        public = mock.get(f"{UPSTREAM}/x.ts").mock(return_value=Response(200, content=TS_BODY))
        resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 502
    assert not public.called


# --- upstream failures ------------------------------------------------------


@respx.mock
async def test_upstream_failures_are_mapped(app_client: AsyncClient) -> None:
    token, cid, tid = await _seed(f"{UPSTREAM}/live/c.ts")
    route = respx.get(f"{UPSTREAM}/live/c.ts")
    params = {"token": token}

    route.mock(return_value=Response(503, text="All tuners busy at 10.0.0.9"))
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params=params)
    assert resp.status_code == 503 and "retry-after" in resp.headers
    assert "10.0.0.9" not in resp.text

    route.mock(side_effect=httpx.ConnectTimeout("slow"))
    assert (
        await _get_stream(app_client, f"/api/exports/stream/{cid}", params=params)
    ).status_code == 504

    route.mock(side_effect=httpx.ConnectError("refused"))
    assert (
        await _get_stream(app_client, f"/api/exports/stream/{cid}", params=params)
    ).status_code == 502

    route.mock(return_value=Response(404, text="no such stream"))
    assert (
        await _get_stream(app_client, f"/api/exports/stream/{cid}", params=params)
    ).status_code == 502

    route.mock(
        return_value=Response(200, text="<html>login</html>", headers={"content-type": "text/html"})
    )
    assert (
        await _get_stream(app_client, f"/api/exports/stream/{cid}", params=params)
    ).status_code == 502

    assert relay.registry.live_count(tid) == 0


# --- concurrency ------------------------------------------------------------


@respx.mock
async def test_over_the_cap_is_503_then_released(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TVTIMES_RELAY_MAX_STREAMS_PER_TENANT", "1")
    get_settings.cache_clear()
    token, cid, tid = await _seed(f"{UPSTREAM}/live/c.ts")
    respx.get(f"{UPSTREAM}/live/c.ts").mock(
        return_value=Response(200, content=TS_BODY, headers={"content-type": "video/mp2t"})
    )
    # another client on this account already watching another channel
    other = await relay.registry.acquire((tid, uuid.uuid4(), "10.9.9.9"), per_tenant=1, total=16)
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "5"

    await other.release(sticky=False)
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 200
    assert relay.registry.live_count(tid) == 0


async def test_registry_shares_a_key_and_expires_idle_hls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(relay, "_monotonic", lambda: clock[0])
    reg = relay.StreamRegistry()
    tid, cid = uuid.uuid4(), uuid.uuid4()
    key = (tid, cid, "1.2.3.4")

    first = await reg.acquire(key, per_tenant=1, total=1)
    # the same player reconnecting shares its slot instead of being locked out
    again = await reg.acquire(key, per_tenant=1, total=1)
    with pytest.raises(relay.RelayBusy):
        await reg.acquire((tid, uuid.uuid4(), "1.2.3.4"), per_tenant=1, total=1)
    await first.release(sticky=False)
    await first.release(sticky=False)  # idempotent
    assert reg.live_count(tid) == 1
    await again.release(sticky=False)
    assert reg.live_count(tid) == 0

    # HLS: no open connection, but the session holds its slot until idle 30 s
    lease = await reg.acquire(key, per_tenant=1, total=1)
    await lease.release(sticky=True)
    clock[0] += 29
    with pytest.raises(relay.RelayBusy):
        await reg.acquire((uuid.uuid4(), cid, "x"), per_tenant=1, total=1)
    clock[0] += 2
    other = await reg.acquire((uuid.uuid4(), cid, "x"), per_tenant=1, total=1)
    await other.release(sticky=False)


# --- disconnect -------------------------------------------------------------


class _EndlessStream(httpx.AsyncByteStream):
    """A live upstream: one chunk, then nothing, forever -- until closed."""

    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield TS_BODY
        await anyio.sleep_forever()
        yield b""  # pragma: no cover

    async def aclose(self) -> None:
        self.closed = True


async def test_client_disconnect_closes_the_upstream() -> None:
    stream = _EndlessStream()
    upstream = httpx.Response(200, stream=stream, headers={"content-type": "video/mp2t"})
    closed: list[tuple[int, str]] = []

    async def on_close(sent: int, reason: str) -> None:
        closed.append((sent, reason))

    chunks = upstream.aiter_raw()
    first = await anext(chunks)
    response = relay.RelayResponse(
        upstream=upstream,
        chunks=chunks,
        first=first,
        status_code=200,
        headers={"Content-Type": "video/mp2t"},
        on_close=on_close,
    )
    got_body = anyio.Event()
    messages: list[dict[str, Any]] = []

    async def send(message: Any) -> None:
        messages.append(message)
        if message["type"] == "http.response.body":
            got_body.set()

    async def receive() -> Any:
        await got_body.wait()
        return {"type": "http.disconnect"}

    with anyio.fail_after(5):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)

    assert stream.closed
    assert closed == [(len(TS_BODY), "client_disconnect")]
    start = messages[0]
    assert start["status"] == 200
    assert (b"content-length", b"0") not in start["headers"]


# --- stalker / play ticket --------------------------------------------------


async def test_stalker_is_still_501_on_both_routes(app_client: AsyncClient) -> None:
    token, cid, tid = await _seed("ffff0000", kind=SourceKind.stalker)
    resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
    assert resp.status_code == 501
    ticket = tokens.issue_play_token(cid, tid)
    resp = await _get_stream(
        app_client, f"/api/exports/play/{cid}/stream", params={"ticket": ticket}
    )
    assert resp.status_code == 501


@respx.mock
async def test_play_ticket_route_relays(app_client: AsyncClient) -> None:
    _token, cid, tid = await _seed(f"{UPSTREAM}/live/c.ts")
    respx.get(f"{UPSTREAM}/live/c.ts").mock(
        return_value=Response(200, content=TS_BODY, headers={"content-type": "video/mp2t"})
    )
    ticket = tokens.issue_play_token(cid, tid)
    resp = await _get_stream(
        app_client, f"/api/exports/play/{cid}/stream", params={"ticket": ticket}
    )
    assert resp.status_code == 200
    assert resp.content == TS_BODY
    resp = await _get_stream(
        app_client, f"/api/exports/play/{cid}/stream", params={"ticket": "junk"}
    )
    assert resp.status_code == 401


# --- single quality ---------------------------------------------------------

PLUTO_MASTER = """#EXTM3U
#EXT-X-VERSION:5
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",DEFAULT=NO,URI="subs/en.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English [Original]",DEFAULT=YES,URI="a/orig.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English",DEFAULT=NO,URI="a/en.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="other",NAME="Unused",URI="a/unused.m3u8"
#EXT-X-MEDIA:TYPE=CLOSED-CAPTIONS,GROUP-ID="cc",NAME="CC1",INSTREAM-ID="CC1"
#EXT-X-STREAM-INF:BANDWIDTH=1042180,CODECS="avc1.4d401e,mp4a.40.2",SUBTITLES="subs",AUDIO="audio"
v/1000.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3321280,SUBTITLES="subs",AUDIO="audio",CLOSED-CAPTIONS="cc"
v/3300.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=6500000,SUBTITLES="subs",AUDIO="audio"
v/6500.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=640930,SUBTITLES="subs",AUDIO="audio"
v/640.m3u8
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=86000,URI="iframes.m3u8"
"""


def test_single_variant_keeps_the_best_quality_under_the_cap() -> None:
    out = relay.keep_single_variant(PLUTO_MASTER, 4_000_000)
    uris = [line for line in out.splitlines() if line and not line.startswith("#")]
    assert uris == ["v/3300.m3u8"]
    assert "BANDWIDTH=3321280" in out
    # One rendition per group the variant uses: the default audio, the subs.
    assert 'URI="a/orig.m3u8"' in out and 'URI="subs/en.m3u8"' in out
    assert "a/en.m3u8" not in out and "unused" not in out and "iframes" not in out
    # No request behind it, so closed captions stay.
    assert 'CLOSED-CAPTIONS,GROUP-ID="cc"' in out


def test_single_variant_falls_back_to_the_lowest_and_leaves_simple_playlists() -> None:
    out = relay.keep_single_variant(PLUTO_MASTER, 500_000)
    assert [ln for ln in out.splitlines() if ln and not ln.startswith("#")] == ["v/640.m3u8"]
    one = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nonly.m3u8\n"
    assert relay.keep_single_variant(one, 4_000_000) == one


@respx.mock
async def test_relayed_master_is_trimmed_only_when_the_source_asks(
    app_client: AsyncClient,
) -> None:
    token, cid, _ = await _seed(f"{UPSTREAM}/hls/master.m3u8")
    respx.get(f"{UPSTREAM}/hls/master.m3u8").mock(
        return_value=Response(
            200, text=PLUTO_MASTER, headers={"content-type": "application/vnd.apple.mpegurl"}
        )
    )

    async def variants() -> int:
        resp = await _get_stream(app_client, f"/api/exports/stream/{cid}", params={"token": token})
        assert resp.status_code == 200
        return resp.text.count("#EXT-X-STREAM-INF")

    assert await variants() == 4
    async with get_sessionmaker()() as session:
        channel = await session.get(Channel, cid)
        assert channel is not None
        source = await session.get(Source, channel.source_id)
        assert source is not None
        source.relay_single_variant = True
        await session.commit()
    relay.registry.clear()
    assert await variants() == 1


def test_single_variant_rides_along_in_nested_tokens() -> None:
    target = relay.RelayTarget(
        uuid.uuid4(), uuid.uuid4(), SourceKind.m3u, f"{UPSTREAM}/m.m3u8", single_variant=True
    )
    url = relay.relay_url_for(
        target,
        f"{UPSTREAM}/v/1.m3u8",
        profile="passthrough",
        ttl_seconds=60,
        name="1.m3u8",
        nested=True,
        origin="http://localhost:5173",
    )
    assert relay.decode_token(_token_of(url), profile="passthrough").single_variant is True
