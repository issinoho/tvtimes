"""Find-and-approve pairing (app.services.devices / app.api.routers.devices)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.db import get_sessionmaker
from app.models.device import PairedDevice
from app.services import devices as svc
from httpx import AsyncClient
from sqlalchemy import update

from tests.conftest import auth_header, login, register_and_verify


async def _auth(client: AsyncClient, emails: list[dict[str, str]], email: str) -> dict[str, str]:
    await register_and_verify(client, emails, email=email)
    return auth_header(await login(client, email=email))


async def _start(client: AsyncClient, name: str = "Living room Fire TV") -> dict[str, object]:
    r = await client.post("/api/pairing/start", json={"name": name})
    assert r.status_code == 200
    body: dict[str, object] = r.json()
    return body


async def test_health_says_it_is_tvtimes_and_can_pair(app_client: AsyncClient) -> None:
    body = (await app_client.get("/api/healthz")).json()
    assert body["app"] == "tvtimes"
    assert body["pairing"] is True


async def test_pair_approve_collect_and_read_exports(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    started = await _start(app_client)
    code, secret = str(started["code"]), str(started["poll_secret"])
    assert len(code) == svc.CODE_LENGTH
    assert started["interval"] == svc.POLL_INTERVAL_S

    # Waiting for approval.
    polled = await app_client.post("/api/pairing/poll", json={"poll_secret": secret})
    assert polled.json() == {"status": "pending", "token": None, "origin": None}

    # Typed the way a person might: lower case, a space in the middle.
    typed = f"{code[:4].lower()} {code[4:]}"
    approved = await app_client.post("/api/devices", json={"code": typed}, headers=headers)
    assert approved.status_code == 200
    assert approved.json()["name"] == "Living room Fire TV"
    assert approved.json()["paired"] is False

    # The code is spent.
    again = await app_client.post("/api/devices", json={"code": code}, headers=headers)
    assert again.status_code == 400

    collected = (await app_client.post("/api/pairing/poll", json={"poll_secret": secret})).json()
    assert collected["status"] == "approved"
    token = collected["token"]
    assert token
    assert collected["origin"]

    # Collected exactly once.
    gone = await app_client.post("/api/pairing/poll", json={"poll_secret": secret})
    assert gone.status_code == 404

    # The device's own token reads the feeds.
    feed = await app_client.get("/api/exports/favourites.json", params={"token": token})
    assert feed.status_code == 200

    listed = (await app_client.get("/api/devices", headers=headers)).json()
    assert len(listed) == 1
    assert listed[0]["paired"] is True
    assert listed[0]["last_used_at"] is not None

    # Removing it revokes the token at once.
    removed = await app_client.delete(f"/api/devices/{listed[0]['id']}", headers=headers)
    assert removed.status_code == 200
    denied = await app_client.get("/api/exports/favourites.json", params={"token": token})
    assert denied.status_code == 401


async def test_device_token_is_independent_of_the_account_token(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "kim@example.com")
    started = await _start(app_client)
    await app_client.post("/api/devices", json={"code": started["code"]}, headers=headers)
    token = (
        await app_client.post("/api/pairing/poll", json={"poll_secret": started["poll_secret"]})
    ).json()["token"]
    # Disabling the account's own export token leaves paired devices alone.
    await app_client.delete("/api/account/export-token", headers=headers)
    feed = await app_client.get("/api/exports/favourites.json", params={"token": token})
    assert feed.status_code == 200


async def test_another_account_cannot_remove_a_device(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    owner = await _auth(app_client, captured_emails, "owner@example.com")
    other = await _auth(app_client, captured_emails, "other@example.com")
    started = await _start(app_client)
    device = (
        await app_client.post("/api/devices", json={"code": started["code"]}, headers=owner)
    ).json()
    removed = await app_client.delete(f"/api/devices/{device['id']}", headers=other)
    assert removed.status_code == 404
    assert (await app_client.get("/api/devices", headers=other)).json() == []


async def test_expired_code_cannot_be_approved_and_is_swept(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "lee@example.com")
    started = await _start(app_client)
    async with get_sessionmaker()() as session:
        await session.execute(
            update(PairedDevice).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    r = await app_client.post("/api/devices", json={"code": started["code"]}, headers=headers)
    assert r.status_code == 400
    polled = await app_client.post(
        "/api/pairing/poll", json={"poll_secret": started["poll_secret"]}
    )
    assert polled.status_code == 404


async def test_unknown_poll_secret_is_404(app_client: AsyncClient) -> None:
    r = await app_client.post("/api/pairing/poll", json={"poll_secret": "nope"})
    assert r.status_code == 404


async def test_pending_requests_are_capped(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "MAX_PENDING", 2)
    await _start(app_client)
    await _start(app_client)
    r = await app_client.post("/api/pairing/start", json={"name": "third"})
    assert r.status_code == 429


def test_codes_avoid_lookalike_characters() -> None:
    for ch in "01ILOU":
        assert ch not in svc.CODE_ALPHABET
    assert svc.normalise_code(" ab-cd 23 ") == "ABCD23"
