"""Refresh-token and CSRF cookie handling.

The refresh token lives only in an HttpOnly cookie scoped to the auth routes.
A non-HttpOnly CSRF cookie is set alongside it; state-changing auth calls that
rely on the cookie (refresh, logout) must echo it back in ``X-CSRF-Token``
(double-submit).
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, Response, status

from app.config import get_settings

REFRESH_COOKIE = "tvtimes_refresh"
CSRF_COOKIE = "tvtimes_csrf"
CSRF_HEADER = "x-csrf-token"
_COOKIE_PATH = "/api/auth"


def _secure() -> bool:
    return get_settings().public_origin.startswith("https://")


def set_session_cookies(response: Response, *, refresh_token: str, max_age_seconds: int) -> str:
    csrf = secrets.token_urlsafe(24)
    common: dict[str, object] = {
        "path": _COOKIE_PATH,
        "secure": _secure(),
        "samesite": "lax",
        "max_age": max_age_seconds,
    }
    response.set_cookie(REFRESH_COOKIE, refresh_token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)  # type: ignore[arg-type]
    return csrf


def clear_session_cookies(response: Response) -> None:
    for name in (REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path=_COOKIE_PATH)


def read_refresh_cookie(request: Request) -> str:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No session cookie")
    return token


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF check failed")
