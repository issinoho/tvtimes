"""Thin wrappers over ``py_webauthn`` for passkey registration and login.

Challenges are persisted server-side (``WebAuthnChallenge``) rather than in a
cookie so the ceremony survives the SPA reloading and cannot be replayed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import get_settings


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str
    backed_up: bool


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    new_sign_count: int


def _origin() -> str:
    return get_settings().public_origin.rstrip("/")


def build_registration_options(
    *,
    user_id: uuid.UUID,
    user_name: str,
    user_display_name: str,
    exclude_credential_ids: list[bytes],
) -> tuple[str, bytes]:
    settings = get_settings()
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=user_id.bytes,
        user_name=user_name,
        user_display_name=user_display_name,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=cid) for cid in exclude_credential_ids
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return options_to_json(options), options.challenge


def verify_registration(
    *, credential: dict[str, Any] | str, expected_challenge: bytes
) -> RegistrationResult:
    settings = get_settings()
    v = verify_registration_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=_origin(),
        require_user_verification=False,
    )
    return RegistrationResult(
        credential_id=v.credential_id,
        public_key=v.credential_public_key,
        sign_count=v.sign_count,
        aaguid=v.aaguid,
        backed_up=v.credential_backed_up,
    )


def build_authentication_options(
    *, allow_credential_ids: list[bytes] | None = None
) -> tuple[str, bytes]:
    options = generate_authentication_options(
        rp_id=get_settings().webauthn_rp_id,
        user_verification=UserVerificationRequirement.PREFERRED,
        allow_credentials=(
            [PublicKeyCredentialDescriptor(id=cid) for cid in allow_credential_ids]
            if allow_credential_ids
            else None
        ),
    )
    return options_to_json(options), options.challenge


def verify_authentication(
    *,
    credential: dict[str, Any] | str,
    expected_challenge: bytes,
    public_key: bytes,
    current_sign_count: int,
) -> AuthenticationResult:
    settings = get_settings()
    v = verify_authentication_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=_origin(),
        credential_public_key=public_key,
        credential_current_sign_count=current_sign_count,
        require_user_verification=False,
    )
    return AuthenticationResult(new_sign_count=v.new_sign_count)
