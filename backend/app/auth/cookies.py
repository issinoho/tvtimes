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
# The refresh token is only ever read server-side, so keep it narrowly scoped.
_REFRESH_PATH = "/api/auth"
# The CSRF token is a non-secret double-submit value the SPA must read from
# JavaScript on any route, so it has to be visible at the site root.
_CSRF_PATH = "/"


def _secure() -> bool:
    return get_settings().public_origin.startswith("https://")


def set_session_cookies(response: Response, *, refresh_token: str, max_age_seconds: int) -> str:
    csrf = secrets.token_urlsafe(24)
    common: dict[str, object] = {
        "secure": _secure(),
        "samesite": "lax",
        "max_age": max_age_seconds,
    }
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        path=_REFRESH_PATH,
        **common,  # type: ignore[arg-type]
    )
    # Drop any pre-existing CSRF cookie left at the old auth-scoped path so the
    # browser doesn't send two same-named cookies to /api/auth/* (which would
    # make the double-submit check flaky until the stale one expired).
    response.delete_cookie(CSRF_COOKIE, path=_REFRESH_PATH)
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        path=_CSRF_PATH,
        **common,  # type: ignore[arg-type]
    )
    return csrf


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=_REFRESH_PATH)
    response.delete_cookie(CSRF_COOKIE, path=_CSRF_PATH)
    response.delete_cookie(CSRF_COOKIE, path=_REFRESH_PATH)  # legacy scope


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
