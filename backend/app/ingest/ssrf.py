"""Guarded outbound HTTP for user-supplied URLs.

Every fetch resolves the host and refuses non-public addresses (loopback,
private, link-local — including the cloud metadata IP 169.254.169.254 — CGNAT,
reserved). Redirects are followed manually so each hop is re-checked. Bodies
are size-capped.

The connection is **pinned to the address we validated**: the socket connects
to that IP while the URL — and therefore the ``Host`` header and the TLS SNI /
certificate check — keeps the original hostname (:class:`_PinnedBackend`).
Without this a hostname could resolve public for the check and to
``127.0.0.1`` / ``169.254.169.254`` for httpx's own second lookup on connect —
DNS rebinding. An explicitly allow-listed *hostname* is trusted as-is and not
pinned.
"""

from __future__ import annotations

import contextvars
import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import anyio
import httpx

from app.config import get_settings
from app.ingest.errors import SourceInvalid, SourceRejected, SourceUnreachable
from app.ingest.redact import redact_resource_url

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_REDIRECTS = 5
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_M3U_SNIFF_BYTES = 4096

# The address the *next* request must connect to, set per redirect hop by the
# fetch helpers and read by _PinnedBackend at connect time. A ContextVar so
# concurrent fetches in the worker don't tread on each other.
_pin_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("tvtimes_pin", default=None)


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    ):
        return False
    return not (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT)


async def _resolve(host: str) -> list[str]:
    try:
        infos = await anyio.to_thread.run_sync(
            lambda: socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        )
    except socket.gaierror as exc:
        raise SourceUnreachable(f"Could not resolve host {host!r}.") from exc
    return [str(info[4][0]) for info in infos]


_IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse_allowlist(entries: list[str] | None) -> tuple[set[str], list[_IpNetwork]]:
    """An allowlist entry is either a hostname (matched exactly, case-insensitively)
    or an IP / CIDR (e.g. ``192.168.0.0/24``) that a resolved address may fall in."""
    hosts: set[str] = set()
    nets: list[_IpNetwork] = []
    for entry in entries or []:
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            hosts.add(entry.lower())
    return hosts, nets


async def resolve_allowed(url: str, *, allowlist: list[str] | None = None) -> list[str] | None:
    """Validate `url` against the SSRF policy and return the addresses a request
    may connect to:

    * ``None`` — the host is an explicitly allow-listed *hostname*; trust it and
      let the client resolve it normally (no pinning).
    * ``[ip, ...]`` — validated addresses; the caller must connect to one of
      these (see ``_PinningTransport``), never re-resolve.

    Raises ``SourceRejected`` for a bad scheme or a non-public address, and
    ``SourceUnreachable`` if the host can't be resolved."""
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise SourceRejected(f"Only http(s) URLs are allowed (got {parts.scheme or 'no'} scheme).")
    host = parts.hostname
    if not host:
        raise SourceRejected("The URL has no host.")

    allow_hosts, allow_nets = _parse_allowlist(allowlist)
    if host.lower() in allow_hosts:
        return None

    literal: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    addresses = [str(literal)] if literal is not None else await _resolve(host)
    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if allow_nets and any(ip in net for net in allow_nets):
            continue  # explicitly allow-listed range (e.g. your LAN)
        if not _ip_is_public(ip):
            raise SourceRejected(
                f"{host!r} resolves to a non-public address ({addr}); refusing to fetch it. "
                "Add it to TVTIMES_FETCH_ALLOWLIST (a host, IP, or CIDR) to permit it."
            )
    return addresses


async def assert_allowed_url(url: str, *, allowlist: list[str] | None = None) -> None:
    """A pre-flight of :func:`resolve_allowed` for callers that only need the
    yes/no (e.g. validating a source URL at save time, before any fetch)."""
    await resolve_allowed(url, allowlist=allowlist)


