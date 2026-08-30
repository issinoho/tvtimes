"""Authentication credentials: password (fallback), passkeys (primary), TOTP."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class PasswordCredential(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "password_credential"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Full Argon2id PHC string (contains algo params + salt).
    hash: Mapped[str] = mapped_column(String(255), nullable=False)

    user: Mapped[User] = relationship(back_populates="password")


class WebAuthnCredential(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "webauthn_credential"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(default=0, nullable=False)
    # Comma-separated AuthenticatorTransport values ("usb,nfc,internal,hybrid").
    transports: Mapped[str | None] = mapped_column(String(120))
    aaguid: Mapped[str | None] = mapped_column(String(64))
    nickname: Mapped[str] = mapped_column(String(80), nullable=False, default="Passkey")
    backed_up: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    user: Mapped[User] = relationship(back_populates="webauthn_credentials")


class TotpSecret(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "totp_secret"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Base32 secret, encrypted at rest (app.auth.crypto).
    secret_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    # JSON array of sha256 hex digests of unused single-use recovery codes.
    recovery_codes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    user: Mapped[User] = relationship(back_populates="totp")

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None
