"""End-to-end passkey registration + login using a software authenticator."""

from __future__ import annotations

import json
from typing import Any

from httpx import AsyncClient
from soft_webauthn import SoftWebauthnDevice
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from tests.conftest import auth_header, login, register_and_verify

ORIGIN = "http://localhost:5173"


def _options_with_bytes(options_json: str) -> dict[str, Any]:
    """py_webauthn emits base64url strings; a real navigator.credentials call
    hands the authenticator ArrayBuffers. Convert back for soft-webauthn."""
    pk: dict[str, Any] = json.loads(options_json)
    pk["challenge"] = base64url_to_bytes(pk["challenge"])
    if isinstance(pk.get("user"), dict) and "id" in pk["user"]:
        pk["user"]["id"] = base64url_to_bytes(pk["user"]["id"])
    for key in ("allowCredentials", "excludeCredentials"):
        for entry in pk.get(key) or []:
            entry["id"] = base64url_to_bytes(entry["id"])
    return {"publicKey": pk}


def _encode_registration(pkc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": bytes_to_base64url(pkc["rawId"]),
        "rawId": bytes_to_base64url(pkc["rawId"]),
        "type": pkc["type"],
        "clientExtensionResults": pkc.get("clientExtensionResults", {}),
        "response": {
            "clientDataJSON": bytes_to_base64url(pkc["response"]["clientDataJSON"]),
            "attestationObject": bytes_to_base64url(pkc["response"]["attestationObject"]),
        },
    }


def _encode_assertion(pkc: dict[str, Any]) -> dict[str, Any]:
    user_handle = pkc["response"].get("userHandle")
    return {
        "id": bytes_to_base64url(pkc["rawId"]),
        "rawId": bytes_to_base64url(pkc["rawId"]),
        "type": pkc["type"],
        "clientExtensionResults": pkc.get("clientExtensionResults", {}),
        "response": {
            "clientDataJSON": bytes_to_base64url(pkc["response"]["clientDataJSON"]),
            "authenticatorData": bytes_to_base64url(pkc["response"]["authenticatorData"]),
            "signature": bytes_to_base64url(pkc["response"]["signature"]),
            "userHandle": bytes_to_base64url(user_handle) if user_handle else None,
        },
    }


async def _register_passkey(client: AsyncClient, access_token: str) -> SoftWebauthnDevice:
    device = SoftWebauthnDevice()
    opts = await client.post("/api/account/passkeys/options", headers=auth_header(access_token))
    assert opts.status_code == 200
    attestation = device.create(_options_with_bytes(opts.json()["options"]), ORIGIN)
    resp = await client.post(
        "/api/account/passkeys",
        json={"credential": _encode_registration(attestation), "nickname": "YubiKey"},
        headers=auth_header(access_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["nickname"] == "YubiKey"
    return device


async def test_register_and_login_with_passkey(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    token = await login(app_client)
    device = await _register_passkey(app_client, token)

    listed = await app_client.get("/api/account/passkeys", headers=auth_header(token))
    assert len(listed.json()) == 1

    # Now authenticate from a clean client with no password.
    opts = await app_client.post(
        "/api/auth/webauthn/login/options", json={"email": "sam@example.com"}
    )
    assert opts.status_code == 200
    assertion = device.get(_options_with_bytes(opts.json()["options"]), ORIGIN)

    resp = await app_client.post(
        "/api/auth/webauthn/login/verify", json={"credential": _encode_assertion(assertion)}
    )
    assert resp.status_code == 200, resp.text
    assert "tvtimes_refresh" in resp.cookies


async def test_passkey_login_rejects_unknown_credential(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    await login(app_client)

    stranger = SoftWebauthnDevice()
    stranger.cred_init("localhost", b"sam")
    opts = await app_client.post("/api/auth/webauthn/login/options", json={})
    assertion = stranger.get(_options_with_bytes(opts.json()["options"]), ORIGIN)
    resp = await app_client.post(
        "/api/auth/webauthn/login/verify", json={"credential": _encode_assertion(assertion)}
    )
    assert resp.status_code == 401


async def test_passkey_registration_requires_verified_email(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    from app.db import get_sessionmaker
    from app.models.user import User
    from sqlalchemy import update

    # Register + verify + login to obtain an access token, then revoke
    # verification directly so the request carries an unverified session.
    await register_and_verify(app_client, captured_emails)
    token = await login(app_client)
    async with get_sessionmaker()() as s:
        await s.execute(
            update(User).where(User.email == "sam@example.com").values(email_verified_at=None)
        )
        await s.commit()

    resp = await app_client.post("/api/account/passkeys/options", headers=auth_header(token))
    assert resp.status_code == 403


async def test_delete_passkey(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    token = await login(app_client)
    await _register_passkey(app_client, token)
    listed = await app_client.get("/api/account/passkeys", headers=auth_header(token))
    passkey_id = listed.json()[0]["id"]

    resp = await app_client.request(
        "DELETE", f"/api/account/passkeys/{passkey_id}", headers=auth_header(token)
    )
    assert resp.status_code == 200
    listed = await app_client.get("/api/account/passkeys", headers=auth_header(token))
    assert listed.json() == []
