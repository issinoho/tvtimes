"""Shared slowapi limiter and client-IP resolution.

The limiter is keyed by the client's IP. ``X-Forwarded-For`` is honoured only
when the request's direct peer is a configured trusted proxy
(``TVTIMES_TRUSTED_PROXIES``); otherwise the TCP peer is used and XFF ignored,
so a client reaching tvtimes directly can't spoof its address to dodge a rate
limit or poison the audit log. Auth endpoints add their own tighter per-route
limits.
"""

from __future__ import annotations

import contextlib
import ipaddress

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import get_settings

_IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _trusted_nets() -> list[_IpNetwork]:
    nets: list[_IpNetwork] = []
    for entry in get_settings().trusted_proxy_entries:
        with contextlib.suppress(ValueError):
            nets.append(ipaddress.ip_network(entry, strict=False))
    return nets


def _in_nets(addr: str, nets: list[_IpNetwork]) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in nets)


def client_ip(request: Request) -> str | None:
    """The client's real IP.

    If the direct peer is a trusted proxy, walk ``X-Forwarded-For`` from the
    right and return the first address that isn't itself a trusted proxy — the
    closest hop the proxy chain couldn't have forged. Otherwise return the TCP
    peer and ignore ``X-Forwarded-For`` entirely.
    """
    peer = request.client.host if request.client else None
    nets = _trusted_nets()
    if not nets or peer is None or not _in_nets(peer, nets):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    for hop in reversed([h.strip() for h in forwarded.split(",") if h.strip()]):
        if not _in_nets(hop, nets):
            return hop
    return peer  # every hop was a trusted proxy — nothing else to attribute it to


def _key(request: Request) -> str:
    return client_ip(request) or get_remote_address(request)


settings = get_settings()
limiter = Limiter(
    key_func=_key,
    storage_uri=settings.ratelimit_storage_uri,
    enabled=settings.ratelimit_enabled,
    default_limits=["240/minute"],
)

# Per-route limits (referenced from routers).
LOGIN_LIMIT = "10/minute"
# The second factor gets its own (tighter) budget so a 6-digit TOTP space
# can't be walked even with a fresh mfa_token each minute.
MFA_LIMIT = "6/minute"
REGISTER_LIMIT = "5/minute"
VERIFY_LIMIT = "20/minute"
WEBAUTHN_LIMIT = "30/minute"
