from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from app.config import get_settings
from app.main import create_app
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def spa_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>tvtimes</title>")
    (static / "assets" / "app.js").write_text("console.log('hi')")
    (static / "favicon.svg").write_text("<svg/>")
    monkeypatch.setenv("TVTIMES_STATIC_DIR", str(static))
    get_settings.cache_clear()

    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_root_serves_index(spa_client: AsyncClient) -> None:
    r = await spa_client.get("/")
    assert r.status_code == 200
    assert "tvtimes" in r.text


async def test_client_route_falls_back_to_index(spa_client: AsyncClient) -> None:
    r = await spa_client.get("/guide/today")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text


async def test_real_asset_is_served(spa_client: AsyncClient) -> None:
    r = await spa_client.get("/favicon.svg")
    assert r.status_code == 200
    assert r.text == "<svg/>"
    r = await spa_client.get("/assets/app.js")
    assert r.status_code == 200


async def test_unknown_api_path_is_404_not_index(spa_client: AsyncClient) -> None:
    r = await spa_client.get("/api/nope")
    assert r.status_code == 404
    assert "<!doctype html>" not in r.text


async def test_no_path_traversal(spa_client: AsyncClient) -> None:
    r = await spa_client.get("/../../etc/passwd")
    # normalised by the client/route; must never leak a file outside the root
    assert "root:" not in r.text
