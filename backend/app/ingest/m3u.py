"""M3U/M3U8 playlist parsing (channel-list format). Parsing is ported verbatim
from ``tvdinner.m3u``; the fetch is async and SSRF-guarded."""

from __future__ import annotations

import re

from app.ingest.models import Channel, Playlist
from app.ingest.ssrf import fetch_text

_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_DURATION_RE = re.compile(r"^-?\d+(?:\.\d+)?\s*(.*)$")


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
            playlist.epg_url = header.get("x-tvg-url") or header.get("url-tvg")
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


async def load_m3u_playlist(url: str) -> Playlist:
    text = await fetch_text(url, m3u_sniff=True)
    return parse_m3u(text)
