"""The normalized channel model every source produces (ported from
``tvdinner.m3u``)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HD_MARKER_RE = re.compile(r"\bHD\b", re.IGNORECASE)


@dataclass(slots=True)
class Channel:
    name: str
    # For M3U/Xtream this is a playable URL. For Stalker it is the portal "cmd"
    # token, resolved to a URL lazily at play time.
    stream_ref: str
    tvg_id: str | None = None
    tvg_name: str | None = None
    tvg_logo: str | None = None
    group_title: str | None = None
    tvg_url: str | None = None
    number: int | None = None

    @property
    def groups(self) -> list[str]:
        if not self.group_title:
            return []
        return [g.strip() for g in self.group_title.split(";") if g.strip()]

    @property
    def is_hd(self) -> bool:
        return bool(_HD_MARKER_RE.search(self.name))


@dataclass(slots=True)
class Playlist:
    channels: list[Channel] = field(default_factory=list)
    # XMLTV URL discovered from the source (M3U header / Xtream xmltv.php).
    epg_url: str | None = None
    # Non-fatal notes to surface to the user (e.g. "account status: Expired").
    warnings: list[str] = field(default_factory=list)
