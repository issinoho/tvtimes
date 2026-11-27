"""Stream relay: proxy a channel's upstream stream through tvtimes.

The export ``/stream`` routes normally 302 to the upstream URL. For a source with
``relay_streams`` set they instead come here, and tvtimes fetches the stream and
passes it through byte for byte. That lets a client outside the LAN play a tuner
only tvtimes can reach (an HDHomeRun, a LAN tvheadend), and keeps provider
credentials -- an Xtream login is in the URL path -- off the client entirely.

* **Destination policy, by source kind.** An HDHomeRun must be a private LAN
  address (``hdhomerun.assert_lan_url``); everything else goes through the SSRF
  guard (``ssrf.resolve_allowed`` + ``TVTIMES_FETCH_ALLOWLIST``), so a remote
  playlist can't make tvtimes stream the LAN back out. Checked on every redirect
  hop, and the connection is pinned to the address that was checked. Each policy
  gets its own client, so a pooled connection is never reused across them.
* **HLS** is rewritten: every URI in a playlist becomes a relay URL carrying an
  opaque Fernet token (the upstream URL is *encrypted* in it, not just signed),
  served by ``/api/exports/relay/{profile}/{token}/{name}`` with no DB lookup.
* **Concurrency** is capped in memory (:class:`StreamRegistry`) -- one uvicorn
  process. A TS stream holds a slot for its connection's lifetime; an HLS
  session holds one while it keeps fetching, and 30 s after.
* **Disconnects** are handled in :class:`RelayResponse` itself, not by an async
  generator that only GC would finalise: the upstream (and so the tuner) is
  released the moment the client goes away.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import json
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote, urljoin, urlsplit

import anyio
import httpx
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import Receive, Scope, Send

from app.auth.ratelimit import client_ip
from app.config import get_settings
from app.ingest import hdhomerun, ssrf
from app.ingest.errors import SourceError
from app.logging import get_logger
from app.models.source import Channel, Source, SourceKind
from app.services import exports as exports_svc

_log = get_logger("services.relay")

PROFILE_PASSTHROUGH = "passthrough"
# The URL scheme reserves a path segment for a transcode profile; v1 has one.
PROFILES = frozenset({PROFILE_PASSTHROUGH})

_TOKEN_VERSION = 1
_HKDF_INFO = b"tvtimes-relay-v1"
_MAX_REDIRECTS = 5
_CHUNK = 65536
_HLS_IDLE_SECONDS = 30.0
_RETRY_AFTER = "5"

_MPEGURL_TYPES = frozenset(
    {
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "application/mpegurl",
        "audio/mpegurl",
        "audio/x-mpegurl",
    }
)
_MEDIA_TYPES = _MPEGURL_TYPES | {"application/octet-stream", "binary/octet-stream"}
_MEDIA_PREFIXES = ("video/", "audio/")
_HLS_MEDIA_TYPE = "application/vnd.apple.mpegurl"

_NO_STORE = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


# --- target -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RelayTarget:
    """One upstream URL to relay, and whose it is. ``kind`` picks the
    destination policy, so it travels with every token minted from it."""

    tenant_id: uuid.UUID
    channel_id: uuid.UUID
    kind: SourceKind
    url: str
    # Minted while rewriting an HLS playlist (a nested playlist, segment, key):
    # part of an HLS session, so its slot outlives the fetch, and it logs at
    # debug. False for the entry link /stream hands out.
    nested: bool = False


def resolve_target(channel: Channel, source: Source | None) -> RelayTarget:
    """Wraps ``exports.resolve_stream``; a Stalker channel still raises
    :class:`~app.services.exports.StreamUnavailable`."""
    url = exports_svc.resolve_stream(channel, source)
    kind = source.kind if source is not None else SourceKind.m3u
    return RelayTarget(channel.tenant_id, channel.id, kind, url)


# --- tokens -----------------------------------------------------------------


class InvalidRelayToken(Exception):
    """Tampered with, expired, or minted for another profile."""


@functools.lru_cache(maxsize=4)
def _fernet_for(raw_key: str) -> Fernet:
    # Its own key, derived from the app key, so a relay token can never be
    # mistaken for (or decrypt as) an at-rest secret and vice versa.
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(
        raw_key.encode("utf-8")
    )
    return Fernet(base64.urlsafe_b64encode(derived))


def _fernet() -> Fernet:
    return _fernet_for(get_settings().encryption_key)


def _now() -> float:
    """Wall clock for token expiry (a seam for tests)."""
    return time.time()


def issue_token(target: RelayTarget, *, profile: str, ttl_seconds: int) -> str:
    payload = {
        "v": _TOKEN_VERSION,
        "tid": str(target.tenant_id),
        "cid": str(target.channel_id),
        "k": target.kind.value,
        "u": target.url,
        "p": profile,
        "n": target.nested,
        "exp": int(_now()) + ttl_seconds,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    # Fernet tokens are urlsafe base64; the padding is dropped to keep the
    # path segment free of '='.
    return _fernet().encrypt(raw).decode("ascii").rstrip("=")


def decode_token(token: str, *, profile: str) -> RelayTarget:
    try:
        raw = _fernet().decrypt(token + "=" * (-len(token) % 4))
        data = json.loads(raw)
        if data["v"] != _TOKEN_VERSION or data["p"] != profile:
            raise InvalidRelayToken
        if not isinstance(data["exp"], int) or data["exp"] <= _now():
            raise InvalidRelayToken
        return RelayTarget(
            uuid.UUID(data["tid"]),
            uuid.UUID(data["cid"]),
            SourceKind(data["k"]),
            str(data["u"]),
            nested=bool(data.get("n", False)),
        )
    except (InvalidToken, ValueError, KeyError, TypeError) as exc:
        raise InvalidRelayToken from exc


# --- concurrency ------------------------------------------------------------

SessionKey = tuple[uuid.UUID, uuid.UUID, str]


class RelayBusy(Exception):
    """Over the per-tenant or global stream cap."""


@dataclass(slots=True)
class _Entry:
    active: int = 0
    sticky: bool = False  # an HLS session: stays live while idle < 30 s
    last_seen: float = 0.0


def _monotonic() -> float:
    return time.monotonic()


class StreamRegistry:
    """In-memory stream slots, keyed ``(tenant, channel, client_ip)``.

    A key already live shares its slot -- a player reconnecting, or an HLS
    session fetching its next segment, is never locked out by itself. A TS
    stream's slot is freed when its last connection closes; an HLS session's
    when it has fetched nothing for ``idle_seconds``."""

    def __init__(self, idle_seconds: float = _HLS_IDLE_SECONDS) -> None:
        self._idle = idle_seconds
        self._entries: dict[SessionKey, _Entry] = {}
        self._lock = asyncio.Lock()

    def _live(self, entry: _Entry, now: float) -> bool:
        return entry.active > 0 or (entry.sticky and now - entry.last_seen < self._idle)

    def _purge(self, now: float) -> None:
        for key in [k for k, e in self._entries.items() if not self._live(e, now)]:
            del self._entries[key]

    async def acquire(self, key: SessionKey, *, per_tenant: int, total: int) -> Lease:
        async with self._lock:
            now = _monotonic()
            self._purge(now)
            entry = self._entries.get(key)
            if entry is None:
                tenant_live = sum(1 for k in self._entries if k[0] == key[0])
                if tenant_live >= per_tenant or len(self._entries) >= total:
                    raise RelayBusy
                entry = self._entries[key] = _Entry()
            entry.active += 1
            entry.last_seen = now
        return Lease(self, key)

    async def _release(self, key: SessionKey, *, sticky: bool) -> None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.active = max(0, entry.active - 1)
            entry.last_seen = _monotonic()
            entry.sticky = entry.sticky or sticky
            if entry.active == 0 and not entry.sticky:
                del self._entries[key]

    def live_count(self, tenant_id: uuid.UUID | None = None) -> int:
        now = _monotonic()
        return sum(
            1
            for k, e in self._entries.items()
            if self._live(e, now) and (tenant_id is None or k[0] == tenant_id)
        )

    def clear(self) -> None:
        self._entries.clear()


class Lease:
    """One connection's hold on a slot; releasing twice is a no-op."""

    def __init__(self, registry: StreamRegistry, key: SessionKey) -> None:
        self._registry = registry
        self._key = key
        self._released = False

    async def release(self, *, sticky: bool) -> None:
        if self._released:
            return
        self._released = True
        await self._registry._release(self._key, sticky=sticky)


