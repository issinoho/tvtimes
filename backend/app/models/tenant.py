"""Tenant — the unit of isolation. One per account for now; modelled separately
so shared/household accounts are an additive change later."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Tenant(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "tenant"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # IANA name, e.g. "Europe/London". Feeds/channels may override per-source.
    default_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    # TMDB v4 read token, encrypted at rest (app.auth.crypto). Nullable = not set.
    tmdb_token_encrypted: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # sha256 hex of the per-tenant export token (M3U / XMLTV feeds for external
    # players). The raw token is shown once on creation and never stored.
    export_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    export_token_set_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    # Email the tenant's verified users when a source breaks / goes stale /
    # recovers (app.worker.source_alerts). On by default.
    source_alerts_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Push a notification when someone on the account takes an action. Each
    # category is an independent per-tenant opt-in (off by default); when on it
    # fans out to *every* enabled notification target, ignoring the per-target
    # send_* flags (those only gate source alerts / reminders). Push only — these
    # never send email. See app.services.notify.notify_activity.
    notify_on_reminder_set: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notify_on_title_watch_set: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notify_on_play: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notify_on_watchlist_remove: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    users: Mapped[list[User]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
