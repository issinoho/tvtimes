"""Every response carries the baseline security headers (CSP, anti-clickjacking,
nosniff, Referrer-Policy, COOP); /openapi.json is exempt from CSP only; HSTS is
prod-https-only."""

from __future__ import annotations

import pytest
from app.config import get_settings
from app.main import create_app
from httpx import ASGITransport, AsyncClient

_ALWAYS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "cross-origin-opener-policy": "same-origin",
}


async def _get(path: str) -> dict[str, str]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return dict((await client.get(path)).headers)


@pytest.mark.parametrize("path", ["/api/auth/login", "/some/spa/route", "/openapi.json"])
async def test_baseline_headers_on_every_response(path: str) -> None:
    headers = await _get(path)
    for name, value in _ALWAYS.items():
        assert headers.get(name) == value


async def test_csp_present_on_app_responses() -> None:
    csp = (await _get("/api/auth/login")).get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "img-src 'self' data: https://image.tmdb.org" in csp
    assert "'unsafe-eval'" not in csp


async def test_openapi_is_exempt_from_csp_only() -> None:
    headers = await _get("/openapi.json")
    assert "content-security-policy" not in headers
    assert headers.get("x-frame-options") == "DENY"


async def test_no_hsts_outside_prod_https() -> None:
    assert "strict-transport-security" not in await _get("/api/auth/login")


async def test_hsts_on_prod_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TVTIMES_ENV", "prod")
    monkeypatch.setenv("TVTIMES_PUBLIC_ORIGIN", "https://tv.example.com")
    monkeypatch.setenv(
        "TVTIMES_JWT_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----"
    )
    monkeypatch.setenv("TVTIMES_ENCRYPTION_KEY", "a-real-looking-key")
    get_settings.cache_clear()
    try:
        headers = await _get("/api/auth/login")
    finally:
        get_settings.cache_clear()
    assert "max-age=" in headers.get("strict-transport-security", "")
