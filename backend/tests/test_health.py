from __future__ import annotations

import pytest
from app import __version__
from app.config import get_settings
from app.main import create_app
from httpx import ASGITransport, AsyncClient


async def test_healthz(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "version": __version__}


async def test_readyz_reports_database_up(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["database"] is True


async def test_openapi_schema_served(app_client: AsyncClient) -> None:
    resp = await app_client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "tvtimes API"


async def test_docs_and_schema_are_off_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TVTIMES_ENV", "prod")
    monkeypatch.setenv("TVTIMES_PUBLIC_ORIGIN", "https://tv.example.com")
    monkeypatch.setenv(
        "TVTIMES_JWT_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----"
    )
    from cryptography.fernet import Fernet

    monkeypatch.setenv("TVTIMES_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/docs")).status_code == 404
            assert (await client.get("/redoc")).status_code == 404
            assert (await client.get("/openapi.json")).status_code == 404
    finally:
        get_settings.cache_clear()