registry = StreamRegistry()


# --- upstream client & destination policy ------------------------------------

_Policy = Literal["lan", "public"]
_clients: dict[_Policy, httpx.AsyncClient] = {}


class RelayError(Exception):
    """A relay that can't go ahead; ``status`` is what the client gets."""

    def __init__(self, status: int, reason: str, *, retry_after: str | None = None) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.retry_after = retry_after


def _policy_for(kind: SourceKind) -> _Policy:
    # Connector sources are tuners on another network; they're treated like a
    # playlist URL (public-or-allow-listed), which in practice means they can't
    # be relayed -- the server can't reach them, which is why they're connectors.
    return "lan" if kind is SourceKind.hdhomerun else "public"


async def _check_destination(policy: _Policy, url: str) -> str | None:
    """Enforce the kind's policy on ``url``; return the address to pin to."""
    if policy == "lan":
        return (await hdhomerun.assert_lan_url(url))[0]
    pins = await ssrf.resolve_allowed(url, allowlist=get_settings().fetch_allowlist_entries)
    return pins[0] if pins else None


def _client(policy: _Policy) -> httpx.AsyncClient:
    client = _clients.get(policy)
    if client is None or client.is_closed:
        settings = get_settings()
        client = httpx.AsyncClient(
            transport=ssrf.pinning_transport(),
            follow_redirects=False,
            # read= is the idle timeout between chunks, not a cap on the stream.
            timeout=httpx.Timeout(
                settings.relay_read_timeout_seconds,
                connect=settings.relay_connect_timeout_seconds,
            ),
            headers={"User-Agent": settings.relay_user_agent or ssrf.USER_AGENT},
        )
        _clients[policy] = client
    return client


