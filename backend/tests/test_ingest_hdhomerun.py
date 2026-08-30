from __future__ import annotations

import struct
import zlib

import pytest
import respx
from app.ingest import hdhomerun
from app.ingest.errors import SourceInvalid, SourceRejected, SourceUnreachable
from httpx import Response

_DISCOVER = {
    "FriendlyName": "HDHomeRun CONNECT",
    "ModelNumber": "HDHR5-2US",
    "DeviceID": "10ABCDEF",
    "DeviceAuth": "s3cr3tauth",
    "TunerCount": 2,
    "LineupURL": "http://192.168.1.50/lineup.json",
}
_LINEUP = [
    {"GuideNumber": "2.1", "GuideName": "BBC One", "HD": 1, "URL": "http://192.168.1.50/auto/v2.1"},
    {"GuideNumber": "3.1", "GuideName": "ITV1", "URL": "http://192.168.1.50/auto/v3.1"},
    {"GuideNumber": "4.1", "GuideName": "ignored, no url"},
]


@respx.mock
async def test_load_playlist_happy_path() -> None:
    respx.get("http://192.168.1.50/discover.json").mock(return_value=Response(200, json=_DISCOVER))
    respx.get("http://192.168.1.50/lineup.json").mock(return_value=Response(200, json=_LINEUP))

    playlist = await hdhomerun.load_hdhomerun_playlist({"device_url": "http://192.168.1.50"})

    assert playlist.epg_url == "https://api.hdhomerun.com/api/xmltv?DeviceAuth=s3cr3tauth"
    assert [(c.name, c.stream_ref, c.tvg_id) for c in playlist.channels] == [
        ("BBC One HD", "http://192.168.1.50/auto/v2.1", "2.1"),
        ("ITV1", "http://192.168.1.50/auto/v3.1", "3.1"),
    ]
    assert playlist.channels[0].number == 2


@respx.mock
async def test_relative_lineup_url_is_resolved_against_device() -> None:
    disc = {**_DISCOVER, "LineupURL": "lineup.json"}
    respx.get("http://192.168.1.50/discover.json").mock(return_value=Response(200, json=disc))
    respx.get("http://192.168.1.50/lineup.json").mock(return_value=Response(200, json=_LINEUP))

    playlist = await hdhomerun.load_hdhomerun_playlist({"device_url": "http://192.168.1.50"})
    assert len(playlist.channels) == 2


@respx.mock
async def test_empty_lineup_is_invalid() -> None:
    respx.get("http://192.168.1.50/discover.json").mock(return_value=Response(200, json=_DISCOVER))
    respx.get("http://192.168.1.50/lineup.json").mock(return_value=Response(200, json=[]))

    with pytest.raises(SourceInvalid):
        await hdhomerun.load_hdhomerun_playlist({"device_url": "http://192.168.1.50"})


@respx.mock
async def test_not_an_hdhomerun_is_invalid() -> None:
    respx.get("http://192.168.1.50/discover.json").mock(return_value=Response(200, json={"x": 1}))
    with pytest.raises(SourceInvalid):
        await hdhomerun.load_hdhomerun_playlist({"device_url": "http://192.168.1.50"})


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/",
        "https://example.com/",
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "ftp://192.168.1.50/",
    ],
)
async def test_rejects_non_lan_device_url(url: str) -> None:
    with pytest.raises(SourceRejected):
        await hdhomerun.load_hdhomerun_playlist({"device_url": url})


async def test_no_device_and_no_discovery_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(timeout: float = 2.0) -> list[str]:
        return []

    monkeypatch.setattr(hdhomerun, "discover_device_urls", _none)
    with pytest.raises(SourceUnreachable):
        await hdhomerun.load_hdhomerun_playlist({"device_url": ""})


def test_discovery_frame_round_trips() -> None:
    frame = hdhomerun.build_discovery_request()
    body, crc = frame[:-4], struct.unpack("<I", frame[-4:])[0]
    assert crc == zlib.crc32(body) & 0xFFFFFFFF

    # A synthetic reply carrying only a BaseURL TLV.
    base = b"http://192.168.1.50:80"
    payload = struct.pack(">BB", hdhomerun._TAG_BASE_URL, len(base)) + base
    reply = struct.pack(">HH", hdhomerun._TYPE_DISCOVER_RPY, len(payload)) + payload
    assert hdhomerun.parse_discovery_reply(reply) == "http://192.168.1.50:80"
    assert hdhomerun.parse_discovery_reply(b"\x00\x03") is None
