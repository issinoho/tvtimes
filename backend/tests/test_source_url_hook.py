"""Remote URL updates: a per-source token lets another system push a new
playlist / server / portal URL to ``POST /api/hooks/source-url``."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

HOOK = "/api/hooks/source-url"
M3U = {"kind": "m3u", "display_name": "Pluto", "url": "http://feed.example.com/old.m3u"}
XTREAM = {
    "kind": "xtream",
    "display_name": "Panel",
    "server_url": "http://panel.example.com:8080",
    "username": "alice",
    "password": "s3cret",
}


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    calls: list[uuid.UUID] = []

    async def _record(source_id: uuid.UUID, **_: object) -> None:
        calls.append(source_id)

    monkeypatch.setattr("app.api.routers.sources.enqueue_source_refresh", _record)
    monkeypatch.setattr("app.api.routers.hooks.enqueue_source_refresh", _record)
    return calls


async def _headers(client: AsyncClient, emails: list[dict[str, str]]) -> dict[str, str]:
    await register_and_verify(client, emails)
    return auth_header(await login(client))


async def _config(source_id: str) -> dict[str, object]:
    from app.db import get_sessionmaker
    from app.models.source import Source
    from app.services import sources as svc

    async with get_sessionmaker()() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source is not None
        return svc.decrypt_config(source)


async def _source_with_token(
    client: AsyncClient, headers: dict[str, str], body: dict[str, str] = M3U
) -> tuple[str, str]:
    sid = (await client.post("/api/sources", json=body, headers=headers)).json()["id"]
    resp = await client.post(f"/api/sources/{sid}/update-token", headers=headers)
    assert resp.status_code == 201, resp.text
    return sid, resp.json()["token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_push_changes_the_url_and_queues_a_refresh(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    sid, token = await _source_with_token(app_client, headers)
    enqueued.clear()

    new = "http://feed.example.com/new.m3u?sig=abc123"
    resp = await app_client.post(HOOK, json={"url": new}, headers=_bearer(token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"source_id": sid, "changed": True}
    assert await _config(sid) == {"url": new}
    assert enqueued == [uuid.UUID(sid)]

    got = (await app_client.get(f"/api/sources/{sid}", headers=headers)).json()
    assert got["last_status"] == "pending"
    assert got["url_updates_supported"] is True
    assert got["update_token_set_at"] is not None
    assert got["update_token_last_used_at"] is not None


async def test_pushing_the_same_url_is_a_no_op(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    _sid, token = await _source_with_token(app_client, headers)
    enqueued.clear()

    resp = await app_client.post(HOOK, json={"url": M3U["url"]}, headers=_bearer(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["changed"] is False
    assert enqueued == []


async def test_xtream_push_replaces_only_the_server_url(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    sid, token = await _source_with_token(app_client, headers, XTREAM)

    resp = await app_client.post(
        HOOK, json={"url": "http://new-panel.example.com/"}, headers=_bearer(token)
    )
    assert resp.status_code == 200, resp.text
    assert await _config(sid) == {
        "server_url": "http://new-panel.example.com",
        "username": "alice",
        "password": "s3cret",
        "output": "ts",
    }


async def test_private_url_is_rejected_and_nothing_changes(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    sid, token = await _source_with_token(app_client, headers)
    enqueued.clear()

    resp = await app_client.post(
        HOOK, json={"url": "http://169.254.169.254/latest/"}, headers=_bearer(token)
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "source_error"
    assert await _config(sid) == {"url": M3U["url"]}
    assert enqueued == []


async def test_missing_or_wrong_token_is_401(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    await _source_with_token(app_client, headers)

    assert (await app_client.post(HOOK, json={"url": "http://x.example.com/"})).status_code == 401
    resp = await app_client.post(
        HOOK, json={"url": "http://x.example.com/"}, headers=_bearer("not-a-token")
    )
    assert resp.status_code == 401
    # A user's session token is not an update token.
    resp = await app_client.post(HOOK, json={"url": "http://x.example.com/"}, headers=headers)
    assert resp.status_code == 401


async def test_token_only_reaches_its_own_source(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    sid_a, token_a = await _source_with_token(app_client, headers)
    sid_b, _ = await _source_with_token(app_client, headers, {**M3U, "display_name": "Other"})

    resp = await app_client.post(
        HOOK, json={"url": "http://feed.example.com/a.m3u"}, headers=_bearer(token_a)
    )
    assert resp.json()["source_id"] == sid_a
    assert await _config(sid_a) == {"url": "http://feed.example.com/a.m3u"}
    assert await _config(sid_b) == {"url": M3U["url"]}


async def test_rotating_and_revoking_kill_the_old_token(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    sid, old = await _source_with_token(app_client, headers)

    new = (await app_client.post(f"/api/sources/{sid}/update-token", headers=headers)).json()
    url = {"url": "http://feed.example.com/r.m3u"}
    assert (await app_client.post(HOOK, json=url, headers=_bearer(old))).status_code == 401
    assert (await app_client.post(HOOK, json=url, headers=_bearer(new["token"]))).status_code == 200

    resp = await app_client.delete(f"/api/sources/{sid}/update-token", headers=headers)
    assert resp.status_code == 200
    assert (await app_client.post(HOOK, json=url, headers=_bearer(new["token"]))).status_code == 401
    got = (await app_client.get(f"/api/sources/{sid}", headers=headers)).json()
    assert got["update_token_set_at"] is None


async def test_hdhomerun_cannot_get_an_update_token(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    headers = await _headers(app_client, captured_emails)
    body = {"kind": "hdhomerun", "display_name": "Tuner", "device_url": "http://192.168.1.50"}
    sid = (await app_client.post("/api/sources", json=body, headers=headers)).json()["id"]
    resp = await app_client.post(f"/api/sources/{sid}/update-token", headers=headers)
    assert resp.status_code == 422
    got = (await app_client.get(f"/api/sources/{sid}", headers=headers)).json()
    assert got["url_updates_supported"] is False


async def test_minting_and_pushing_are_audited_without_the_full_url(
    app_client: AsyncClient, captured_emails: list[dict[str, str]], enqueued: list[uuid.UUID]
) -> None:
    from app.db import get_sessionmaker
    from app.models.audit import AuditLog
    from sqlalchemy import select

    headers = await _headers(app_client, captured_emails)
    sid, token = await _source_with_token(app_client, headers)
    await app_client.post(
        HOOK, json={"url": "http://feed.example.com/n.m3u?sig=secret"}, headers=_bearer(token)
    )

    async with get_sessionmaker()() as session:
        rows = (
            await session.scalars(select(AuditLog).where(AuditLog.event.like("source.%")))
        ).all()
    by_event = {r.event: r.detail for r in rows}
    assert by_event["source.update_token_set"] == {"source_id": sid}
    assert by_event["source.url_pushed"] == {"source_id": sid, "host": "feed.example.com"}
