from __future__ import annotations

import pytest
from app.ingest import ssrf
from app.ingest.errors import SourceRejected


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
        "http://[::1]/x",
        "http://100.64.0.1/x",  # CGNAT
        "http://0.0.0.0/x",
    ],
)
async def test_rejects_non_public_literals(url: str) -> None:
    with pytest.raises(SourceRejected):
        await ssrf.assert_allowed_url(url)


@pytest.mark.parametrize("url", ["ftp://host/x", "file:///etc/passwd", "gopher://h", "//h/x"])
async def test_rejects_bad_schemes(url: str) -> None:
    with pytest.raises(SourceRejected):
        await ssrf.assert_allowed_url(url)


async def test_allows_public_literal() -> None:
    await ssrf.assert_allowed_url("https://93.184.216.34/")  # no raise


async def test_hostname_resolving_to_private_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["93.184.216.34", "10.1.2.3"]

    monkeypatch.setattr(ssrf, "_resolve", fake_resolve)
    with pytest.raises(SourceRejected):
        await ssrf.assert_allowed_url("http://sneaky.example.com/x")


async def test_hostname_resolving_to_public_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(ssrf, "_resolve", fake_resolve)
    await ssrf.assert_allowed_url("http://ok.example.com/x")  # no raise


async def test_allowlist_bypasses_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(_host: str) -> list[str]:
        raise AssertionError("should not resolve an allow-listed host")

    monkeypatch.setattr(ssrf, "_resolve", boom)
    await ssrf.assert_allowed_url("http://internal.test/x", allowlist=["internal.test"])
