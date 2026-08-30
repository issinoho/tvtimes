from __future__ import annotations

import json

import pytest
import respx
from app.ingest import channel_logos
from httpx import Response

_CHANNELS = [
    {"id": "BBCOne.uk", "name": "BBC One", "alt_names": ["BBC 1"], "logo": "https://x/bbc1.png"},
    {
        "id": "TCM.us",
        "name": "Turner Classic Movies",
        "alt_names": ["TCM"],
        "logo": "https://x/tcm.png",
    },
    {"id": "NoLogo.us", "name": "No Logo", "logo": ""},
    "junk",
]


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    channel_logos._index = {}
    channel_logos._loaded_at = 0.0


@respx.mock
async def test_load_index_keys_by_id_name_and_alt_name() -> None:
    route = respx.get(channel_logos._SOURCE_URL).mock(
        return_value=Response(200, content=json.dumps(_CHANNELS).encode())
    )
    index = await channel_logos.load_index()

    assert index["bbcone.uk"] == "https://x/bbc1.png"
    assert index["bbc one"] == "https://x/bbc1.png"
    assert index["bbc 1"] == "https://x/bbc1.png"
    assert index["tcm"] == "https://x/tcm.png"
    assert "no logo" not in index  # empty logo string is skipped
    assert route.call_count == 1

    # Second call is served from the day-long cache.
    await channel_logos.load_index()
    assert route.call_count == 1


@respx.mock
async def test_lookup_prefers_id_then_name_then_tvg_name() -> None:
    respx.get(channel_logos._SOURCE_URL).mock(
        return_value=Response(200, content=json.dumps(_CHANNELS).encode())
    )
    index = await channel_logos.load_index()

    assert channel_logos.lookup(index, ext_id="TCM.us", name="whatever") == "https://x/tcm.png"
    assert channel_logos.lookup(index, ext_id=None, name="BBC One") == "https://x/bbc1.png"
    assert (
        channel_logos.lookup(index, ext_id="x", name="x", tvg_name="BBC 1") == "https://x/bbc1.png"
    )
    assert channel_logos.lookup(index, ext_id=None, name="Unknown Channel") is None


@respx.mock
async def test_fetch_failure_is_swallowed() -> None:
    respx.get(channel_logos._SOURCE_URL).mock(return_value=Response(503))
    assert await channel_logos.load_index() == {}
