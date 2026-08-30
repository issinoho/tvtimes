"""Shared test fixtures.

Tests run against an in-memory SQLite database with the full schema created
from ``Base.metadata``. Postgres-only column types are avoided in models or
guarded so the suite stays runnable without a database server.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

os.environ.setdefault("TVTIMES_ENV", "test")
os.environ.setdefault("TVTIMES_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("TVTIMES_LOG_LEVEL", "WARNING")

from app.config import get_settings
from app.db import Base, dispose_engine, get_engine
from app.main import create_app
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        await dispose_engine()