async def aclose() -> None:
    """Close the upstream clients (``main.lifespan`` shutdown)."""
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        await client.aclose()


async def _open_upstream(
    target: RelayTarget, request_headers: Mapping[str, str]
) -> tuple[httpx.Response, str]:
    """GET the target, following redirects by hand with the policy re-checked on
    every hop. Returns the (streaming) response and the final URL."""
    policy = _policy_for(target.kind)
    client = _client(policy)
    headers = {"Accept-Encoding": "identity"}
    for name in ("range", "if-range"):
        value = request_headers.get(name)
        if value:
            headers[name] = value
    url = target.url
    for _ in range(_MAX_REDIRECTS + 1):
        try:
            pin = await _check_destination(policy, url)
        except SourceError as exc:
            raise RelayError(502, "policy_rejected") from exc
        try:
            request = client.build_request("GET", url, headers=headers)
            with ssrf.pin_connections_to(pin):
                response = await client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise RelayError(504, "upstream_timeout") from exc
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise RelayError(502, "upstream_error") from exc
        if response.is_redirect:
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                raise RelayError(502, "bad_redirect")
            url = urljoin(url, location)
            continue
        return response, url
    raise RelayError(502, "too_many_redirects")


# --- HLS rewrite ------------------------------------------------------------

_URI_ATTR_RE = re.compile(r'URI="([^"]*)"')
# Tags whose URI= is a playlist rather than a segment / key / init section.
_PLAYLIST_URI_TAGS = ("#EXT-X-MEDIA:", "#EXT-X-I-FRAME-STREAM-INF:", "#EXT-X-RENDITION-REPORT:")
_SEGMENT_URI_TAGS = (
    "#EXT-X-KEY:",
    "#EXT-X-SESSION-KEY:",
    "#EXT-X-MAP:",
    "#EXT-X-PART:",
    "#EXT-X-PRELOAD-HINT:",
)
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _relay_name(url: str, default: str) -> str:
    """The upstream file name (players pick a demuxer by extension), made safe
    for a path segment."""
    base = unquote(urlsplit(url).path).rsplit("/", 1)[-1]
    name = _SAFE_NAME_RE.sub("", base)[:128].lstrip(".")
    return name or default


