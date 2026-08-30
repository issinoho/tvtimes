"""Account self-service: profile, timezone, passkeys, TOTP, active sessions."""

from __future__ import annotations

import uuid
import zoneinfo
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.auth import service
from app.auth.deps import ClientMetaDep, CurrentUser, SessionDep, VerifiedUser
from app.auth.ratelimit import WEBAUTHN_LIMIT, limiter
from app.auth.tokens import hash_refresh_token
from app.models.credentials import WebAuthnCredential
from app.schemas.account import TimezoneIn
from app.schemas.auth import (
    MeOut,
    MessageOut,
    OptionsOut,
    PasskeyOut,
    RecoveryCodesOut,
    SessionOut,
    TotpBeginOut,
    TotpConfirmIn,
    WebAuthnRegisterCompleteIn,
)

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, session: SessionDep) -> MeOut:
    await session.refresh(user, ["tenant", "totp"])
    passkeys = await session.scalar(
        select(func.count())
        .select_from(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
    )
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        tenant_id=user.tenant_id,
        default_timezone=user.tenant.default_timezone,
        totp_enabled=user.totp is not None and user.totp.confirmed_at is not None,
        passkey_count=passkeys or 0,
    )


@router.put("/timezone", response_model=MessageOut)
async def set_timezone(body: TimezoneIn, user: VerifiedUser, session: SessionDep) -> MessageOut:
    try:
        zoneinfo.ZoneInfo(body.timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown timezone") from exc
    await session.refresh(user, ["tenant"])
    user.tenant.default_timezone = body.timezone
    return MessageOut(message="Timezone updated.")


# --- passkeys --------------------------------------------------------------


@router.post("/passkeys/options", response_model=OptionsOut)
@limiter.limit(WEBAUTHN_LIMIT)
async def passkey_register_options(
    request: Request, user: VerifiedUser, session: SessionDep
) -> OptionsOut:
    options = await service.webauthn_register_begin(session, user)
    return OptionsOut(options=options)


@router.post("/passkeys", response_model=PasskeyOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(WEBAUTHN_LIMIT)
async def passkey_register_verify(
    request: Request,
    body: WebAuthnRegisterCompleteIn,
    user: VerifiedUser,
    session: SessionDep,
    meta: ClientMetaDep,
) -> PasskeyOut:
    cred = await service.webauthn_register_complete(
        session, user, credential=body.credential, nickname=body.nickname, meta=meta
    )
    await session.flush()
    return PasskeyOut.model_validate(cred)


@router.get("/passkeys", response_model=list[PasskeyOut])
async def list_passkeys(user: CurrentUser, session: SessionDep) -> list[PasskeyOut]:
    rows = await session.scalars(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
        .order_by(WebAuthnCredential.created_at.desc())
    )
    return [PasskeyOut.model_validate(r) for r in rows]


@router.delete("/passkeys/{passkey_id}", response_model=MessageOut)
async def delete_passkey(
    passkey_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> MessageOut:
    cred = await session.get(WebAuthnCredential, passkey_id)
    if cred is None or cred.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown passkey")
    await session.delete(cred)
    return MessageOut(message="Passkey removed.")


# --- TOTP ---------------------------------------------------------------------


@router.post("/totp", response_model=TotpBeginOut)
async def totp_begin(user: VerifiedUser, session: SessionDep) -> TotpBeginOut:
    enrol = await service.totp_begin(session, user)
    return TotpBeginOut(secret=enrol.secret, provisioning_uri=enrol.provisioning_uri)


@router.post("/totp/confirm", response_model=RecoveryCodesOut)
async def totp_confirm(
    body: TotpConfirmIn, user: VerifiedUser, session: SessionDep, meta: ClientMetaDep
) -> RecoveryCodesOut:
    codes = await service.totp_confirm(session, user, code=body.code, meta=meta)
    return RecoveryCodesOut(recovery_codes=codes)


@router.delete("/totp", response_model=MessageOut)
async def totp_disable(user: VerifiedUser, session: SessionDep, meta: ClientMetaDep) -> MessageOut:
    await service.totp_disable(session, user, meta=meta)
    return MessageOut(message="Two-factor authentication disabled.")


# --- sessions / devices -----------------------------------------------------


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    request: Request, user: CurrentUser, session: SessionDep
) -> list[SessionOut]:
    rows = await service.list_sessions(session, user)
    current_hash = None
    cookie = request.cookies.get("tvtimes_refresh")
    if cookie:
        current_hash = hash_refresh_token(cookie)
    out: list[SessionOut] = []
    for r in rows:
        item = SessionOut.model_validate(r)
        item.current = r.token_hash == current_hash
        out.append(item)
    return out


@router.delete("/sessions/{session_id}", response_model=MessageOut)
async def revoke_session(
    session_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> MessageOut:
    await service.revoke_session(session, user, session_id)
    return MessageOut(message="Session revoked.")


@router.delete("/sessions", response_model=MessageOut)
async def revoke_other_sessions(
    request: Request, user: CurrentUser, session: SessionDep
) -> MessageOut:
    keep = None
    cookie = request.cookies.get("tvtimes_refresh")
    if cookie:
        keep = hash_refresh_token(cookie)
    rows = await service.list_sessions(session, user)
    now = datetime.now(UTC)
    for r in rows:
        if r.token_hash != keep:
            r.revoked_at = now
    return MessageOut(message="Other sessions revoked.")
