"""Shared test fixtures.

Tests run against an in-memory SQLite database with the full schema created
from ``Base.metadata``. Postgres-only column types are avoided in models so the
suite stays runnable without a database server.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator

import pytest

os.environ.setdefault("TVTIMES_ENV", "test")
os.environ.setdefault("TVTIMES_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("TVTIMES_LOG_LEVEL", "WARNING")
os.environ.setdefault("TVTIMES_RATELIMIT_ENABLED", "false")
os.environ.setdefault("TVTIMES_ENCRYPTION_KEY", "test-key-not-secret-but-stable")
os.environ.setdefault("TVTIMES_PUBLIC_ORIGIN", "http://localhost:5173")
os.environ.setdefault("TVTIMES_WEBAUTHN_RP_ID", "localhost")

from app.config import get_settings
from app.db import Base, dispose_engine, get_engine
from app.main import create_app
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_breach_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never call the Pwned Passwords API from the test suite."""

    async def _never_breached(_password: str) -> bool:
        return False

    monkeypatch.setattr("app.auth.passwords._is_breached", _never_breached)


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


@pytest.fixture
def captured_emails(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Capture outgoing emails so tests can pull verification / reset links."""
    outbox: list[dict[str, str]] = []

    async def _fake_send(*, to: str, subject: str, body_text: str) -> None:
        outbox.append({"to": to, "subject": subject, "body": body_text})

    monkeypatch.setattr("app.auth.service.send_email", _fake_send)
    return outbox


def token_from_link(body: str) -> str:
    """Extract the ``token=`` query value from a verification / reset email body."""
    m = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", body)
    assert m, f"no token in email body: {body!r}"
    return m.group(1)


DEFAULT_PASSWORD = "correct horse battery"


async def register_and_verify(
    client: AsyncClient,
    outbox: list[dict[str, str]],
    *,
    email: str = "sam@example.com",
    password: str | None = DEFAULT_PASSWORD,
    display_name: str = "Sam",
) -> None:
    body: dict[str, object] = {"email": email, "display_name": display_name}
    if password is not None:
        body["password"] = password
    resp = await client.post("/api/auth/register", json=body)
    assert resp.status_code == 202, resp.text
    verify_mail = next(m for m in outbox if m["to"] == email and "confirm" in m["subject"])
    resp = await client.post(
        "/api/auth/verify", json={"token": token_from_link(verify_mail["body"])}
    )
    assert resp.status_code == 200, resp.text


async def login(
    client: AsyncClient,
    *,
    email: str = "sam@example.com",
    password: str = DEFAULT_PASSWORD,
) -> str:
    """Password login. Returns the access token; the refresh cookie is stored on
    the client."""
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def csrf_header(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["tvtimes_csrf"]}
