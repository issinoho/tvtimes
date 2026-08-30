"""A configured TV source and the channels ingested from it."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class SourceKind(enum.StrEnum):
    m3u = "m3u"
    xtream = "xtream"
    stalker = "stalker"


class SourceStatus(enum.StrEnum):
    pending = "pending"
    ok = "ok"
    error = "error"


class Source(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "source"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[SourceKind] = mapped_column(
        Enum(SourceKind, native_enum=False, length=16), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Fernet-encrypted JSON: the kind-specific URL / credentials.
    config_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # IANA name; overrides the tenant default for this source's channels.
    timezone_override: Mapped[str | None] = mapped_column(String(64))
    clock_shift_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=360)

    last_refreshed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_status: Mapped[SourceStatus] = mapped_column(
        Enum(SourceStatus, native_enum=False, length=16),
        nullable=False,
        default=SourceStatus.pending,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    channel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    epg_url: Mapped[str | None] = mapped_column(Text)

    tenant: Mapped[Tenant] = relationship()
    channels: Mapped[list[Channel]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class Channel(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "channel"
    __table_args__ = (
        UniqueConstraint("source_id", "dedupe_key", name="uq_channel_source_id_dedupe_key"),
        Index("ix_channel_source_group", "source_id", "group_title"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stable per-source identity for upserts: the tvg-id, else the name.
    dedupe_key: Mapped[str] = mapped_column(String(400), nullable=False)

    ext_id: Mapped[str | None] = mapped_column(String(256))  # tvg-id
    name: Mapped[str] = mapped_column(String(400), nullable=False)
    tvg_name: Mapped[str | None] = mapped_column(String(400))
    logo_url: Mapped[str | None] = mapped_column(Text)
    group_title: Mapped[str | None] = mapped_column(String(400))
    number: Mapped[int | None] = mapped_column(Integer)
    is_hd: Mapped[bool] = mapped_column(nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Fernet-encrypted: a playable URL (m3u/xtream) or the Stalker "cmd" token.
    stream_ref_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # Per-channel clock correction, on top of the source's shift.
    clock_shift_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    source: Mapped[Source] = relationship(back_populates="channels")
