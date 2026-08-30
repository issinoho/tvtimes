"""Native HDHomeRun ingest: UDP discovery + ``discover.json`` / lineup fetch.

This runs **inside the backend** so a self-hosted deployment on the same LAN as
the tuner needs no connector agent. The connector still exists for off-network
setups (see ``connector/`` and ``app/services/connectors.py``).

Discovery follows the libhdhomerun wire format (type ``0x0002`` request,
``0x0003`` reply, TLV payload, trailing little-endian CRC-32). It is ported from
``connector/tvtimes_connector/hdhomerun.py`` and adapted to async httpx.

Security: a real HDHomeRun always lives on a private network, so both the
user-supplied ``device_url`` and any auto-discovered BaseURL are required to
resolve to a private (RFC1918 / ULA) address before the backend will fetch
them. This is the inverse of the general SSRF guard (which *rejects* private
addresses) and keeps the feature from being used as a proxy to arbitrary hosts.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import zlib
from urllib.parse import urljoin, urlsplit

import anyio
import httpx

from app.ingest.errors import SourceInvalid, SourceRejected, SourceUnreachable
from app.ingest.models import Channel, Playlist
from app.logging import get_logger

_DISCOVERY_PORT = 65001
_TYPE_DISCOVER_REQ = 0x0002
_TYPE_DISCOVER_RPY = 0x0003
_TAG_DEVICE_TYPE = 0x03
_TAG_DEVICE_ID = 0x04
_TAG_BASE_URL = 0x2A
_DEVICE_TYPE_TUNER = 0x00000001
_WILDCARD = 0xFFFFFFFF

_HDHR_XMLTV = "https://api.hdhomerun.com/api/xmltv?DeviceAuth={auth}"
_HDHR_GUIDE = "https://api.hdhomerun.com/api/guide.php?DeviceAuth={auth}"
_DISCOVER_TIMEOUT = 8.0
_LINEUP_TIMEOUT = 20.0

_log = get_logger("ingest.hdhomerun")


# --- UDP discovery -------------------------------------------------------------


def _tlv(tag: int, value: bytes) -> bytes:
    return struct.pack(">BB", tag, len(value)) + value


def build_discovery_request() -> bytes:
    payload = _tlv(_TAG_DEVICE_TYPE, struct.pack(">I", _DEVICE_TYPE_TUNER)) + _tlv(
        _TAG_DEVICE_ID, struct.pack(">I", _WILDCARD)
    )
    frame = struct.pack(">HH", _TYPE_DISCOVER_REQ, len(payload)) + payload
    return frame + struct.pack("<I", zlib.crc32(frame) & 0xFFFFFFFF)


def parse_discovery_reply(data: bytes) -> str | None:
    """Return the advertised BaseURL of a discovery reply, or ``None``."""
    if len(data) < 8:
        return None
    msg_type, length = struct.unpack(">HH", data[:4])
    if msg_type != _TYPE_DISCOVER_RPY:
        return None
    payload = data[4 : 4 + length]
    base_url = ""
    i = 0
    while i + 2 <= len(payload):
        tag, tag_len = payload[i], payload[i + 1]
        value = payload[i + 2 : i + 2 + tag_len]
        i += 2 + tag_len
        if tag == _TAG_BASE_URL:
            base_url = value.decode("ascii", "replace").rstrip("/")
    return base_url or None


def _discover_blocking(timeout: float) -> list[str]:
    request = build_discovery_request()
    found: set[str] = set()
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        sock.sendto(request, ("255.255.255.255", _DISCOVERY_PORT))
        while True:
            try:
                data, _addr = sock.recvfrom(2048)
            except TimeoutError:
                break
            base_url = parse_discovery_reply(data)
            if base_url:
                found.add(base_url)
    except OSError:
        pass
    finally:
        if sock is not None:
            sock.close()
    return sorted(found)


async def discover_device_urls(timeout: float = 2.0) -> list[str]:
    return await anyio.to_thread.run_sync(_discover_blocking, timeout)


# --- LAN address guard -------------------------------------------------------


async def _assert_lan_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise SourceRejected("An HDHomeRun URL must start with http:// or https://.")
    host = parts.hostname
    if not host:
        raise SourceRejected("The HDHomeRun URL has no host.")
    literal: ipaddress.IPv4Address | ipaddress.IPv6Address | None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    else:
        try:
            infos = await anyio.to_thread.run_sync(
                lambda: socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
            )
        except socket.gaierror as exc:
            raise SourceUnreachable(f"Could not resolve {host!r}.") from exc
        addresses = [str(info[4][0]) for info in infos]
    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_private or ip.is_loopback or ip.is_link_local:
            raise SourceRejected(
                f"{host!r} ({addr}) is not a private LAN address. Enter the "
                "HDHomeRun's address on your home network, e.g. http://192.168.1.50."
            )


# --- discover.json + lineup -------------------------------------------------


def _to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().split(".", 1)[0].isdigit():
        return int(value.strip().split(".", 1)[0])
    return None


async def _fetch_channel_images(client: httpx.AsyncClient, device_auth: str) -> dict[str, str]:
    """GuideNumber -> logo URL from the SiliconDust cloud guide. Best effort:
    logos are cosmetic and this endpoint needs guide data on the account."""
    try:
        r = await client.get(_HDHR_GUIDE.format(auth=device_auth), timeout=_LINEUP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return {}
    images: dict[str, str] = {}
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        number = str(entry.get("GuideNumber") or "").strip()
        image = entry.get("ImageURL")
        if number and isinstance(image, str) and image:
            images[number] = image
    return images


async def _fetch_device(
    client: httpx.AsyncClient, base_url: str
) -> tuple[list[Channel], str | None, str | None]:
    base_url = base_url.rstrip("/")
    await _assert_lan_url(base_url)
    try:
        r = await client.get(f"{base_url}/discover.json", timeout=_DISCOVER_TIMEOUT)
        r.raise_for_status()
        discover = r.json()
    except httpx.HTTPError as exc:
        raise SourceUnreachable(
            f"Could not reach the HDHomeRun at {base_url} ({exc.__class__.__name__})."
        ) from exc
    except ValueError as exc:
        raise SourceInvalid(f"{base_url}/discover.json did not return JSON.") from exc
    if not isinstance(discover, dict) or not discover.get("LineupURL"):
        raise SourceInvalid(f"{base_url} does not look like an HDHomeRun (no LineupURL).")

    lineup_url = urljoin(f"{base_url}/", str(discover["LineupURL"]))
    await _assert_lan_url(lineup_url)
    try:
        r = await client.get(lineup_url, timeout=_LINEUP_TIMEOUT)
        r.raise_for_status()
        entries = r.json()
    except httpx.HTTPError as exc:
        raise SourceUnreachable(
            f"Could not read the channel lineup from {base_url} ({exc.__class__.__name__})."
        ) from exc
    except ValueError as exc:
        raise SourceInvalid(f"The HDHomeRun lineup at {base_url} was not JSON.") from exc

    name = str(discover.get("FriendlyName") or "HDHomeRun")
    channels: list[Channel] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not entry.get("URL"):
            continue
        number = _to_int(entry.get("GuideNumber"))
        guide_number = str(entry.get("GuideNumber") or "").strip()
        display = str(entry.get("GuideName") or guide_number or "Channel")
        if entry.get("HD") and not display.upper().endswith(" HD"):
            display = f"{display} HD"
        channels.append(
            Channel(
                name=display,
                stream_ref=str(entry["URL"]),
                tvg_id=guide_number or None,
                tvg_name=str(entry.get("GuideName") or "") or None,
                group_title=name,
                number=number,
            )
        )

    auth = discover.get("DeviceAuth")
    auth_str = str(auth) if auth else None
    epg_url = _HDHR_XMLTV.format(auth=auth_str) if auth_str else None
    return channels, epg_url, auth_str


async def load_hdhomerun_playlist(config: dict[str, object]) -> Playlist:
    device_url = str(config.get("device_url") or "").strip().rstrip("/")
    base_urls = [device_url] if device_url else await discover_device_urls()
    if not base_urls:
        raise SourceUnreachable(
            "No HDHomeRun was found on the network. Enter the tuner's address "
            "(e.g. http://192.168.1.50) — auto-discovery needs UDP broadcast, "
            "which Docker's default bridge network blocks."
        )

    playlist = Playlist()
    seen_streams: set[str] = set()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for i, base in enumerate(base_urls):
            channels, epg_url, device_auth = await _fetch_device(client, base)
            if i == 0 and epg_url:
                playlist.epg_url = epg_url
            images = (
                await _fetch_channel_images(client, device_auth) if device_auth and channels else {}
            )
            for ch in channels:
                if ch.stream_ref in seen_streams:
                    continue
                seen_streams.add(ch.stream_ref)
                if ch.tvg_id and ch.tvg_id in images:
                    ch.tvg_logo = images[ch.tvg_id]
                playlist.channels.append(ch)

    if not playlist.channels:
        raise SourceInvalid("The HDHomeRun returned an empty channel lineup.")
    _log.info("hdhomerun.ingested", devices=len(base_urls), channels=len(playlist.channels))
    return playlist
