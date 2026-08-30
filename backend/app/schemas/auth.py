"""Request/response bodies for the auth API.

The access token is returned in the JSON body (the SPA holds it in memory); the
refresh token is delivered only as an HttpOnly cookie and never appears here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str | None = Field(default=None, min_length=10, max_length=200)


class MessageOut(BaseModel):
    message: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class MfaIn(BaseModel):
    mfa_token: str
    code: str = Field(min_length=4, max_length=20)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class VerifyIn(BaseModel):
    token: str


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)


class WebAuthnLoginBeginIn(BaseModel):
    email: EmailStr | None = None


class WebAuthnCompleteIn(BaseModel):
    # The raw PublicKeyCredential JSON produced by the browser.
    credential: dict[str, Any]


class WebAuthnRegisterCompleteIn(WebAuthnCompleteIn):
    nickname: str = Field(default="Passkey", max_length=80)


class OptionsOut(BaseModel):
    # Opaque JSON string from py_webauthn's options_to_json(); the SPA feeds it
    # straight to @simplewebauthn/browser.
    options: str


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip: str | None
    current: bool = False


class PasskeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nickname: str
    created_at: datetime
    last_used_at: datetime | None
    backed_up: bool


class TotpBeginOut(BaseModel):
    secret: str
    provisioning_uri: str


class TotpConfirmIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool
    tenant_id: uuid.UUID
    default_timezone: str
    totp_enabled: bool
    passkey_count: int
    tmdb_connected: bool = False
