"""Per-user favourite channels.

Unlike a watchlist ``programme`` item, this is a plain FK to ``channel`` —
channels are reconciled in place across a source refresh (by ``dedupe_key``),
so a favourite survives it. Per user, so a household account can differ.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.source import Channel


class FavouriteChannel(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "favourite_channel"
    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", name="uq_favourite_channel_user_channel"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel.id", ondelete="CASCADE"), nullable=False, index=True
    )

    channel: Mapped[Channel] = relationship()
