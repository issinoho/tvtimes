"""Access tokens (short-lived EdDSA JWT) and refresh tokens (opaque, hashed)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import get_settings
from app.logging import get_logger

_ALG = "EdDSA"
_log = get_logger("auth.tokens")


@lru_cache
def _private_key() -> Ed25519PrivateKey:
    pem = get_settings().jwt_private_key_pem.strip()
    if pem:
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("TVTIMES_JWT_PRIVATE_KEY_PEM must be an Ed25519 private key")
        return key
    _log.warning(
        "jwt.ephemeral_key",
        msg="no TVTIMES_JWT_PRIVATE_KEY_PEM set; access tokens will not survive a restart",
    )
    return Ed25519PrivateKey.generate()


def _private_pem() -> bytes:
    return _private_key().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _public_pem() -> bytes:
    return (
        _private_key()
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    jti: str
    expires_at: datetime
    session_id: uuid.UUID | None = None


def issue_access_token(
    user_id: uuid.UUID, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=get_settings().access_token_ttl_seconds)
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "sid": str(session_id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": secrets.token_urlsafe(12),
        "typ": "access",
    }
    token = jwt.encode(payload, _private_pem(), algorithm=_ALG)
    return token, exp


def issue_mfa_token(user_id: uuid.UUID) -> str:
    """Short-lived (5 min) token proving password step passed; exchanged for a
    session once the TOTP/recovery step completes."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "typ": "mfa",
    }
    return jwt.encode(payload, _private_pem(), algorithm=_ALG)


def decode_mfa_token(token: str) -> uuid.UUID:
    data = jwt.decode(token, _public_pem(), algorithms=[_ALG], options={"require": ["exp", "sub"]})
    if data.get("typ") != "mfa":
        raise jwt.InvalidTokenError("wrong token type")
    return uuid.UUID(data["sub"])


def decode_access_token(token: str) -> AccessClaims:
    data = jwt.decode(token, _public_pem(), algorithms=[_ALG], options={"require": ["exp", "sub"]})
    if data.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    sid = data.get("sid")
    return AccessClaims(
        user_id=uuid.UUID(data["sub"]),
        tenant_id=uuid.UUID(data["tid"]),
        jti=data["jti"],
        expires_at=datetime.fromtimestamp(data["exp"], tz=UTC),
        session_id=uuid.UUID(sid) if sid else None,
    )


# --- refresh tokens -------------------------------------------------------------

REFRESH_TOKEN_BYTES = 32


def new_refresh_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hex)``. Only the hash is ever persisted."""
    raw = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_expiry(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now + timedelta(seconds=get_settings().refresh_token_ttl_seconds)
