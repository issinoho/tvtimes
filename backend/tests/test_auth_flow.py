from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import (
    DEFAULT_PASSWORD,
    auth_header,
    csrf_header,
    login,
    register_and_verify,
    token_from_link,
)


async def test_register_is_generic_and_sends_verification(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    resp = await app_client.post(
        "/api/auth/register",
        json={"email": "New@Example.com", "display_name": "New", "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 202
    assert "confirmation email" in resp.json()["message"]
    assert any("confirm" in m["subject"] for m in captured_emails)
    # email normalised to lower-case for delivery
    assert captured_emails[0]["to"] == "new@example.com"


async def test_register_stores_browser_timezone(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(
        app_client, captured_emails, email="tz@example.com", timezone="Europe/London"
    )
    headers = auth_header(await login(app_client, email="tz@example.com"))
    me = await app_client.get("/api/account/me", headers=headers)
    assert me.json()["default_timezone"] == "Europe/London"


async def test_register_falls_back_to_utc_for_unknown_timezone(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(
        app_client, captured_emails, email="badtz@example.com", timezone="Mars/Olympus_Mons"
    )
    headers = auth_header(await login(app_client, email="badtz@example.com"))
    me = await app_client.get("/api/account/me", headers=headers)
    assert me.json()["default_timezone"] == "UTC"


async def test_duplicate_register_does_not_leak_existence(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails, email="dup@example.com")
    captured_emails.clear()
    resp = await app_client.post(
        "/api/auth/register",
        json={"email": "dup@example.com", "display_name": "Dup", "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 202
    assert "already have an account" in captured_emails[0]["subject"]


async def test_login_requires_verified_email(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await app_client.post(
        "/api/auth/register",
        json={"email": "u@example.com", "display_name": "U", "password": DEFAULT_PASSWORD},
    )
    resp = await app_client.post(
        "/api/auth/login", json={"email": "u@example.com", "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "email_not_verified"


async def test_login_success_sets_cookies_and_returns_access_token(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    resp = await app_client.post(
        "/api/auth/login", json={"email": "sam@example.com", "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert "tvtimes_refresh" in resp.cookies
    assert "tvtimes_csrf" in resp.cookies

    # The CSRF cookie must be readable by the SPA on any route, so it is scoped
    # to "/", not the auth path — otherwise a page reload can't do the silent
    # token refresh and the user is bounced to login. The refresh token stays
    # narrowly scoped (only the server reads it).
    set_cookie_headers = [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]
    # The real CSRF cookie carries a value (an expiry-clearing header for the
    # legacy path may also be present).
    csrf_hdr = next(
        h
        for h in set_cookie_headers
        if h.startswith("tvtimes_csrf=") and not h.startswith('tvtimes_csrf=""')
    )
    refresh_hdr = next(h for h in set_cookie_headers if h.startswith("tvtimes_refresh="))
    assert "Path=/;" in f"{csrf_hdr};" and "Path=/api/auth" not in csrf_hdr
    assert "Path=/api/auth" in refresh_hdr
    assert "HttpOnly" in refresh_hdr and "HttpOnly" not in csrf_hdr

    token = resp.json()["access_token"]
    me = await app_client.get("/api/account/me", headers=auth_header(token))
    assert me.status_code == 200
    assert me.json()["email"] == "sam@example.com"
    assert me.json()["email_verified"] is True


async def test_login_wrong_password_and_unknown_email_are_indistinguishable(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    bad = await app_client.post(
        "/api/auth/login", json={"email": "sam@example.com", "password": "nope nope nope"}
    )
    unknown = await app_client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "nope nope nope"}
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["code"] == unknown.json()["code"] == "invalid_credentials"


async def test_account_lockout_after_repeated_failures(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    for _ in range(5):
        await app_client.post(
            "/api/auth/login", json={"email": "sam@example.com", "password": "wrong wrong"}
        )
    # Correct password now, but the account is temporarily locked.
    resp = await app_client.post(
        "/api/auth/login", json={"email": "sam@example.com", "password": DEFAULT_PASSWORD}
    )
    assert resp.status_code == 423
    assert resp.json()["code"] == "account_locked"


async def test_refresh_rotates_and_detects_reuse(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    await login(app_client)

    first_refresh = app_client.cookies["tvtimes_refresh"]
    r1 = await app_client.post("/api/auth/refresh", headers=csrf_header(app_client))
    assert r1.status_code == 200
    rotated_refresh = app_client.cookies["tvtimes_refresh"]
    assert rotated_refresh != first_refresh

    # Replay the original (now-rotated) token: must fail and burn the chain.
    app_client.cookies.set("tvtimes_refresh", first_refresh)
    replay = await app_client.post("/api/auth/refresh", headers=csrf_header(app_client))
    assert replay.status_code == 401

    app_client.cookies.set("tvtimes_refresh", rotated_refresh)
    after = await app_client.post("/api/auth/refresh", headers=csrf_header(app_client))
    assert after.status_code == 401  # whole chain revoked


async def test_repeated_refresh_stays_one_session(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    token = await login(app_client)
    headers = auth_header(token)

    listed = await app_client.get("/api/account/sessions", headers=headers)
    assert len(listed.json()) == 1
    signed_in_at = listed.json()[0]["created_at"]

    # Every reload / access-token expiry rotates the refresh token; that must
    # not spawn a new "active session" per rotation.
    for _ in range(4):
        r = await app_client.post("/api/auth/refresh", headers=csrf_header(app_client))
        assert r.status_code == 200
        headers = auth_header(r.json()["access_token"])

    again = await app_client.get("/api/account/sessions", headers=headers)
    body = again.json()
    assert len(body) == 1
    assert body[0]["current"] is True
    assert body[0]["created_at"] == signed_in_at  # "since" is the sign-in, not the last refresh


async def test_refresh_requires_csrf_header(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    await login(app_client)
    resp = await app_client.post("/api/auth/refresh")  # no X-CSRF-Token
    assert resp.status_code == 403


async def test_logout_clears_cookie_and_revokes_session(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    await login(app_client)
    stale_refresh = app_client.cookies["tvtimes_refresh"]
    stale_csrf = app_client.cookies["tvtimes_csrf"]

    resp = await app_client.post("/api/auth/logout", headers={"X-CSRF-Token": stale_csrf})
    assert resp.status_code == 200
    assert "tvtimes_refresh" not in app_client.cookies  # cleared by the response

    # Even replaying the pre-logout token pair fails: the session is revoked.
    app_client.cookies.set("tvtimes_refresh", stale_refresh)
    app_client.cookies.set("tvtimes_csrf", stale_csrf)
    resp = await app_client.post("/api/auth/refresh", headers={"X-CSRF-Token": stale_csrf})
    assert resp.status_code == 401


async def test_password_reset_flow(
    app_client: AsyncClient, captured_emails: list[dict[str, str]]
) -> None:
    await register_and_verify(app_client, captured_emails)
    await login(app_client)
    captured_emails.clear()

    resp = await app_client.post("/api/auth/password/forgot", json={"email": "sam@example.com"})
    assert resp.status_code == 202
    reset_token = token_from_link(captured_emails[0]["body"])

    new_password = "a whole new password"
    resp = await app_client.post(
        "/api/auth/password/reset", json={"token": reset_token, "password": new_password}
    )
    assert resp.status_code == 200

    # Old sessions revoked; new password works.
    assert (
        await app_client.post(
            "/api/auth/login", json={"email": "sam@example.com", "password": DEFAULT_PASSWORD}
        )
    ).status_code == 401
    assert (
        await app_client.post(
            "/api/auth/login", json={"email": "sam@example.com", "password": new_password}
        )
    ).status_code == 200


async def test_verify_with_bad_token_is_rejected(app_client: AsyncClient) -> None:
    resp = await app_client.post("/api/auth/verify", json={"token": "not-a-real-token"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_invalid"
