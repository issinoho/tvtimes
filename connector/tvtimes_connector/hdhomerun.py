"""HDHomeRun discovery + lineup fetching.

UDP broadcast discovery follows the libhdhomerun wire format (type 0x0002
request, 0x0003 reply, TLV payload, trailing little-endian CRC-32). Devices
found this way — plus any explicitly configured base URLs — are then queried
over HTTP for ``discover.json`` and their lineup.
"""

from __future__ import annotations

import socket
import struct
import zlib
from dataclasses import dataclass, field

import httpx

_DISCOVERY_PORT = 65001
_TYPE_DISCOVER_REQ = 0x0002
_TYPE_DISCOVER_RPY = 0x0003
_TAG_DEVICE_TYPE = 0x03
_TAG_DEVICE_ID = 0x04
_TAG_BASE_URL = 0x2A
_DEVICE_TYPE_TUNER = 0x00000001
_WILDCARD = 0xFFFFFFFF


@dataclass
class Device:
    base_url: str
    device_id: str = ""
    friendly_name: str = "HDHomeRun"
    model: str | None = None
    tuner_count: int | None = None
    device_auth: str | None = None


@dataclass
class LineupChannel:
    name: str
    stream_url: str
    number: int | None = None
    hd: bool = False


@dataclass
class DeviceLineup:
    device: Device
    epg_url: str | None
    channels: list[LineupChannel] = field(default_factory=list)


# --- UDP discovery ---------------------------------------------------------


def _tlv(tag: int, value: bytes) -> bytes:
    return struct.pack(">BB", tag, len(value)) + value


def build_discovery_request() -> bytes:
    payload = _tlv(_TAG_DEVICE_TYPE, struct.pack(">I", _DEVICE_TYPE_TUNER)) + _tlv(
        _TAG_DEVICE_ID, struct.pack(">I", _WILDCARD)
    )
    frame = struct.pack(">HH", _TYPE_DISCOVER_REQ, len(payload)) + payload
    return frame + struct.pack("<I", zlib.crc32(frame) & 0xFFFFFFFF)


def parse_discovery_reply(data: bytes) -> Device | None:
    if len(data) < 8:
        return None
    msg_type, length = struct.unpack(">HH", data[:4])
    if msg_type != _TYPE_DISCOVER_RPY:
        return None
    payload = data[4 : 4 + length]
    device = Device(base_url="")
    i = 0
    while i + 2 <= len(payload):
        tag, tag_len = payload[i], payload[i + 1]
        value = payload[i + 2 : i + 2 + tag_len]
        i += 2 + tag_len
        if tag == _TAG_DEVICE_ID and tag_len == 4:
            device.device_id = f"{struct.unpack('>I', value)[0]:08X}"
        elif tag == _TAG_BASE_URL:
            device.base_url = value.decode("ascii", "replace").rstrip("/")
    return device if device.base_url else None


def discover_devices(timeout: float = 2.0) -> list[Device]:
    request = build_discovery_request()
    found: dict[str, Device] = {}
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
            device = parse_discovery_reply(data)
            if device:
                found[device.base_url] = device
    except OSError:
        pass
    finally:
        if sock is not None:
            sock.close()
    return list(found.values())


# --- HTTP: discover.json + lineup ------------------------------------------


def _to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().split(".", 1)[0].isdigit():
        return int(value.strip().split(".", 1)[0])
    return None


def fetch_lineup(client: httpx.Client, base_url: str) -> DeviceLineup | None:
    base_url = base_url.rstrip("/")
    try:
        discover = client.get(f"{base_url}/discover.json", timeout=8.0).raise_for_status().json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(discover, dict) or "LineupURL" not in discover:
        return None

    device = Device(
        base_url=base_url,
        device_id=str(discover.get("DeviceID") or ""),
        friendly_name=str(discover.get("FriendlyName") or "HDHomeRun"),
        model=discover.get("ModelNumber"),
        tuner_count=_to_int(discover.get("TunerCount")),
        device_auth=discover.get("DeviceAuth"),
    )
    try:
        entries = client.get(str(discover["LineupURL"]), timeout=15.0).raise_for_status().json()
    except (httpx.HTTPError, ValueError):
        return None

    channels: list[LineupChannel] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not entry.get("URL"):
            continue
        channels.append(
            LineupChannel(
                name=str(entry.get("GuideName") or entry.get("GuideNumber") or "Channel"),
                stream_url=str(entry["URL"]),
                number=_to_int(entry.get("GuideNumber")),
                hd=bool(entry.get("HD")),
            )
        )

    epg_url = (
        f"https://api.hdhomerun.com/api/xmltv?DeviceAuth={device.device_auth}"
        if device.device_auth
        else None
    )
    return DeviceLineup(device=device, epg_url=epg_url, channels=channels)


def collect_lineups(extra_base_urls: list[str], *, discover: bool = True) -> list[DeviceLineup]:
    base_urls: list[str] = list(extra_base_urls)
    if discover:
        base_urls += [d.base_url for d in discover_devices()]
    seen: set[str] = set()
    lineups: list[DeviceLineup] = []
    with httpx.Client(follow_redirects=True) as client:
        for base in base_urls:
            b = base.rstrip("/")
            if b in seen:
                continue
            seen.add(b)
            lineup = fetch_lineup(client, b)
            if lineup is not None:
                lineups.append(lineup)
    return lineups
