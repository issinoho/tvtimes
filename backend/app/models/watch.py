"""Watch state reported by an external player.

tvdinner (and anything else holding the tenant's export token) posts the
*intervals* it actually played per channel — not "programme X was watched".
Deliberately so: an EPG refresh deletes and recreates ``programme`` rows, so a
foreign key to one would cascade the history away, the same reasoning that
makes ``watchlist_item`` store an airing snapshot rather than an FK.

An interval is durable, and tvtimes derives watched-ness from it by overlap
against whatever the guide currently says was on (see
``app.services.watch.watched_programme_ids``). Re-deriving on read also means a
corrected clock-shift, or a re-ingested guide, changes the answer for free.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin


class WatchEvent(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "watch_event"
    __table_args__ = (
        # A replayed batch (the reporter retries, or resends its whole log)
        # must not pile up duplicates.
        UniqueConstraint("channel_id", "started_at", name="uq_watch_event_channel_start"),
        Index("ix_watch_event_tenant_started", "tenant_id", "started_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Corrected UTC, matching what the export feeds serve — so an interval is
    # directly comparable with a shifted programme's airtime.
    started_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    # What the reporter believed was on. Never used to match a programme (the
    # overlap does that) — kept for the history UI and for debugging a feed
    # whose times look wrong.
    title: Mapped[str | None] = mapped_column(String(500))
    # A free-text label for the box that reported it ("living room"), so a
    # household with two players can tell them apart. Reporter-supplied.
    device: Mapped[str | None] = mapped_column(String(120))
