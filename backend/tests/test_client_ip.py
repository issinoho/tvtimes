"""app.auth.ratelimit.client_ip — trusts X-Forwarded-For only from a
configured proxy, so a direct client can't spoof its address."""

from __future__ import annotations

import ipaddress

import pytest
from app.auth import ratelimit
from starlette.requests import Request


def _request(peer: str | None, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    scope = {
        "type": "http",
        "headers": headers,
        "client": (peer, 12345) if peer is not None else None,
    }
    return Request(scope)


@pytest.fixture
def trust(monkeypatch: pytest.MonkeyPatch):
    def _set(*cidrs: str) -> None:
        nets = [ipaddress.ip_network(c) for c in cidrs]
        monkeypatch.setattr(ratelimit, "_trusted_nets", lambda: nets)

    return _set


def test_no_trusted_proxies_ignores_xff(trust) -> None:
    trust()  # none
    assert ratelimit.client_ip(_request("203.0.113.9", "1.2.3.4")) == "203.0.113.9"


def test_untrusted_peer_ignores_xff(trust) -> None:
    trust("10.0.0.0/8")
    assert ratelimit.client_ip(_request("203.0.113.9", "1.2.3.4")) == "203.0.113.9"


def test_trusted_peer_takes_the_forwarded_client(trust) -> None:
    trust("10.0.0.0/8")
    assert ratelimit.client_ip(_request("10.0.0.2", "1.2.3.4")) == "1.2.3.4"


def test_trusted_peer_skips_trailing_trusted_hops(trust) -> None:
    trust("10.0.0.0/8")
    assert ratelimit.client_ip(_request("10.0.0.2", "1.2.3.4, 10.0.0.9")) == "1.2.3.4"


def test_spoofed_prepend_is_ignored(trust) -> None:
    # Attacker sends "X-Forwarded-For: 9.9.9.9"; the real proxy appends the true
    # client. Walking from the right, the first non-proxy hop is the real one.
    trust("10.0.0.0/8")
    assert ratelimit.client_ip(_request("10.0.0.2", "9.9.9.9, 1.2.3.4")) == "1.2.3.4"


def test_malformed_hop_is_skipped(trust) -> None:
    trust("10.0.0.0/8")
    assert ratelimit.client_ip(_request("10.0.0.2", "not-an-ip, 1.2.3.4")) == "1.2.3.4"


def test_trusted_peer_no_xff_uses_peer(trust) -> None:
    trust("10.0.0.0/8")
    assert ratelimit.client_ip(_request("10.0.0.2")) == "10.0.0.2"


def test_all_hops_trusted_falls_back_to_peer(trust) -> None:
    trust("10.0.0.0/8")
    assert ratelimit.client_ip(_request("10.0.0.2", "10.0.0.7")) == "10.0.0.2"


def test_no_client_is_none(trust) -> None:
    trust("10.0.0.0/8")
    assert ratelimit.client_ip(_request(None, "1.2.3.4")) is None
