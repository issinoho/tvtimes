from __future__ import annotations

from app import __version__
from httpx import AsyncClient


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