def _sub_uri(
    relay_url: Callable[..., str], match: re.Match[str], *, playlist: bool, default: str
) -> str:
    return f'URI="{relay_url(match.group(1), playlist=playlist, default=default)}"'


def relay_url_for(
    target: RelayTarget,
    absolute: str,
    *,
    profile: str,
    ttl_seconds: int,
    name: str,
    nested: bool,
) -> str:
    """The public relay URL for one upstream URL of ``target``'s channel."""
    origin = get_settings().public_origin.rstrip("/")
    token = issue_token(
        RelayTarget(target.tenant_id, target.channel_id, target.kind, absolute, nested=nested),
        profile=profile,
        ttl_seconds=ttl_seconds,
    )
    return f"{origin}/api/exports/relay/{profile}/{token}/{name}"


def entry_url(target: RelayTarget, *, profile: str = PROFILE_PASSTHROUGH) -> str:
    """Where ``/stream`` sends a player for a relayed channel: a relay URL whose
    last segment carries a file extension where one can be known. Players
    (ExoPlayer, through radiotimes' StreamResolver) pick HLS vs progressive
    from the URL, so with an extension they never have to open the stream just
    to see what it is -- which would tune an HDHomeRun twice, or spend a
    one-connection IPTV account's only slot."""
    # An HDHomeRun only ever serves MPEG-TS, and its URLs (/auto/v7) say nothing.
    name = "stream.ts" if target.kind is SourceKind.hdhomerun else _relay_name(target.url, "stream")
    return relay_url_for(
        target,
        target.url,
        profile=profile,
        ttl_seconds=get_settings().relay_playlist_ttl_seconds,
        name=name,
        nested=False,
    )


def rewrite_playlist(text: str, *, base_url: str, target: RelayTarget, profile: str) -> str:
    """Point every URI in an HLS playlist back at the relay. URIs resolve
    against ``base_url`` -- the *final* upstream URL, after redirects."""
    settings = get_settings()
    is_master = "#EXT-X-STREAM-INF" in text
    is_vod = "#EXT-X-ENDLIST" in text

    def relay_url(uri: str, *, playlist: bool, default: str) -> str:
        absolute = urljoin(base_url, uri.strip())
        if urlsplit(absolute).scheme not in ("http", "https"):
            return uri  # data:, skd:// (FairPlay) ... nothing to fetch
        ttl = (
            settings.relay_playlist_ttl_seconds
            if playlist or is_vod
            else settings.relay_segment_ttl_seconds
        )
        return relay_url_for(
            target,
            absolute,
            profile=profile,
            ttl_seconds=ttl,
            name=_relay_name(absolute, default),
            nested=True,
        )

    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append("")
        elif stripped.startswith("#"):
            if stripped.startswith(_PLAYLIST_URI_TAGS):
                playlist, default = True, "index.m3u8"
            elif stripped.startswith(_SEGMENT_URI_TAGS):
                playlist = False
                default = "init.mp4" if stripped.startswith("#EXT-X-MAP:") else "key"
            else:
                out.append(stripped)
                continue
            out.append(
                _URI_ATTR_RE.sub(
                    functools.partial(_sub_uri, relay_url, playlist=playlist, default=default),
                    stripped,
                )
            )
        else:
            out.append(
                relay_url(
                    stripped,
                    playlist=is_master,
                    default="index.m3u8" if is_master else "stream.ts",
                )
            )
    return "\n".join(out) + "\n"


# --- response ---------------------------------------------------------------


async def _aclose_iter(it: AsyncIterator[bytes]) -> None:
    close = getattr(it, "aclose", None)
    if close is not None:
        await close()


