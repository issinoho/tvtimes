"""Serve channel logos from tvtimes' own origin.

Playlists often point ``tvg-logo`` at an ``http://`` LAN URL; on an HTTPS
deployment the browser won't load that as a page image. This fetches the logo
server-side (through the SSRF guard / allowlist), sniffs its type, and caches
the bytes briefly so a guide full of channels doesn't hammer the source.
"""

from __future__ import annotations

import time

from app.config import get_settings
from app.ingest.errors import SourceError
from app.ingest.ssrf import fetch_bytes

_MAX_BYTES = 2_000_000
_TTL_SECONDS = 6 * 3600
_MAX_ENTRIES = 800

# url -> (body, content_type, stored_at)
_cache: dict[str, tuple[bytes, str, float]] = {}


def _sniff(body: bytes) -> str | None:
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if body[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    head = body[:256].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        return "image/svg+xml"
    return None


async def fetch_logo(url: str) -> tuple[bytes, str] | None:
    """``(bytes, content_type)`` for a channel logo URL, or ``None`` if it can't
    be fetched or isn't an image."""
    hit = _cache.get(url)
    if hit is not None and time.monotonic() - hit[2] < _TTL_SECONDS:
        return hit[0], hit[1]

    try:
        result = await fetch_bytes(
            url, max_bytes=_MAX_BYTES, allowlist=get_settings().fetch_allowlist_entries
        )
    except SourceError:
        return None
    ctype = _sniff(result.body)
    if ctype is None:
        return None

    if len(_cache) >= _MAX_ENTRIES:
        _cache.clear()
    _cache[url] = (result.body, ctype, time.monotonic())
    return result.body, ctype
