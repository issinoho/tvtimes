"""TOTP (RFC 6238) enrolment and verification, plus single-use recovery codes."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets

import pyotp

RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no ambiguous chars


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, account_name: str, issuer: str = "tvtimes") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def verify_code(secret: str, code: str, *, valid_window: int = 1) -> bool:
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)


# --- recovery codes -----------------------------------------------------------


def generate_recovery_codes() -> list[str]:
    return ["-".join(_group() for _ in range(3)) for _ in range(RECOVERY_CODE_COUNT)]


def _group() -> str:
    return "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(4))


def _hash_recovery(code: str) -> str:
    normalized = code.strip().upper().replace(" ", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_recovery_codes(codes: list[str]) -> str:
    return json.dumps([_hash_recovery(c) for c in codes])


def consume_recovery_code(stored_json: str, code: str) -> tuple[bool, str]:
    """Return ``(matched, remaining_json)``. Comparison is constant-time."""
    try:
        hashes: list[str] = json.loads(stored_json)
    except (ValueError, TypeError):
        hashes = []
    target = _hash_recovery(code)
    for i, h in enumerate(hashes):
        if hmac.compare_digest(h, target):
            remaining = hashes[:i] + hashes[i + 1 :]
            return True, json.dumps(remaining)
    return False, stored_json
