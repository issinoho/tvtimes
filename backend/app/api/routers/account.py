"""Account self-service: profile, timezone, passkeys, TOTP, active sessions."""

from __future__ import annotations

import uuid
import zoneinfo
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from app.auth import service
from app.auth.deps import (
    ClientMetaDep,
    CurrentClaims,
    CurrentUser,
    SessionDep,
    VerifiedUser,
)
from app.auth.ratelimit import WEBAUTHN_LIMIT, limiter
from app.config import get_settings
from app.models.credentials import WebAuthnCredential
from app.schemas.account import ExportTokenOut, SourceAlertsIn, TimezoneIn, TmdbTokenIn
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
from app.services import exports as exports_svc
from app.services import tmdb as tmdb_svc

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
        tmdb_connected=bool(user.tenant.tmdb_token_encrypted),
        export_token_set_at=user.tenant.export_token_set_at,
        source_alerts_enabled=user.tenant.source_alerts_enabled,
    )


@router.put("/tmdb-token", response_model=MessageOut)
async def set_tmdb_token(body: TmdbTokenIn, user: VerifiedUser, session: SessionDep) -> MessageOut:
    if not await tmdb_svc.token_looks_valid(body.token):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "TMDB didn't accept that key. Use a v4 API Read Access Token.",
        )
    await tmdb_svc.set_token(session, user.tenant_id, body.token)
    return MessageOut(message="TMDB connected.")


@router.delete("/tmdb-token", response_model=MessageOut)
async def clear_tmdb_token(user: VerifiedUser, session: SessionDep) -> MessageOut:
    await tmdb_svc.clear_token(session, user.tenant_id)
    return MessageOut(message="TMDB disconnected.")


@router.post("/export-token", response_model=ExportTokenOut)
async def create_export_token(user: VerifiedUser, session: SessionDep) -> ExportTokenOut:
    """Mint (or rotate) the tenant's M3U / XMLTV export token. The raw value is
    returned once here and never again — rotate to get a new one."""
    await session.refresh(user, ["tenant"])
    raw = await exports_svc.generate_token(session, user.tenant)
    base = get_settings().public_origin.rstrip("/")
    return ExportTokenOut(
        token=raw,
        playlist_url=f"{base}/api/exports/playlist.m3u?token={raw}",
        epg_url=f"{base}/api/exports/epg.xml?token={raw}",
    )


@router.delete("/export-token", response_model=MessageOut)
async def delete_export_token(user: VerifiedUser, session: SessionDep) -> MessageOut:
    await session.refresh(user, ["tenant"])
    await exports_svc.revoke_token(session, user.tenant)
    return MessageOut(message="Export feeds disabled.")


@router.put("/source-alerts", response_model=MessageOut)
async def set_source_alerts(
    body: SourceAlertsIn, user: VerifiedUser, session: SessionDep
) -> MessageOut:
    await session.refresh(user, ["tenant"])
    user.tenant.source_alerts_enabled = body.enabled
    return MessageOut(
        message="Source alert emails on." if body.enabled else "Source alert emails off."
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
    user: CurrentUser, claims: CurrentClaims, session: SessionDep
) -> list[SessionOut]:
    rows = await service.list_sessions(session, user)
    out: list[SessionOut] = []
    for r in rows:
        item = SessionOut.model_validate(r)
        item.created_at = r.chain_started_at or r.created_at  # sign-in time, not last refresh
        item.current = claims.session_id is not None and r.id == claims.session_id
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
    user: CurrentUser, claims: CurrentClaims, session: SessionDep
) -> MessageOut:
    rows = await service.list_sessions(session, user)
    now = datetime.now(UTC)
    for r in rows:
        if r.id != claims.session_id:
            r.revoked_at = now
    return MessageOut(message="Other sessions revoked.")
