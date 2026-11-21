"""M3U/M3U8 playlist parsing (channel-list format). Parsing is ported verbatim
from ``tvdinner.m3u``; the fetch is async and SSRF-guarded."""

from __future__ import annotations

import re

from app.ingest.models import Channel, Playlist
from app.ingest.ssrf import fetch_text

_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_DURATION_RE = re.compile(r"^-?\d+(?:\.\d+)?\s*(.*)$")
# Tags only an HLS stream manifest carries: a master playlist lists variants
# (#EXT-X-STREAM-INF), a media playlist lists segments (#EXT-X-TARGETDURATION).
_HLS_MANIFEST_RE = re.compile(r"^\s*#EXT-X-(?:STREAM-INF|TARGETDURATION)\b", re.MULTILINE)
# ``x-tvg-url`` is often a comma-separated list (one feed per country/provider).
# Commas are legal inside a URL, so only split where the next piece starts a new
# http(s) URL.
_EPG_URL_SPLIT_RE = re.compile(r"\s*,\s*(?=https?://)", re.IGNORECASE)


def split_epg_urls(value: str | None) -> list[str]:
    """The distinct guide URLs an M3U header advertises, in order."""
    if not value:
        return []
    seen: dict[str, None] = {}
    for piece in _EPG_URL_SPLIT_RE.split(value.strip()):
        url = piece.strip()
        if url:
            seen.setdefault(url, None)
    return list(seen)


def _parse_extinf(line: str) -> tuple[dict[str, str], str]:
    match = _DURATION_RE.match(line)
    rest = match.group(1) if match else line
    attrs = dict(_ATTR_RE.findall(rest))
    stripped = _ATTR_RE.sub("", rest)
    name = stripped.split(",", 1)[1].strip() if "," in stripped else stripped.strip()
    return attrs, name


def parse_m3u(text: str) -> Playlist:
    playlist = Playlist()
    pending_attrs: dict[str, str] | None = None
    pending_name: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            header = dict(_ATTR_RE.findall(line))
            urls = split_epg_urls(header.get("x-tvg-url") or header.get("url-tvg"))
            # One URL is auto-attached. Several are only offered: fetching
            # every one (a playlist may list a hundred country feeds) is far
            # too heavy, and there's no telling which one fits.
            playlist.epg_url = urls[0] if len(urls) == 1 else None
            playlist.advertised_epg_urls = urls if len(urls) > 1 else []
            continue
        if line.startswith("#EXTINF:"):
            pending_attrs, pending_name = _parse_extinf(line[len("#EXTINF:") :])
            continue
        if line.startswith("#"):
            continue
        if pending_name is not None:
            attrs = pending_attrs or {}
            playlist.channels.append(
                Channel(
                    name=pending_name,
                    stream_ref=line,
                    tvg_id=attrs.get("tvg-id") or None,
                    tvg_name=attrs.get("tvg-name") or None,
                    tvg_logo=attrs.get("tvg-logo") or None,
                    group_title=attrs.get("group-title") or None,
                    tvg_url=attrs.get("tvg-url") or None,
                )
            )
            pending_attrs, pending_name = None, None
    return playlist


def looks_like_m3u(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped.startswith("#EXTM3U")
    return False


def is_hls_manifest(text: str) -> bool:
    """True for one stream's own HLS manifest rather than a channel list.

    Both start with ``#EXTM3U``, but parsing a manifest as a channel list finds
    nothing (a master playlist has no ``#EXTINF``) or worse (a media playlist's
    ``#EXTINF`` lines are segments, each of which would become a "channel")."""
    return bool(_HLS_MANIFEST_RE.search(text))


async def load_m3u_playlist(url: str) -> Playlist:
    text = await fetch_text(url, m3u_sniff=True)
    if is_hls_manifest(text):
        return Playlist(direct_stream=url)
    return parse_m3u(text)
