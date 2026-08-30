"""Password hashing (Argon2id) and breach screening.

Password is an optional fallback; passkeys are primary. When a password *is*
set we enforce a minimum length and reject known-breached passwords via the
Pwned Passwords k-anonymity range API (best effort — a network failure never
blocks the user).
"""

from __future__ import annotations

import hashlib

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 10

# OWASP-aligned Argon2id parameters (well above the argon2-cffi defaults for
# memory; ~64 MiB, 3 passes).
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"


class PasswordError(ValueError):
    """Raised for a policy violation (too short / breached)."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        _hasher.verify(stored_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:  # pragma: no cover
        return True


async def assert_password_acceptable(password: str, *, check_breach: bool = True) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if check_breach and await _is_breached(password):
        raise PasswordError("This password has appeared in a data breach. Choose another.")


async def _is_breached(password: str) -> bool:
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                _HIBP_RANGE_URL.format(prefix=prefix),
                headers={"Add-Padding": "true"},
            )
            resp.raise_for_status()
    except httpx.HTTPError:
        return False  # fail open — availability over strictness
    for line in resp.text.splitlines():
        candidate, _, _count = line.partition(":")
        if candidate.strip().upper() == suffix:
            return True
    return False