class _PinnedBackend:
    """Wraps httpcore's network backend so ``connect_tcp`` goes to the IP in
    ``_pin_ctx`` instead of the URL's hostname. The URL (and therefore the
    ``Host`` header and the TLS SNI / cert check, which httpcore derives from
    it) is untouched — only the socket target changes. When ``_pin_ctx`` is
    unset (an allow-listed hostname) the hostname is used as normal."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def connect_tcp(self, host: str, port: int, **kwargs: Any) -> Any:
        return await self._inner.connect_tcp(_pin_ctx.get() or host, port, **kwargs)

    def __getattr__(self, name: str) -> Any:  # delegate connect_unix_socket, sleep, …
        return getattr(self._inner, name)


class _GuardedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Duck-typed drop-in for httpcore's AsyncNetworkBackend (delegates
        # everything except connect_tcp).
        self._pool._network_backend = _PinnedBackend(self._pool._network_backend)  # type: ignore[assignment]


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=_GuardedTransport(),
        follow_redirects=False,
        timeout=timeout,
    )


async def fetch_text(
    url: str,
    *,
    max_bytes: int | None = None,
    timeout: float | None = None,
    allowlist: list[str] | None = None,
    m3u_sniff: bool = False,
) -> str:
    settings = get_settings()
    max_bytes = max_bytes or settings.fetch_max_bytes
    timeout = timeout or settings.fetch_timeout_seconds
    allowlist = allowlist if allowlist is not None else settings.fetch_allowlist_entries

    current = url
    async with _client(timeout) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            pins = await resolve_allowed(current, allowlist=allowlist)
            token = _pin_ctx.set(pins[0] if pins else None)
            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceUnreachable("Redirect with no Location header.")
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise SourceUnreachable(
                            f"{redact_resource_url(current)} returned HTTP {response.status_code}."
                        )
                    return await _read_capped(response, max_bytes, m3u_sniff)
            except httpx.HTTPError as exc:
                raise SourceUnreachable(
                    f"Could not fetch {redact_resource_url(current)}: {exc.__class__.__name__}."
                ) from exc
            finally:
                _pin_ctx.reset(token)
    raise SourceUnreachable("Too many redirects.")


@dataclass(slots=True)
class BytesResult:
    status: int  # 200 or 304
    body: bytes  # empty on 304; gzip bodies are already decompressed
    etag: str | None
    last_modified: str | None


async def fetch_bytes(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    max_bytes: int | None = None,
    timeout: float | None = None,
    allowlist: list[str] | None = None,
) -> BytesResult:
    """Conditional GET for large blobs (XMLTV). A gzip body is transparently
    decompressed. ``304`` is returned as-is so the caller can keep what it has."""
    from app.ingest.xmltv import maybe_decompress

    settings = get_settings()
    max_bytes = max_bytes or settings.fetch_max_bytes
    timeout = timeout or settings.fetch_timeout_seconds
    allowlist = allowlist if allowlist is not None else settings.fetch_allowlist_entries

    headers: dict[str, str] = {"Accept-Encoding": "gzip"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    current = url
    async with _client(timeout) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            pins = await resolve_allowed(current, allowlist=allowlist)
            token = _pin_ctx.set(pins[0] if pins else None)
            try:
                async with client.stream("GET", current, headers=headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceUnreachable("Redirect with no Location header.")
                        current = urljoin(current, location)
                        continue
                    if response.status_code == 304:
                        return BytesResult(304, b"", etag, last_modified)
                    if response.status_code >= 400:
                        raise SourceUnreachable(
                            f"{redact_resource_url(current)} returned HTTP {response.status_code}."
                        )
                    body = await _read_bytes_capped(response, max_bytes)
                    return BytesResult(
                        200,
                        maybe_decompress(body),
                        response.headers.get("etag"),
                        response.headers.get("last-modified"),
                    )
            except httpx.HTTPError as exc:
                raise SourceUnreachable(
                    f"Could not fetch {redact_resource_url(current)}: {exc.__class__.__name__}."
                ) from exc
            finally:
                _pin_ctx.reset(token)
    raise SourceUnreachable("Too many redirects.")


async def _read_bytes_capped(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes(65536):
        total += len(chunk)
        if total > max_bytes:
            raise SourceRejected("The source response is larger than the allowed limit.")
        chunks.append(chunk)
    return b"".join(chunks)


async def _read_capped(response: httpx.Response, max_bytes: int, m3u_sniff: bool) -> str:
    chunks: list[bytes] = []
    total = 0
    sniffed = not m3u_sniff
    async for chunk in response.aiter_bytes(_M3U_SNIFF_BYTES):
        if not sniffed:
            head = chunk.lstrip()
            if not head.startswith(b"#EXTM3U"):
                raise SourceInvalid("That URL did not return an M3U playlist.")
            sniffed = True
        total += len(chunk)
        if total > max_bytes:
            raise SourceRejected("The source response is larger than the allowed limit.")
        chunks.append(chunk)
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


async def fetch_json(
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    allowlist: list[str] | None = None,
) -> Any:
    settings = get_settings()
    timeout = timeout or settings.fetch_timeout_seconds
    allowlist = allowlist if allowlist is not None else settings.fetch_allowlist_entries

    pins = await resolve_allowed(url, allowlist=allowlist)
    token = _pin_ctx.set(pins[0] if pins else None)
    try:
        async with _client(timeout) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise SourceUnreachable(
            f"Could not reach {redact_resource_url(url)}: {exc.__class__.__name__}."
        ) from exc
    finally:
        _pin_ctx.reset(token)
    if response.is_redirect:
        raise SourceUnreachable(f"{redact_resource_url(url)} unexpectedly redirected.")
    if response.status_code >= 400:
        raise SourceUnreachable(f"{redact_resource_url(url)} returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise SourceInvalid(f"{redact_resource_url(url)} did not return JSON.") from exc
