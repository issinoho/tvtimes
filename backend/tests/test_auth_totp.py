from __future__ import annotations

import pyotp
from httpx import AsyncClient

from tests.conftest import (
    DEFAULT_PASSWORD,
    auth_header,
    login,
    register_and_verify,
)


async def _enrol_totp(client: AsyncClient, access_token: str) -> tuple[str, list[str]]:
    begin = await client.post("/api/account/totp", headers=auth_header(access_token))
    assert begin.status_code == 200
    secret = begin.json()["secret"]
    code = pyotp.TOTP(secret).now()
    confirm = await client.post(
        "/api/account/totp/confirm", json={"code": code}, headers=auth_header(access_token)
    )
    assert confirm.status_code == 200
    return secret, confirm.json()["recovery_codes"]


async def test_totp_enrolment_then_login_requires_second_factor(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    token = await login(app_client)
    secret, recovery = await _enrol_totp(app_client, token)
    assert len(recovery) == 10

    # Fresh password login now stops at the MFA step.
    resp = await app_client.post(
        "/api/auth/login", json={"email": "sam@example.com", "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "mfa_required"
    mfa_token = resp.json()["mfa_token"]

    done = await app_client.post(
        "/api/auth/login/mfa",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert done.status_code == 200
    assert "tvtimes_refresh" in done.cookies


async def test_recovery_code_completes_mfa_and_is_single_use(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    token = await login(app_client)
    _secret, recovery = await _enrol_totp(app_client, token)
    code = recovery[0]

    resp = await app_client.post(
        "/api/auth/login", json={"email": "sam@example.com", "password": DEFAULT_PASSWORD}
    )
    mfa_token = resp.json()["mfa_token"]
    ok = await app_client.post("/api/auth/login/mfa", json={"mfa_token": mfa_token, "code": code})
    assert ok.status_code == 200

    # Same recovery code cannot be reused.
    resp = await app_client.post(
        "/api/auth/login", json={"email": "sam@example.com", "password": DEFAULT_PASSWORD}
    )
    mfa_token = resp.json()["mfa_token"]
    reused = await app_client.post(
        "/api/auth/login/mfa", json={"mfa_token": mfa_token, "code": code}
    )
    assert reused.status_code == 401


async def test_wrong_totp_code_is_rejected(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    token = await login(app_client)
    await _enrol_totp(app_client, token)
    resp = await app_client.post(
        "/api/auth/login", json={"email": "sam@example.com", "password": DEFAULT_PASSWORD}
    )
    mfa_token = resp.json()["mfa_token"]
    bad = await app_client.post(
        "/api/auth/login/mfa", json={"mfa_token": mfa_token, "code": "000000"}
    )
    assert bad.status_code == 401


async def test_me_reports_totp_enabled(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    token = await login(app_client)
    before = await app_client.get("/api/account/me", headers=auth_header(token))
    assert before.json()["totp_enabled"] is False
    await _enrol_totp(app_client, token)
    after = await app_client.get("/api/account/me", headers=auth_header(token))
    assert after.json()["totp_enabled"] is True
