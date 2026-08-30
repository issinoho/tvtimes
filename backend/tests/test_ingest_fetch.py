from __future__ import annotations

import httpx
import pytest
import respx
from app.ingest import ssrf
from app.ingest.errors import SourceInvalid, SourceRejected, SourceUnreachable

ALLOW = ["feed.test", "evil.test", "panel.test"]


@respx.mock
async def test_fetch_text_happy_path() -> None:
    respx.get("http://feed.test/list.m3u").mock(
        return_value=httpx.Response(200, text="#EXTM3U\n#EXTINF:-1,One\nhttp://s/1\n")
    )
    text = await ssrf.fetch_text("http://feed.test/list.m3u", allowlist=ALLOW, m3u_sniff=True)
    assert text.startswith("#EXTM3U")


@respx.mock
async def test_fetch_text_m3u_sniff_rejects_html() -> None:
    respx.get("http://feed.test/nope").mock(
        return_value=httpx.Response(200, text="<html>not a playlist</html>")
    )
    with pytest.raises(SourceInvalid):
        await ssrf.fetch_text("http://feed.test/nope", allowlist=ALLOW, m3u_sniff=True)


@respx.mock
async def test_fetch_text_size_cap() -> None:
    respx.get("http://feed.test/big").mock(
        return_value=httpx.Response(200, text="#EXTM3U\n" + "x" * 5000)
    )
    with pytest.raises(SourceRejected):
        await ssrf.fetch_text(
            "http://feed.test/big", allowlist=ALLOW, m3u_sniff=True, max_bytes=1024
        )


@respx.mock
async def test_fetch_text_redirect_to_blocked_host_is_rejected() -> None:
    respx.get("http://feed.test/go").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )
    with pytest.raises(SourceRejected):
        await ssrf.fetch_text("http://feed.test/go", allowlist=ALLOW)


@respx.mock
async def test_fetch_text_http_error() -> None:
    respx.get("http://feed.test/500").mock(return_value=httpx.Response(503))
    with pytest.raises(SourceUnreachable):
        await ssrf.fetch_text("http://feed.test/500", allowlist=ALLOW)


@respx.mock
async def test_fetch_json_parses_body() -> None:
    respx.get("http://panel.test/player_api.php").mock(
        return_value=httpx.Response(200, json={"user_info": {"auth": 1}})
    )
    body = await ssrf.fetch_json("http://panel.test/player_api.php", allowlist=ALLOW)
    assert body["user_info"]["auth"] == 1
