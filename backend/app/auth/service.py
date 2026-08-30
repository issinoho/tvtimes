"""Auth orchestration: registration, email verification, login (password +
passkey), TOTP, and refresh-session rotation with reuse detection."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import passwords, tokens, totp, webauthn
from app.auth.crypto import decrypt, encrypt
from app.auth.email import send_email
from app.auth.errors import (
    AccountLocked,
    EmailNotVerified,
    InvalidCredentials,
    MfaRequired,
    PolicyViolation,
    TokenInvalid,
)
from app.config import get_settings
from app.logging import get_logger
from app.models.audit import AuditLog
from app.models.credentials import PasswordCredential, TotpSecret, WebAuthnCredential
from app.models.session import AuthSession
from app.models.tenant import Tenant
from app.models.token import (
    EmailToken,
    EmailTokenPurpose,
    WebAuthnChallenge,
    WebAuthnChallengeKind,
)
from app.models.user import User

_log = get_logger("auth.service")

_EMAIL_TOKEN_TTL = timedelta(hours=2)
_CHALLENGE_TTL = timedelta(minutes=5)
_LOCK_THRESHOLD = 5
_LOCK_BASE = timedelta(seconds=30)
_LOCK_MAX = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class ClientMeta:
    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    access_token: str
    access_expires: datetime
    refresh_token: str
    refresh_expires: datetime
    session_id: uuid.UUID


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _audit(
    session: AsyncSession,
    event: str,
    *,
    user: User | None = None,
    meta: ClientMeta | None = None,
    **detail: object,
) -> None:
    session.add(
        AuditLog(
            event=event,
            user_id=user.id if user else None,
            tenant_id=user.tenant_id if user else None,
            ip=meta.ip if meta else None,
            user_agent=meta.user_agent if meta else None,
            detail=detail,
        )
    )
    _log.info(f"auth.{event}", user_id=str(user.id) if user else None, **detail)


# --- registration & verification --------------------------------------------


async def register(
    session: AsyncSession,
    *,
    email: str,
    display_name: str,
    password: str | None,
    meta: ClientMeta | None = None,
) -> None:
    """Always returns without revealing whether the address was already in use.
    A verification email (or an 'account exists' notice) is sent out of band."""
    email = normalize_email(email)
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        await _audit(session, "register_existing", user=existing, meta=meta)
        await send_email(
            to=email,
            subject="tvtimes — you already have an account",
            body_text=(
                "Someone (hopefully you) tried to sign up with this address, "
                "which already has a tvtimes account. Try signing in instead."
            ),
        )
        return

    if password is not None:
        try:
            await passwords.assert_password_acceptable(password)
        except passwords.PasswordError as exc:
            raise PolicyViolation(str(exc)) from exc

    tenant = Tenant(name=display_name.strip() or email, default_timezone="UTC")
    user = User(
        tenant=tenant,
        email=email,
        display_name=display_name.strip() or email.split("@")[0],
        is_owner=True,
    )
    session.add(tenant)
    session.add(user)
    if password is not None:
        user.password = PasswordCredential(hash=passwords.hash_password(password))
    await session.flush()

    raw_token = await _issue_email_token(session, user, EmailTokenPurpose.verify)
    await _audit(session, "register", user=user, meta=meta)
    await send_email(
        to=email,
        subject="tvtimes — confirm your email",
        body_text=_verify_email_body(raw_token),
    )


async def _issue_email_token(session: AsyncSession, user: User, purpose: EmailTokenPurpose) -> str:
    raw = secrets.token_urlsafe(32)
    session.add(
        EmailToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_hash_token(raw),
            expires_at=_now() + _EMAIL_TOKEN_TTL,
        )
    )
    return raw


def _verify_email_body(raw_token: str) -> str:
    url = f"{get_settings().public_origin.rstrip('/')}/verify?token={raw_token}"
    return f"Welcome to tvtimes. Confirm your address:\n\n{url}\n\nThe link expires in 2 hours."


async def verify_email(
    session: AsyncSession, *, raw_token: str, meta: ClientMeta | None = None
) -> None:
    row = await session.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == _hash_token(raw_token),
            EmailToken.purpose == EmailTokenPurpose.verify,
        )
    )
    if row is None or row.used_at is not None or row.expires_at <= _now():
        raise TokenInvalid()
    user = await session.get(User, row.user_id)
    if user is None:
        raise TokenInvalid()
    row.used_at = _now()
    if user.email_verified_at is None:
        user.email_verified_at = _now()
    await _audit(session, "email_verified", user=user, meta=meta)


# --- password login --------------------------------------------------------


async def password_login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    meta: ClientMeta | None = None,
) -> IssuedSession:
    email = normalize_email(email)
    user = await session.scalar(select(User).where(User.email == email))
    if user is None or user.password is None:
        # Equalise timing against a real Argon2 verify.
        passwords.verify_password(
            "$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "A" * 43, password
        )
        await _audit(session, "login_failed", meta=meta, email=email, reason="no_user")
        raise InvalidCredentials()

    if user.locked_until is not None and user.locked_until > _now():
        raise AccountLocked()

    if not passwords.verify_password(user.password.hash, password):
        await _register_failed_login(session, user, meta)
        raise InvalidCredentials()

    # Success: reset throttle, opportunistically upgrade the hash.
    user.failed_login_count = 0
    user.locked_until = None
    if passwords.needs_rehash(user.password.hash):
        user.password.hash = passwords.hash_password(password)

    if user.email_verified_at is None:
        raise EmailNotVerified()

    if user.totp is not None and user.totp.confirmed_at is not None:
        await _audit(session, "login_password_ok_mfa_pending", user=user, meta=meta)
        raise MfaRequired(tokens.issue_mfa_token(user.id))

    return await issue_session(session, user, meta, method="password")


async def _register_failed_login(
    session: AsyncSession, user: User, meta: ClientMeta | None
) -> None:
    user.failed_login_count += 1
    if user.failed_login_count >= _LOCK_THRESHOLD:
        backoff = min(_LOCK_BASE * (2 ** (user.failed_login_count - _LOCK_THRESHOLD)), _LOCK_MAX)
        user.locked_until = _now() + backoff
    await _audit(
        session,
        "login_failed",
        user=user,
        meta=meta,
        reason="bad_password",
        failed_count=user.failed_login_count,
    )


async def complete_mfa_login(
    session: AsyncSession,
    *,
    mfa_token: str,
    code: str,
    meta: ClientMeta | None = None,
) -> IssuedSession:
    try:
        user_id = tokens.decode_mfa_token(mfa_token)
    except Exception as exc:
        raise TokenInvalid() from exc
    user = await session.get(User, user_id)
    if user is None or user.totp is None or user.totp.confirmed_at is None:
        raise TokenInvalid()

    # A lockout raised after the password step still applies here.
    if user.locked_until is not None and user.locked_until > _now():
        raise AccountLocked()

    secret = decrypt(user.totp.secret_encrypted)
    if totp.verify_code(secret, code):
        await _audit(session, "mfa_ok", user=user, meta=meta, factor="totp")
        return await issue_session(session, user, meta, method="password+totp")

    matched, remaining = totp.consume_recovery_code(user.totp.recovery_codes, code)
    if matched:
        user.totp.recovery_codes = remaining
        await _audit(session, "mfa_ok", user=user, meta=meta, factor="recovery")
        return await issue_session(session, user, meta, method="password+recovery")

    await _audit(session, "mfa_failed", user=user, meta=meta)
    raise InvalidCredentials("That code is not valid.")


# --- session issuance & rotation -----------------------------------------------


async def issue_session(
    session: AsyncSession,
    user: User,
    meta: ClientMeta | None,
    *,
    method: str,
    parent: AuthSession | None = None,
) -> IssuedSession:
    raw_refresh, refresh_hash = tokens.new_refresh_token()
    expires = tokens.refresh_expiry()
    row = AuthSession(
        user_id=user.id,
        token_hash=refresh_hash,
        parent_id=parent.id if parent else None,
        expires_at=expires,
        user_agent=(meta.user_agent if meta else None),
        ip=(meta.ip if meta else None),
    )
    session.add(row)
    await session.flush()
    user.last_login_at = _now()
    access, access_exp = tokens.issue_access_token(user.id, user.tenant_id)
    if parent is None:
        await _audit(session, "session_issued", user=user, meta=meta, method=method)
    return IssuedSession(
        access_token=access,
        access_expires=access_exp,
        refresh_token=raw_refresh,
        refresh_expires=expires,
        session_id=row.id,
    )


async def rotate_session(
    session: AsyncSession, *, raw_refresh: str, meta: ClientMeta | None = None
) -> IssuedSession:
    token_hash = tokens.hash_refresh_token(raw_refresh)
    row = await session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if row is None or row.revoked_at is not None:
        raise TokenInvalid()

    if row.rotated_at is not None:
        # This token was already exchanged — a replay. Burn the whole chain.
        await _revoke_user_sessions(session, row.user_id)
        user = await session.get(User, row.user_id)
        await _audit(session, "refresh_reuse_detected", user=user, meta=meta)
        raise TokenInvalid("Session invalidated. Please sign in again.")

    if row.expires_at <= _now():
        raise TokenInvalid()

    user = await session.get(User, row.user_id)
    if user is None:
        raise TokenInvalid()

    row.rotated_at = _now()
    return await issue_session(session, user, meta, method="refresh", parent=row)


async def _revoke_user_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    rows = await session.scalars(
        select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    )
    for row in rows:
        row.revoked_at = _now()


async def logout(session: AsyncSession, *, raw_refresh: str) -> None:
    token_hash = tokens.hash_refresh_token(raw_refresh)
    row = await session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()


async def list_sessions(session: AsyncSession, user: User) -> list[AuthSession]:
    rows = await session.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .order_by(AuthSession.created_at.desc())
    )
    return list(rows)


async def revoke_session(session: AsyncSession, user: User, session_id: uuid.UUID) -> None:
    row = await session.get(AuthSession, session_id)
    if row is None or row.user_id != user.id:
        raise TokenInvalid("Unknown session.")
    if row.revoked_at is None:
        row.revoked_at = _now()
    await _audit(session, "session_revoked", user=user, session_id=str(session_id))


# --- passkeys ---------------------------------------------------------------


async def webauthn_register_begin(session: AsyncSession, user: User) -> str:
    existing = await session.scalars(
        select(WebAuthnCredential.credential_id).where(WebAuthnCredential.user_id == user.id)
    )
    options_json, challenge = webauthn.build_registration_options(
        user_id=user.id,
        user_name=user.email,
        user_display_name=user.display_name,
        exclude_credential_ids=list(existing),
    )
    session.add(
        WebAuthnChallenge(
            user_id=user.id,
            kind=WebAuthnChallengeKind.registration,
            challenge=challenge,
            expires_at=_now() + _CHALLENGE_TTL,
        )
    )
    return options_json


async def webauthn_register_complete(
    session: AsyncSession,
    user: User,
    *,
    credential: dict[str, Any],
    nickname: str,
    meta: ClientMeta | None = None,
) -> WebAuthnCredential:
    challenge = await _take_challenge(session, WebAuthnChallengeKind.registration, user_id=user.id)
    try:
        result = webauthn.verify_registration(
            credential=credential, expected_challenge=challenge.challenge
        )
    except Exception as exc:
        raise TokenInvalid("Could not verify the passkey.") from exc

    cred = WebAuthnCredential(
        user_id=user.id,
        credential_id=result.credential_id,
        public_key=result.public_key,
        sign_count=result.sign_count,
        aaguid=result.aaguid,
        backed_up=result.backed_up,
        nickname=nickname.strip()[:80] or "Passkey",
    )
    session.add(cred)
    await _audit(session, "passkey_registered", user=user, meta=meta)
    return cred


async def webauthn_login_begin(session: AsyncSession, *, email: str | None) -> str:
    user: User | None = None
    allow: list[bytes] | None = None
    if email:
        user = await session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is not None:
            allow = list(
                await session.scalars(
                    select(WebAuthnCredential.credential_id).where(
                        WebAuthnCredential.user_id == user.id
                    )
                )
            )
    options_json, challenge = webauthn.build_authentication_options(allow_credential_ids=allow)
    session.add(
        WebAuthnChallenge(
            user_id=user.id if user else None,
            kind=WebAuthnChallengeKind.authentication,
            challenge=challenge,
            expires_at=_now() + _CHALLENGE_TTL,
        )
    )
    return options_json


async def webauthn_login_complete(
    session: AsyncSession,
    *,
    credential: dict[str, Any],
    meta: ClientMeta | None = None,
) -> IssuedSession:
    raw_id = credential.get("rawId") or credential.get("id")
    if not isinstance(raw_id, str):
        raise TokenInvalid("Malformed passkey response.")
    from webauthn import base64url_to_bytes

    try:
        credential_id = base64url_to_bytes(raw_id)
    except Exception as exc:
        raise TokenInvalid("Malformed passkey response.") from exc

    cred = await session.scalar(
        select(WebAuthnCredential).where(WebAuthnCredential.credential_id == credential_id)
    )
    if cred is None:
        raise TokenInvalid("Unknown passkey.")
    user = await session.get(User, cred.user_id)
    if user is None:
        raise TokenInvalid()

    challenge = await _take_challenge(
        session, WebAuthnChallengeKind.authentication, user_id=user.id, allow_null_user=True
    )
    try:
        result = webauthn.verify_authentication(
            credential=credential,
            expected_challenge=challenge.challenge,
            public_key=cred.public_key,
            current_sign_count=cred.sign_count,
        )
    except Exception as exc:
        await _audit(session, "passkey_login_failed", user=user, meta=meta)
        raise TokenInvalid("Could not verify the passkey.") from exc

    cred.sign_count = result.new_sign_count
    cred.last_used_at = _now()
    if user.email_verified_at is None:
        raise EmailNotVerified()
    # A passkey is phishing-resistant MFA on its own; no TOTP step.
    return await issue_session(session, user, meta, method="passkey")


async def _take_challenge(
    session: AsyncSession,
    kind: WebAuthnChallengeKind,
    *,
    user_id: uuid.UUID,
    allow_null_user: bool = False,
) -> WebAuthnChallenge:
    conditions = [
        WebAuthnChallenge.kind == kind,
        WebAuthnChallenge.consumed_at.is_(None),
        WebAuthnChallenge.expires_at > _now(),
    ]
    if allow_null_user:
        conditions.append(
            (WebAuthnChallenge.user_id == user_id) | (WebAuthnChallenge.user_id.is_(None))
        )
    else:
        conditions.append(WebAuthnChallenge.user_id == user_id)
    row = await session.scalar(
        select(WebAuthnChallenge).where(*conditions).order_by(WebAuthnChallenge.created_at.desc())
    )
    if row is None:
        raise TokenInvalid("No matching challenge; start again.")
    row.consumed_at = _now()
    return row


# --- password reset -------------------------------------------------------------


async def request_password_reset(
    session: AsyncSession, *, email: str, meta: ClientMeta | None = None
) -> None:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        await _audit(session, "reset_requested_unknown", meta=meta, email=normalize_email(email))
        return
    raw = await _issue_email_token(session, user, EmailTokenPurpose.reset)
    await _audit(session, "reset_requested", user=user, meta=meta)
    url = f"{get_settings().public_origin.rstrip('/')}/reset?token={raw}"
    await send_email(
        to=user.email,
        subject="tvtimes — reset your password",
        body_text=f"Reset your password:\n\n{url}\n\nThe link expires in 2 hours. "
        "If you didn't ask for this, ignore this email.",
    )


async def reset_password(
    session: AsyncSession, *, raw_token: str, new_password: str, meta: ClientMeta | None = None
) -> None:
    row = await session.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == _hash_token(raw_token),
            EmailToken.purpose == EmailTokenPurpose.reset,
        )
    )
    if row is None or row.used_at is not None or row.expires_at <= _now():
        raise TokenInvalid()
    user = await session.get(User, row.user_id)
    if user is None:
        raise TokenInvalid()
    try:
        await passwords.assert_password_acceptable(new_password)
    except passwords.PasswordError as exc:
        raise PolicyViolation(str(exc)) from exc

    row.used_at = _now()
    if user.password is None:
        user.password = PasswordCredential(hash=passwords.hash_password(new_password))
    else:
        user.password.hash = passwords.hash_password(new_password)
    await _revoke_user_sessions(session, user.id)
    await _audit(session, "password_reset", user=user, meta=meta)


# --- TOTP enrolment ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TotpEnrolment:
    secret: str
    provisioning_uri: str


async def totp_begin(session: AsyncSession, user: User) -> TotpEnrolment:
    secret = totp.new_secret()
    if user.totp is None:
        user.totp = TotpSecret(secret_encrypted=encrypt(secret), recovery_codes="[]")
    elif user.totp.confirmed_at is None:
        user.totp.secret_encrypted = encrypt(secret)
    else:
        raise PolicyViolation("TOTP is already enabled. Disable it first to re-enrol.")
    return TotpEnrolment(
        secret=secret,
        provisioning_uri=totp.provisioning_uri(secret, account_name=user.email),
    )


async def totp_confirm(
    session: AsyncSession, user: User, *, code: str, meta: ClientMeta | None = None
) -> list[str]:
    if user.totp is None or user.totp.confirmed_at is not None:
        raise PolicyViolation("Nothing to confirm.")
    secret = decrypt(user.totp.secret_encrypted)
    if not totp.verify_code(secret, code):
        raise InvalidCredentials("That code is not valid.")
    user.totp.confirmed_at = _now()
    codes = totp.generate_recovery_codes()
    user.totp.recovery_codes = totp.hash_recovery_codes(codes)
    await _audit(session, "totp_enabled", user=user, meta=meta)
    return codes


async def totp_disable(
    session: AsyncSession, user: User, *, meta: ClientMeta | None = None
) -> None:
    if user.totp is not None:
        await session.delete(user.totp)
        user.totp = None
    await _audit(session, "totp_disabled", user=user, meta=meta)