async def _close(upstream: httpx.Response | None, chunks: AsyncIterator[bytes] | None) -> None:
    if chunks is not None:
        await _aclose_iter(chunks)
    if upstream is not None:
        await upstream.aclose()


class RelayResponse(Response):
    """Streams an upstream body to the client and, whatever happens -- end of
    stream, upstream error, client disconnect, server shutdown -- closes the
    upstream and calls ``on_close`` in a ``finally``.

    A plain ``StreamingResponse`` over an async generator would leave the
    generator (and the HDHomeRun tuner behind it) to be finalised by GC."""

    def __init__(
        self,
        *,
        upstream: httpx.Response,
        chunks: AsyncIterator[bytes],
        first: bytes,
        status_code: int,
        headers: Mapping[str, str],
        on_close: Callable[[int, str], Awaitable[None]],
    ) -> None:
        # Deliberately not Response.__init__: that would set Content-Length: 0
        # for a body it doesn't have. Same shape as StreamingResponse.
        self.status_code = status_code
        self.background = None
        self.init_headers(headers)
        self._upstream = upstream
        self._chunks = chunks
        self._first = first
        self._on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        sent = 0
        reason = "complete"
        finished = False
        try:
            async with anyio.create_task_group() as tg:

                async def pump() -> None:
                    nonlocal sent, reason, finished
                    try:
                        await send(
                            {
                                "type": "http.response.start",
                                "status": self.status_code,
                                "headers": self.raw_headers,
                            }
                        )
                        if self._first:
                            await send(
                                {
                                    "type": "http.response.body",
                                    "body": self._first,
                                    "more_body": True,
                                }
                            )
                            sent += len(self._first)
                        async for chunk in self._chunks:
                            await send(
                                {"type": "http.response.body", "body": chunk, "more_body": True}
                            )
                            sent += len(chunk)
                        finished = True  # a disconnect from here on is just the close
                        await send({"type": "http.response.body", "body": b"", "more_body": False})
                    except httpx.TimeoutException:
                        reason = "upstream_timeout"
                    except httpx.HTTPError:
                        reason = "upstream_error"
                    except OSError:  # the server's send() after the client went away
                        reason = "client_disconnect"
                    tg.cancel_scope.cancel()

                async def watch_disconnect() -> None:
                    nonlocal reason
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            if not finished:
                                reason = "client_disconnect"
                            break
                    tg.cancel_scope.cancel()

                tg.start_soon(pump)
                tg.start_soon(watch_disconnect)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await _aclose_iter(self._chunks)
                    await self._upstream.aclose()
                finally:
                    await self._on_close(sent, reason)


def _error_response(exc: RelayError) -> Response:
    headers = dict(_NO_STORE)
    if exc.status == 503:
        headers["Retry-After"] = exc.retry_after or _RETRY_AFTER
        body = "No stream available right now; try again shortly."
    elif exc.status == 504:
        body = "The upstream stream timed out."
    else:
        body = "The upstream stream is unavailable."
    return PlainTextResponse(body, status_code=exc.status, headers=headers)


def _media_type(response: httpx.Response) -> str:
    content_type: str = response.headers.get("content-type", "")
    return content_type.split(";", 1)[0].strip().lower()


def _looks_like_playlist(first: bytes) -> bool:
    return first.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"#EXTM3U")


