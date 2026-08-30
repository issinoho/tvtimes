"""Channel-logo backfill from the iptv-org channel database.

Playlists frequently omit ``tvg-logo`` (and HDHomeRun lineups never carry one).
This fills ``channel.logo_url`` from the public iptv-org channel list, matching
by tvg-id or by normalised channel / alt name. It is best-effort: any failure
is logged and leaves logos untouched — a refresh never fails over artwork.
"""

from __future__ import annotations

import json
import time

from app.ingest.xmltv import normalize_name
from app.logging import get_logger

_SOURCE_URL = "https://iptv-org.github.io/api/channels.json"
_TTL_SECONDS = 24 * 3600

_log = get_logger("ingest.channel_logos")

# lookup key (lower-cased tvg-id, or normalised name) -> logo URL
_index: dict[str, str] = {}
_loaded_at = 0.0


def _build_index(entries: object) -> dict[str, str]:
    index: dict[str, str] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        logo = entry.get("logo")
        if not isinstance(logo, str) or not logo:
            continue
        channel_id = entry.get("id")
        if isinstance(channel_id, str) and channel_id:
            index.setdefault(channel_id.lower(), logo)
        candidates = [entry.get("name"), *(entry.get("alt_names") or [])]
        for name in candidates:
            if isinstance(name, str) and name.strip():
                index.setdefault(normalize_name(name), logo)
    return index


async def load_index(*, force: bool = False) -> dict[str, str]:
    """The id/name -> logo map, fetched from iptv-org and cached for a day.
    Returns whatever is cached (possibly empty) if the fetch fails."""
    global _index, _loaded_at
    if _index and not force and time.monotonic() - _loaded_at < _TTL_SECONDS:
        return _index

    from app.ingest.ssrf import fetch_bytes  # local import: avoids an import cycle

    try:
        result = await fetch_bytes(_SOURCE_URL)
        built = _build_index(json.loads(result.body))
    except Exception as exc:  # cosmetic feature — a failure must not break a refresh
        _log.warning("channel_logos.load_failed", error=f"{type(exc).__name__}: {exc}")
        return _index

    if built:
        _index, _loaded_at = built, time.monotonic()
        _log.info("channel_logos.loaded", channels=len(built))
    return _index


def lookup(
    index: dict[str, str], *, ext_id: str | None, name: str, tvg_name: str | None = None
) -> str | None:
    if ext_id:
        hit = index.get(ext_id.lower())
        if hit:
            return hit
    for candidate in (name, tvg_name):
        if candidate:
            hit = index.get(normalize_name(candidate))
            if hit:
                return hit
    return None
