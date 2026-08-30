"""Stalker Portal / Ministra support (ported from ``tvdinner.stalker``).

Unlike the CLI, ``create_link`` is **not** resolved per channel at ingest —
the portal's short-lived stream URLs and rate limits make that a play-time
concern. Each channel keeps its opaque ``cmd`` token as ``stream_ref``.
"""

from __future__ import annotations

import contextlib
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.ingest.errors import SourceInvalid
from app.ingest.models import Channel, Playlist
from app.ingest.ssrf import fetch_json

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_USER_AGENT = (
    "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) "
    "MAG200 stbapp ver: 2 rev: 250 Safari/533.3"
)


@dataclass(slots=True)
class StalkerCreds:
    base_url: str
    portal_path: str
    mac: str
    serial: str | None = None
    device_id: str | None = None
    stb_type: str = "MAG250"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> StalkerCreds:
        parts = urlsplit(str(config["portal_url"]))
        scheme = "https" if parts.scheme in ("https", "stalkers") else "http"
        port = f":{parts.port}" if parts.port else ""
        path = parts.path or "/"
        return cls(
            base_url=f"{scheme}://{parts.hostname}{port}",
            portal_path=path if path.endswith(".php") else path.rstrip("/") + "/portal.php",
            mac=str(config["mac"]),
            serial=(config.get("serial") or None) and str(config["serial"]),
            device_id=(config.get("device_id") or None) and str(config["device_id"]),
            stb_type=str(config.get("stb_type") or "MAG250"),
        )


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None


def parse_stalker_url(source: str) -> StalkerCreds | None:
    parts = urlsplit(source)
    if parts.scheme not in ("stalker", "stalkers") or not parts.hostname:
        return None
    query = parse_qs(parts.query)
    mac = _first(query.get("mac")) or ""
    if not _MAC_RE.match(mac):
        return None
    scheme = "https" if parts.scheme == "stalkers" else "http"
    port = f":{parts.port}" if parts.port else ""
    path = parts.path or "/"
    return StalkerCreds(
        base_url=f"{scheme}://{parts.hostname}{port}",
        portal_path=path if path.endswith(".php") else path.rstrip("/") + "/portal.php",
        mac=mac,
        serial=_first(query.get("serial")),
        device_id=_first(query.get("device_id")),
        stb_type=_first(query.get("stb_type")) or "MAG250",
    )


def valid_mac(mac: str) -> bool:
    return bool(_MAC_RE.match(mac))


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _tz_name() -> str:
    try:
        return time.tzname[time.localtime().tm_isdst > 0] or "GMT"
    except Exception:
        return "GMT"


def _headers(creds: StalkerCreds, token: str | None) -> dict[str, str]:
    headers = {
        "User-Agent": _USER_AGENT,
        "X-User-Agent": f"Model: {creds.stb_type}; Link: WiFi",
        "Cookie": f"mac={creds.mac}; stb_lang=en; timezone={_tz_name()}",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _api_get(creds: StalkerCreds, params: dict[str, str], token: str | None) -> Any:
    return await fetch_json(
        f"{creds.base_url}{creds.portal_path}", params=params, headers=_headers(creds, token)
    )


async def _fetch_genres(creds: StalkerCreds, token: str) -> dict[str, str]:
    raw = await _api_get(
        creds, {"type": "itv", "action": "get_genres", "JsHttpRequest": "1-xml"}, token
    )
    js = raw.get("js") if isinstance(raw, dict) else None
    out: dict[str, str] = {}
    for cat in js if isinstance(js, list) else []:
        if isinstance(cat, dict) and cat.get("id") is not None:
            out[str(cat["id"])] = str(cat.get("title") or "")
    return out


async def _fetch_channels(creds: StalkerCreds, token: str) -> list[dict[str, Any]]:
    raw = await _api_get(
        creds,
        {"type": "itv", "action": "get_all_channels", "JsHttpRequest": "1-xml"},
        token,
    )
    data = raw.get("js") if isinstance(raw, dict) else None
    items = data.get("data") if isinstance(data, dict) else None
    if items:
        return [i for i in items if isinstance(i, dict)]

    collected: list[dict[str, Any]] = []
    page = 1
    while True:
        page_raw = await _api_get(
            creds,
            {
                "type": "itv",
                "action": "get_ordered_list",
                "genre": "*",
                "p": str(page),
                "JsHttpRequest": "1-xml",
            },
            token,
        )
        page_data = page_raw.get("js") if isinstance(page_raw, dict) else None
        page_items = page_data.get("data") if isinstance(page_data, dict) else None
        if not page_items:
            break
        collected.extend(i for i in page_items if isinstance(i, dict))
        total = page_data.get("total_items") if isinstance(page_data, dict) else None
        if total is None or len(collected) >= int(total):
            break
        page += 1
    return collected


async def load_stalker_playlist(creds: StalkerCreds) -> Playlist:
    handshake = await _api_get(
        creds, {"type": "stb", "action": "handshake", "token": "", "JsHttpRequest": "1-xml"}, None
    )
    js = handshake.get("js") if isinstance(handshake, dict) else None
    token = js.get("token") if isinstance(js, dict) else None
    if not token:
        raise SourceInvalid(
            "The Stalker portal did not authenticate — check the portal URL, path and MAC."
        )

    # Not every portal fork needs get_profile before channels resolve.
    with contextlib.suppress(SourceInvalid):
        await _api_get(
            creds,
            {
                "type": "stb",
                "action": "get_profile",
                "mac": creds.mac,
                "sn": creds.serial or "",
                "stb_type": creds.stb_type,
                "device_id": creds.device_id or "",
                "JsHttpRequest": "1-xml",
            },
            token,
        )

    genres = await _fetch_genres(creds, token)
    channels: list[Channel] = []
    for raw in await _fetch_channels(creds, token):
        cmd = raw.get("cmd")
        name = raw.get("name")
        if not cmd or not name:
            continue
        logo = raw.get("logo") or None
        if logo and not logo.startswith(("http://", "https://")):
            logo = f"{creds.base_url.rstrip('/')}/{logo.lstrip('/')}"
        genre_id = raw.get("tv_genre_id")
        xmltv_id = raw.get("xmltv_id") or None
        channels.append(
            Channel(
                name=str(name),
                stream_ref=str(cmd),
                tvg_id=str(xmltv_id) if xmltv_id else None,
                tvg_logo=logo,
                group_title=genres.get(str(genre_id)) if genre_id is not None else None,
                number=_as_int(raw.get("number")),
            )
        )
    return Playlist(channels=channels)
