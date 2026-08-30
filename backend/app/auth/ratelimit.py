"""Shared slowapi limiter.

Keyed by client IP (honouring a trusted ``X-Forwarded-For`` set by the edge
proxy in prod). Auth endpoints add their own tighter per-route limits.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import get_settings


def _key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return get_remote_address(request)


settings = get_settings()
limiter = Limiter(
    key_func=_key,
    storage_uri=settings.ratelimit_storage_uri,
    enabled=settings.ratelimit_enabled,
    default_limits=["240/minute"],
)

# Per-route limits (referenced from routers).
LOGIN_LIMIT = "10/minute"
REGISTER_LIMIT = "5/minute"
VERIFY_LIMIT = "20/minute"
WEBAUTHN_LIMIT = "30/minute"
