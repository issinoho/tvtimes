"""User account. Email is stored lower-cased with a unique index (portable
case-insensitive identity without depending on Postgres citext)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.credentials import PasswordCredential, TotpSecret, WebAuthnCredential
    from app.models.session import AuthSession
    from app.models.tenant import Tenant


class User(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "user_account"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    email_verified_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    # Brute-force throttle state (see app.auth.service).
    failed_login_count: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(TZDateTime)

    # Small, singular, and needed on nearly every auth path -> load eagerly so
    # async code never trips over a lazy load.
    tenant: Mapped[Tenant] = relationship(back_populates="users", lazy="selectin")
    password: Mapped[PasswordCredential | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    totp: Mapped[TotpSecret | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    webauthn_credentials: Mapped[list[WebAuthnCredential]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None
