"""Xtream Codes panel support (ported from ``tvdinner.xtream``, async fetch).

Credentials are kept out of stored channel rows: each channel keeps its numeric
``stream_id`` (as ``stream_ref``) and the playable URL is rebuilt from the
source's stored credentials at play time via :func:`build_live_url`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from app.ingest.errors import SourceInvalid
from app.ingest.models import Channel, Playlist
from app.ingest.ssrf import fetch_json


@dataclass(slots=True)
class XtreamCreds:
    base_url: str  # "http(s)://host[:port]", no trailing slash
    username: str
    password: str
    output: str = "ts"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> XtreamCreds:
        return cls(
            base_url=str(config["server_url"]).rstrip("/"),
            username=str(config["username"]),
            password=str(config["password"]),
            output=str(config.get("output") or "ts"),
        )


def parse_xtream_url(source: str) -> XtreamCreds | None:
    """Accept a pasted ``xtream://user:pass@host:port`` login URL."""
    parts = urlsplit(source)
    if parts.scheme not in ("xtream", "xtreams"):
        return None
    if not parts.hostname or not parts.username or not parts.password:
        return None
    scheme = "https" if parts.scheme == "xtreams" else "http"
    port = f":{parts.port}" if parts.port else ""
    output = (parse_qs(parts.query).get("output") or ["ts"])[0].strip() or "ts"
    return XtreamCreds(
        base_url=f"{scheme}://{parts.hostname}{port}",
        username=unquote(parts.username),
        password=unquote(parts.password),
        output=output,
    )


def xtream_epg_url(creds: XtreamCreds) -> str:
    return f"{creds.base_url}/xmltv.php?username={creds.username}&password={creds.password}"


def build_live_url(creds: XtreamCreds, stream_id: str) -> str:
    return f"{creds.base_url}/live/{creds.username}/{creds.password}/{stream_id}.{creds.output}"


async def _api_get(creds: XtreamCreds, action: str | None, **extra: str) -> Any:
    params = {"username": creds.username, "password": creds.password}
    if action:
        params["action"] = action
    params.update(extra)
    return await fetch_json(f"{creds.base_url}/player_api.php", params=params)


async def load_xtream_playlist(creds: XtreamCreds) -> Playlist:
    handshake = await _api_get(creds, None)
    user_info = handshake.get("user_info") if isinstance(handshake, dict) else None
    if not isinstance(user_info, dict) or not user_info.get("auth"):
        raise SourceInvalid("The Xtream username or password was not accepted.")

    warnings: list[str] = []
    status = user_info.get("status")
    if status and status != "Active":
        warnings.append(f"Xtream account status is {status!r}.")

    categories_raw = await _api_get(creds, "get_live_categories")
    streams_raw = await _api_get(creds, "get_live_streams")

    categories: dict[str, str] = {}
    if isinstance(categories_raw, list):
        for cat in categories_raw:
            if isinstance(cat, dict) and cat.get("category_id") is not None:
                categories[str(cat["category_id"])] = str(cat.get("category_name") or "")

    channels: list[Channel] = []
    for stream in streams_raw if isinstance(streams_raw, list) else []:
        if not isinstance(stream, dict):
            continue
        stream_id = stream.get("stream_id")
        name = stream.get("name")
        if stream_id is None or not name:
            continue

        ids: list[str] = []
        if isinstance(stream.get("category_ids"), list) and stream["category_ids"]:
            ids = [str(i) for i in stream["category_ids"]]
        elif stream.get("category_id") is not None:
            ids = [str(stream["category_id"])]
        group = ";".join(categories[i] for i in ids if categories.get(i)) or None

        epg_id = stream.get("epg_channel_id") or None
        channels.append(
            Channel(
                name=str(name),
                stream_ref=str(stream_id),
                tvg_id=str(epg_id) if epg_id else None,
                tvg_logo=stream.get("stream_icon") or None,
                group_title=group,
                number=stream.get("num") if isinstance(stream.get("num"), int) else None,
            )
        )

    return Playlist(channels=channels, epg_url=xtream_epg_url(creds), warnings=warnings)
