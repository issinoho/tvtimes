"""Authentication endpoints: registration, email verification, password &
passkey login, TOTP second factor, session refresh/logout."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.auth import service
from app.auth.cookies import (
    clear_session_cookies,
    read_refresh_cookie,
    require_csrf,
    set_session_cookies,
)
from app.auth.deps import ClientMetaDep, SessionDep
from app.auth.ratelimit import (
    LOGIN_LIMIT,
    MFA_LIMIT,
    REGISTER_LIMIT,
    VERIFY_LIMIT,
    WEBAUTHN_LIMIT,
    limiter,
)
from app.auth.service import IssuedSession
from app.config import get_settings
from app.schemas.auth import (
    LoginIn,
    MessageOut,
    MfaIn,
    OptionsOut,
    RegisterIn,
    ResetIn,
    ResetRequestIn,
    TokenOut,
    VerifyIn,
    WebAuthnCompleteIn,
    WebAuthnLoginBeginIn,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC_REGISTER = "If that address can be used, a confirmation email is on its way."
_GENERIC_RESET = "If that account exists, a reset link is on its way."


def _finish_login(response: Response, issued: IssuedSession) -> TokenOut:
    set_session_cookies(
        response,
        refresh_token=issued.refresh_token,
        max_age_seconds=get_settings().refresh_token_ttl_seconds,
    )
    return TokenOut(access_token=issued.access_token, expires_at=issued.access_expires)


@router.post("/register", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(REGISTER_LIMIT)
async def register(
    request: Request, body: RegisterIn, session: SessionDep, meta: ClientMetaDep
) -> MessageOut:
    await service.register(
        session,
        email=body.email,
        display_name=body.display_name,
        password=body.password,
        timezone=body.timezone,
        meta=meta,
    )
    return MessageOut(message=_GENERIC_REGISTER)


@router.post("/verify", response_model=MessageOut)
@limiter.limit(VERIFY_LIMIT)
async def verify(
    request: Request, body: VerifyIn, session: SessionDep, meta: ClientMetaDep
) -> MessageOut:
    await service.verify_email(session, raw_token=body.token, meta=meta)
    return MessageOut(message="Email verified. You can sign in now.")


@router.post("/login", response_model=TokenOut)
@limiter.limit(LOGIN_LIMIT)
async def login(
    request: Request,
    body: LoginIn,
    response: Response,
    session: SessionDep,
    meta: ClientMetaDep,
) -> TokenOut:
    issued = await service.password_login(
        session, email=body.email, password=body.password, meta=meta
    )
    return _finish_login(response, issued)


@router.post("/login/mfa", response_model=TokenOut)
@limiter.limit(MFA_LIMIT)
async def login_mfa(
    request: Request,
    body: MfaIn,
    response: Response,
    session: SessionDep,
    meta: ClientMetaDep,
) -> TokenOut:
    issued = await service.complete_mfa_login(
        session, mfa_token=body.mfa_token, code=body.code, meta=meta
    )
    return _finish_login(response, issued)


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("60/minute")
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    meta: ClientMetaDep,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> TokenOut:
    raw = read_refresh_cookie(request)
    issued = await service.rotate_session(session, raw_refresh=raw, meta=meta)
    return _finish_login(response, issued)


@router.post("/logout", response_model=MessageOut)
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MessageOut:
    raw = request.cookies.get("tvtimes_refresh")
    if raw:
        await service.logout(session, raw_refresh=raw)
    clear_session_cookies(response)
    return MessageOut(message="Signed out.")


# --- password reset ----------------------------------------------------------


@router.post("/password/forgot", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(REGISTER_LIMIT)
async def forgot_password(
    request: Request, body: ResetRequestIn, session: SessionDep, meta: ClientMetaDep
) -> MessageOut:
    await service.request_password_reset(session, email=body.email, meta=meta)
    return MessageOut(message=_GENERIC_RESET)


@router.post("/password/reset", response_model=MessageOut)
@limiter.limit(LOGIN_LIMIT)
async def do_reset_password(
    request: Request, body: ResetIn, session: SessionDep, meta: ClientMetaDep
) -> MessageOut:
    await service.reset_password(
        session, raw_token=body.token, new_password=body.password, meta=meta
    )
    return MessageOut(message="Password updated. Sign in with your new password.")


# --- passkey login ---------------------------------------------------------


@router.post("/webauthn/login/options", response_model=OptionsOut)
@limiter.limit(WEBAUTHN_LIMIT)
async def webauthn_login_options(
    request: Request, body: WebAuthnLoginBeginIn, session: SessionDep
) -> OptionsOut:
    options = await service.webauthn_login_begin(session, email=body.email)
    return OptionsOut(options=options)


@router.post("/webauthn/login/verify", response_model=TokenOut)
@limiter.limit(LOGIN_LIMIT)
async def webauthn_login_verify(
    request: Request,
    body: WebAuthnCompleteIn,
    response: Response,
    session: SessionDep,
    meta: ClientMetaDep,
) -> TokenOut:
    issued = await service.webauthn_login_complete(session, credential=body.credential, meta=meta)
    return _finish_login(response, issued)


# Passkey *registration* needs an authenticated user — see routers/account.py.
