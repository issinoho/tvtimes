"""Short-lived server-side tokens: email verification / password reset, and
WebAuthn ceremony challenges."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin


class EmailTokenPurpose(enum.StrEnum):
    verify = "verify"
    reset = "reset"


class EmailToken(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "email_token"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[EmailTokenPurpose] = mapped_column(
        Enum(EmailTokenPurpose, native_enum=False, length=16), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class WebAuthnChallengeKind(enum.StrEnum):
    registration = "registration"
    authentication = "authentication"


class WebAuthnChallenge(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "webauthn_challenge"

    # Null for a discoverable-credential (usernameless) login ceremony.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[WebAuthnChallengeKind] = mapped_column(
        Enum(WebAuthnChallengeKind, native_enum=False, length=16), nullable=False
    )
    challenge: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
