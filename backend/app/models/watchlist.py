"""Per-user watchlist.

Two kinds of item:

* ``programme`` — a specific airing. Stored as a *snapshot* (channel + start /
  stop + title), deliberately **not** an FK to ``programme``: an EPG refresh
  deletes and re-creates programme rows, which would cascade the reminder away.
  The snapshot is the anchor the reminder fires on.
* ``title`` — a title tracked across the guide; the reminder fires for any
  upcoming airing whose (normalised) title matches.

``watchlist_notification`` is the send-once ledger, keyed by a per-airing string
so a title watch never double-emails the same broadcast.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.source import Channel


class WatchKind(enum.StrEnum):
    programme = "programme"
    # value is "title"; the member isn't named ``title`` because that shadows
    # ``str.title`` on the StrEnum.
    by_title = "title"


class WatchlistItem(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "watchlist_item"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[WatchKind] = mapped_column(
        Enum(WatchKind, native_enum=False, length=16), nullable=False
    )

    # A label to show in lists / emails, for both kinds.
    title_display: Mapped[str] = mapped_column(String(500), nullable=False)

    # kind == programme: the airing snapshot.
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channel.id", ondelete="CASCADE"), index=True
    )
    start_utc: Mapped[datetime | None] = mapped_column(TZDateTime)
    stop_utc: Mapped[datetime | None] = mapped_column(TZDateTime)

    # kind == title: the normalised title to match upcoming programmes against.
    title_norm: Mapped[str | None] = mapped_column(String(500), index=True)

    # How many minutes before an airing to send the reminder.
    lead_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)

    channel: Mapped[Channel | None] = relationship()
    notifications: Mapped[list[WatchlistNotification]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class WatchlistNotification(PkUuidMixin, Base):
    __tablename__ = "watchlist_notification"
    __table_args__ = (
        UniqueConstraint(
            "watchlist_item_id", "airing_key", name="uq_watchlist_notification_item_airing"
        ),
    )

    watchlist_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("watchlist_item.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # f"{channel_id}:{int(start_utc.timestamp())}" — identifies one broadcast.
    airing_key: Mapped[str] = mapped_column(String(80), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    item: Mapped[WatchlistItem] = relationship(back_populates="notifications")
