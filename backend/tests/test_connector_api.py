from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, login, register_and_verify

LINEUP: dict[str, Any] = {
    "device_id": "10501234",
    "friendly_name": "HDHomeRun CONNECT",
    "model": "HDHR5-2US",
    "tuner_count": 2,
    "epg_url": "https://api.hdhomerun.com/api/xmltv?DeviceAuth=abc",
    "channels": [
        {"number": 5, "name": "NBC HD", "stream_url": "http://192.168.1.50/auto/v5", "hd": True},
        {"number": 7, "name": "ABC", "stream_url": "http://192.168.1.50/auto/v7"},
    ],
}


@pytest.fixture(autouse=True)
def _no_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a: object) -> None:
        return None

    monkeypatch.setattr("app.api.routers.sources.enqueue_source_refresh", _noop)
    monkeypatch.setattr("app.api.routers.epg.enqueue_epg_refresh", _noop)


async def _auth(client: AsyncClient, emails: list[dict[str, str]], email: str) -> dict[str, str]:
    await register_and_verify(client, emails, email=email)
    return auth_header(await login(client, email=email))


async def test_pair_heartbeat_lineup_flow(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")

    created = await app_client.post("/api/connectors", json={"name": "Home"}, headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "unpaired"
    code = body["pairing_code"]
    assert "tvtimes-connector pair" in body["install_hint"]

    # Pair (no auth) -> token.
    paired = await app_client.post("/api/connector/pair", json={"code": code})
    assert paired.status_code == 200
    token = paired.json()["token"]
    conn_headers = {"Authorization": f"Bearer {token}"}

    # The code no longer works.
    assert (await app_client.post("/api/connector/pair", json={"code": code})).status_code == 400

    hb = await app_client.post(
        "/api/connector/heartbeat", json={"version": "0.1.0"}, headers=conn_headers
    )
    assert hb.status_code == 200

    lineup = await app_client.post("/api/connector/lineup", json=LINEUP, headers=conn_headers)
    assert lineup.status_code == 200
    assert lineup.json()["channels"] == 2

    # It shows up as a connector source with channels + the EPG URL.
    sources = await app_client.get("/api/sources", headers=headers)
    connector_source = next(s for s in sources.json() if s["kind"] == "connector")
    assert connector_source["channel_count"] == 2
    assert connector_source["epg_url"].startswith("https://api.hdhomerun.com")

    channels = await app_client.get(
        f"/api/sources/{connector_source['id']}/channels", headers=headers
    )
    assert {c["name"] for c in channels.json()["items"]} == {"NBC HD", "ABC"}

    # The connector now reads as online, with its device summary.
    listed = await app_client.get("/api/connectors", headers=headers)
    row = listed.json()[0]
    assert row["status"] == "online"
    assert row["version"] == "0.1.0"
    assert row["devices"][0]["device_id"] == "10501234"
    assert row["source_id"] == connector_source["id"]


async def test_lineup_replaces_channels_on_resubmit(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    code = (await app_client.post("/api/connectors", json={"name": "H"}, headers=headers)).json()[
        "pairing_code"
    ]
    token = (await app_client.post("/api/connector/pair", json={"code": code})).json()["token"]
    ch = {"Authorization": f"Bearer {token}"}

    await app_client.post("/api/connector/lineup", json=LINEUP, headers=ch)
    smaller = {**LINEUP, "channels": LINEUP["channels"][:1]}
    await app_client.post("/api/connector/lineup", json=smaller, headers=ch)

    sources = await app_client.get("/api/sources", headers=headers)
    connector_source = next(s for s in sources.json() if s["kind"] == "connector")
    assert connector_source["channel_count"] == 1


async def test_bad_and_expired_pairing_codes(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    headers = await _auth(app_client, captured_emails, "sam@example.com")
    connector_id = (
        await app_client.post("/api/connectors", json={"name": "H"}, headers=headers)
    ).json()["id"]

    assert (
        await app_client.post("/api/connector/pair", json={"code": "NOPENOPE"})
    ).status_code == 400

    # Force-expire, then pairing fails.
    from datetime import UTC, datetime, timedelta

    from app.db import get_sessionmaker
    from app.models.connector import Connector

    async with get_sessionmaker()() as session:
        c = await session.get(Connector, uuid.UUID(connector_id))
        assert c is not None
        real_code = c.pairing_code
        c.pairing_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    assert (
        await app_client.post("/api/connector/pair", json={"code": real_code})
    ).status_code == 400


async def test_connector_token_required_and_tenant_isolated(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    a_headers = await _auth(app_client, captured_emails, "a@example.com")
    connector_id = (
        await app_client.post("/api/connectors", json={"name": "H"}, headers=a_headers)
    ).json()["id"]

    assert (await app_client.post("/api/connector/heartbeat", json={})).status_code == 401
    assert (
        await app_client.post(
            "/api/connector/heartbeat", json={}, headers={"Authorization": "Bearer nope"}
        )
    ).status_code == 401

    b_headers = await _auth(app_client, captured_emails, "b@example.com")
    assert (
        await app_client.request("DELETE", f"/api/connectors/{connector_id}", headers=b_headers)
    ).status_code == 404
    assert (await app_client.get("/api/connectors", headers=b_headers)).json() == []
