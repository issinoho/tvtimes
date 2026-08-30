"""XMLTV EPG source and its ingested programmes."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.source import Channel, Source


class EpgStatus(enum.StrEnum):
    pending = "pending"
    ok = "ok"
    error = "error"


class EpgSource(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "epg_source"
    __table_args__ = (UniqueConstraint("tenant_id", "url", name="uq_epg_source_tenant_id_url"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Set when auto-discovered from an M3U/Xtream source; null for a standalone
    # XMLTV URL the user added directly.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)

    etag: Mapped[str | None] = mapped_column(String(400))
    last_modified: Mapped[str | None] = mapped_column(String(200))
    last_fetched_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_status: Mapped[EpgStatus] = mapped_column(
        Enum(EpgStatus, native_enum=False, length=16), nullable=False, default=EpgStatus.pending
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    programme_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=720)

    source: Mapped[Source | None] = relationship()


class Programme(PkUuidMixin, Base):
    __tablename__ = "programme"
    __table_args__ = (
        Index("ix_programme_channel_start", "channel_id", "start_utc"),
        Index("ix_programme_tenant_start", "tenant_id", "start_utc"),
        Index("ix_programme_epg_source_id", "epg_source_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel.id", ondelete="CASCADE"), nullable=False
    )
    epg_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("epg_source.id", ondelete="CASCADE"), nullable=False
    )

    start_utc: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    stop_utc: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    sub_title: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    episode_num: Mapped[str | None] = mapped_column(String(64))
    year: Mapped[str | None] = mapped_column(String(8))
    icon_url: Mapped[str | None] = mapped_column(Text)
    director: Mapped[str | None] = mapped_column(Text)
    is_movie: Mapped[bool] = mapped_column(nullable=False, default=False)

    channel: Mapped[Channel] = relationship()
