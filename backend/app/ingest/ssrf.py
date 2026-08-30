"""Guarded outbound HTTP for user-supplied URLs.

Every fetch resolves the host and refuses non-public addresses (loopback,
private, link-local — including the cloud metadata IP 169.254.169.254 — CGNAT,
reserved). Redirects are followed manually so each hop is re-checked. Bodies
are size-capped.
"""

from __future__ import annotations

import ipaddress
import socket
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


async def assert_allowed_url(url: str, *, allowlist: list[str] | None = None) -> None:
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise SourceRejected(f"Only http(s) URLs are allowed (got {parts.scheme or 'no'} scheme).")
    host = parts.hostname
    if not host:
        raise SourceRejected("The URL has no host.")
    if allowlist and host in allowlist:
        return

    literal: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    addresses = [str(literal)] if literal is not None else await _resolve(host)
    for addr in addresses:
        if not _ip_is_public(ipaddress.ip_address(addr)):
            raise SourceRejected(
                f"{host!r} resolves to a non-public address ({addr}); refusing to fetch it."
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
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            await assert_allowed_url(current, allowlist=allowlist)
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
    raise SourceUnreachable("Too many redirects.")


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

    await assert_allowed_url(url, allowlist=allowlist)
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise SourceUnreachable(
            f"Could not reach {redact_resource_url(url)}: {exc.__class__.__name__}."
        ) from exc
    if response.is_redirect:
        raise SourceUnreachable(f"{redact_resource_url(url)} unexpectedly redirected.")
    if response.status_code >= 400:
        raise SourceUnreachable(f"{redact_resource_url(url)} returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise SourceInvalid(f"{redact_resource_url(url)} did not return JSON.") from exc
