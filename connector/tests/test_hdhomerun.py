from __future__ import annotations

import struct
import zlib

import httpx
import respx

from tvtimes_connector.hdhomerun import (
    build_discovery_request,
    collect_lineups,
    fetch_lineup,
    parse_discovery_reply,
)


def test_discovery_request_is_well_formed() -> None:
    frame = build_discovery_request()
    msg_type, length = struct.unpack(">HH", frame[:4])
    assert msg_type == 0x0002
    body, crc = frame[:-4], struct.unpack("<I", frame[-4:])[0]
    assert length == len(body) - 4
    assert crc == zlib.crc32(body) & 0xFFFFFFFF


def test_parse_discovery_reply_extracts_base_url() -> None:
    base = b"http://192.168.1.50:80"
    payload = struct.pack(">BB", 0x04, 4) + struct.pack(">I", 0x10501234)  # DEVICE_ID
    payload += struct.pack(">BB", 0x2A, len(base)) + base  # BASE_URL
    frame = struct.pack(">HH", 0x0003, len(payload)) + payload + b"\x00\x00\x00\x00"

    device = parse_discovery_reply(frame)
    assert device is not None
    assert device.base_url == "http://192.168.1.50:80"
    assert device.device_id == "10501234"

    # a non-reply message type is ignored
    assert parse_discovery_reply(struct.pack(">HH", 0x0002, 0)) is None


DISCOVER = {
    "FriendlyName": "HDHomeRun CONNECT",
    "ModelNumber": "HDHR5-2US",
    "DeviceID": "10501234",
    "TunerCount": 2,
    "DeviceAuth": "abc123",
    "LineupURL": "http://192.168.1.50/lineup.json",
}
LINEUP = [
    {"GuideNumber": "5.1", "GuideName": "NBC", "URL": "http://192.168.1.50/auto/v5.1", "HD": 1},
    {"GuideNumber": "7", "GuideName": "ABC HD", "URL": "http://192.168.1.50/auto/v7"},
    {"GuideNumber": "9", "GuideName": "PBS"},  # no URL -> skipped
]


@respx.mock
def test_fetch_lineup() -> None:
    respx.get("http://192.168.1.50/discover.json").mock(
        return_value=httpx.Response(200, json=DISCOVER)
    )
    respx.get("http://192.168.1.50/lineup.json").mock(return_value=httpx.Response(200, json=LINEUP))
    with httpx.Client() as client:
        result = fetch_lineup(client, "http://192.168.1.50")
    assert result is not None
    assert result.device.friendly_name == "HDHomeRun CONNECT"
    assert result.device.tuner_count == 2
    assert result.epg_url == "https://api.hdhomerun.com/api/xmltv?DeviceAuth=abc123"
    assert [(c.number, c.name, c.hd) for c in result.channels] == [
        (5, "NBC", True),
        (7, "ABC HD", False),
    ]


@respx.mock
def test_collect_lineups_uses_configured_urls_only() -> None:
    respx.get("http://10.0.0.9/discover.json").mock(return_value=httpx.Response(200, json=DISCOVER))
    respx.get("http://192.168.1.50/lineup.json").mock(return_value=httpx.Response(200, json=LINEUP))
    lineups = collect_lineups(["http://10.0.0.9"], discover=False)
    assert len(lineups) == 1
    assert len(lineups[0].channels) == 2
