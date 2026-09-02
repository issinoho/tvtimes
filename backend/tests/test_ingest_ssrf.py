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
    with pytest.raises(SourceRejected) as excinfo:
        await ssrf.assert_allowed_url("http://sneaky.example.com/x")
    # the resolved private IP must not leak back to the caller (it would make
    # "add source" an internal DNS-resolution oracle) — #89
    assert "10.1.2.3" not in str(excinfo.value)


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


async def test_allowlist_accepts_a_lan_ip_and_cidr() -> None:
    await ssrf.assert_allowed_url(
        "http://192.168.0.218:5523/feeds/x.m3u", allowlist=["192.168.0.218"]
    )
    await ssrf.assert_allowed_url(
        "http://192.168.0.50/epg.xml", allowlist=["10.0.0.0/8", "192.168.0.0/24"]
    )


async def test_allowlisted_cidr_still_rejects_addresses_outside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["192.168.9.9"]  # not in 192.168.0.0/24

    monkeypatch.setattr(ssrf, "_resolve", fake_resolve)
    with pytest.raises(SourceRejected):
        await ssrf.assert_allowed_url("http://nas.lan/x", allowlist=["192.168.0.0/24"])


# --- resolve_allowed contract + connection pinning (DNS-rebinding defence) ---


async def test_resolve_allowed_returns_none_for_an_allowlisted_hostname() -> None:
    assert await ssrf.resolve_allowed("http://nas.lan/x", allowlist=["nas.lan"]) is None


async def test_resolve_allowed_returns_the_checked_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(_host: str) -> list[str]:
        return ["93.184.216.34", "93.184.216.35"]

    monkeypatch.setattr(ssrf, "_resolve", fake_resolve)
    assert await ssrf.resolve_allowed("https://ok.example.com/x") == [
        "93.184.216.34",
        "93.184.216.35",
    ]


async def test_resolve_allowed_returns_a_public_ip_literal() -> None:
    assert await ssrf.resolve_allowed("https://93.184.216.34/") == ["93.184.216.34"]


async def test_pinned_backend_connects_to_the_pinned_ip_not_the_hostname() -> None:
    """The core rebinding defence: httpcore hands the backend the URL's
    hostname; the backend must connect to the IP we already validated."""
    seen: list[tuple[str, int]] = []

    class _FakeInner:
        async def connect_tcp(self, host: str, port: int, **_kw: object) -> str:
            seen.append((host, port))
            return "stream"

        async def sleep(self, _s: float) -> None: ...  # delegated attr, unused here

    backend = ssrf._PinnedBackend(_FakeInner())

    token = ssrf._pin_ctx.set("93.184.216.34")
    try:
        assert await backend.connect_tcp("rebind.evil.example", 443) == "stream"
    finally:
        ssrf._pin_ctx.reset(token)
    assert seen == [("93.184.216.34", 443)]  # not the (re-resolvable) hostname


async def test_pinned_backend_passes_through_when_unpinned() -> None:
    seen: list[str] = []

    class _FakeInner:
        async def connect_tcp(self, host: str, _port: int, **_kw: object) -> None:
            seen.append(host)

    await ssrf._PinnedBackend(_FakeInner()).connect_tcp("host.example", 80)
    assert seen == ["host.example"]