async def relay(
    request: Request,
    target: RelayTarget,
    *,
    profile: str = PROFILE_PASSTHROUGH,
    from_playlist: bool = False,
) -> Response:
    """Relay ``target`` to the client. ``from_playlist`` marks a fetch through a
    rewritten HLS URL: part of an HLS session, and logged at debug, since there
    is one per segment."""
    settings = get_settings()
    key: SessionKey = (target.tenant_id, target.channel_id, client_ip(request) or "unknown")
    host = urlsplit(target.url).hostname or ""
    fields = {
        "tenant": str(target.tenant_id),
        "channel": str(target.channel_id),
        "kind": target.kind.value,
        "host": host,
    }
    log = _log.debug if from_playlist else _log.info
    try:
        lease = await registry.acquire(
            key,
            per_tenant=settings.relay_max_streams_per_tenant,
            total=settings.relay_max_streams_total,
        )
    except RelayBusy:
        _log.warning("relay.busy", **fields)
        return _error_response(RelayError(503, "busy"))

    started = time.monotonic()
    log("relay.start", **fields)

    async def finish(sent: int, reason: str, *, sticky: bool) -> None:
        await lease.release(sticky=sticky)
        log(
            "relay.end",
            **fields,
            bytes=sent,
            duration_ms=int((time.monotonic() - started) * 1000),
            reason=reason,
        )

    upstream: httpx.Response | None = None
    chunks: AsyncIterator[bytes] | None = None
    try:
        upstream, final_url = await _open_upstream(target, request.headers)
        if upstream.status_code == 503:
            raise RelayError(503, "upstream_503", retry_after=upstream.headers.get("retry-after"))
        if upstream.status_code not in (200, 206):
            raise RelayError(502, f"upstream_{upstream.status_code}")
        media_type = _media_type(upstream)
        encoded = upstream.headers.get("content-encoding", "identity").lower() not in (
            "",
            "identity",
        )
        # Asked for identity; if it's compressed anyway, decode it and drop the
        # now-wrong length/range headers rather than pass a mislabelled body.
        chunks = upstream.aiter_bytes(_CHUNK) if encoded else upstream.aiter_raw(_CHUNK)
        try:
            first = await anext(chunks, b"")
        except httpx.TimeoutException as exc:
            raise RelayError(504, "upstream_timeout") from exc
        except httpx.HTTPError as exc:
            raise RelayError(502, "upstream_error") from exc
        is_hls = (
            media_type in _MPEGURL_TYPES
            or urlsplit(final_url).path.lower().endswith(".m3u8")
            or _looks_like_playlist(first)
        )
        if is_hls:
            body = await _read_manifest(first, chunks, settings.relay_manifest_max_bytes)
            text = body.decode("utf-8", errors="replace")
            rewritten = rewrite_playlist(
                text,
                base_url=final_url,
                target=target,
                profile=profile,
            )
            await _close(upstream, chunks)
            await finish(len(body), "playlist", sticky=True)
            return Response(
                rewritten, status_code=200, media_type=_HLS_MEDIA_TYPE, headers=dict(_NO_STORE)
            )
        if media_type and not (
            media_type in _MEDIA_TYPES or media_type.startswith(_MEDIA_PREFIXES)
        ):
            raise RelayError(502, "content_type")
    except RelayError as exc:
        await _close(upstream, chunks)
        await finish(0, exc.reason, sticky=from_playlist)
        return _error_response(exc)
    except BaseException:
        with anyio.CancelScope(shield=True):
            await _close(upstream, chunks)
            await finish(0, "error", sticky=from_playlist)
        raise

    headers = dict(_NO_STORE)
    headers["Content-Type"] = upstream.headers.get("content-type") or "application/octet-stream"
    passthrough = (
        ["accept-ranges"] if encoded else ["content-length", "content-range", "accept-ranges"]
    )
    for name in passthrough:
        value = upstream.headers.get(name)
        if value:
            headers[name] = value

    async def on_close(sent: int, reason: str) -> None:
        await finish(sent, reason, sticky=from_playlist)

    return RelayResponse(
        upstream=upstream,
        chunks=chunks,
        first=first,
        status_code=upstream.status_code,
        headers=headers,
        on_close=on_close,
    )


async def _read_manifest(first: bytes, chunks: AsyncIterator[bytes], cap: int) -> bytes:
    body = bytearray(first)
    try:
        async for chunk in chunks:
            body += chunk
            if len(body) > cap:
                raise RelayError(502, "manifest_too_large")
    except httpx.TimeoutException as exc:
        raise RelayError(504, "upstream_timeout") from exc
    except httpx.HTTPError as exc:
        raise RelayError(502, "upstream_error") from exc
    if len(body) > cap:
        raise RelayError(502, "manifest_too_large")
    return bytes(body)
