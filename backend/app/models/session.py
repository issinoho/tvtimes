"""Long-lived refresh sessions with a rotation chain and reuse detection."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class AuthSession(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "auth_session"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # sha256 hex of the opaque refresh token; the token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Previous session id in the rotation chain (None for the first).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_session.id", ondelete="SET NULL")
    )
    # Set when this token has been exchanged for a successor. A second use of an
    # already-rotated token is a replay -> revoke the whole chain.
    rotated_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    # When the *first* token in this rotation chain was issued (i.e. the actual
    # sign-in time). Carried forward on every rotation so the sessions list can
    # show "signed in since" rather than "last refreshed".
    chain_started_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="sessions")

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.rotated_at is None and self.expires_at > now
