"""Symmetric at-rest encryption for stored secrets (TOTP seed, source
credentials, TMDB token).

Uses Fernet (AES-128-CBC + HMAC-SHA256, authenticated, timestamped). The
application key comes from ``settings.encryption_key``:

* If it is already a valid 32-byte urlsafe-base64 Fernet key, it is used as-is.
* Otherwise a key is derived deterministically as
  ``urlsafe_b64encode(sha256(key))`` so any passphrase works in dev. Production
  MUST supply a real generated key.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _derive_key(raw: str) -> bytes:
    raw_bytes = raw.encode("utf-8")
    try:
        if len(base64.urlsafe_b64decode(raw_bytes)) == 32:
            return raw_bytes
    except (ValueError, TypeError):
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(raw_bytes).digest())


def _fernet() -> Fernet:
    return Fernet(_derive_key(get_settings().encryption_key))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:  # pragma: no cover - corrupt/rotated key
        raise ValueError("could not decrypt value") from exc
