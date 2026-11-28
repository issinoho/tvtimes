"""A configured TV source and the channels ingested from it."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class SourceKind(enum.StrEnum):
    m3u = "m3u"
    xtream = "xtream"
    stalker = "stalker"
    hdhomerun = "hdhomerun"
    connector = "connector"


def relay_default(kind: SourceKind) -> bool:
    """Whether a new source of this kind relays its streams by default. Only a
    directly-added HDHomeRun: its tuner is LAN-only, whereas a connector's tuner
    sits on another network the server can't reach."""
    return kind is SourceKind.hdhomerun


def relay_supported(kind: SourceKind) -> bool:
    """Stalker streams are resolved per play, so they can't be relayed."""
    return kind is not SourceKind.stalker


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

    # Proxy playback of this source's streams through the server (so LAN-only
    # streams work from outside the network). Not offered for stalker.
    relay_streams: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=false()
    )
    # When relaying an HLS master playlist, offer one quality (plus one
    # rendition of each audio/subtitle group it uses) instead of all of them:
    # ffmpeg-based players open every rendition before playing, and through a
    # home upload that makes startup take tens of seconds.
    relay_single_variant: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=false()
    )

    # User-defined order on the Sources screen; the guide lists channels
    # source-by-source in this order.
    sort_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_refreshed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_status: Mapped[SourceStatus] = mapped_column(
        Enum(SourceStatus, native_enum=False, length=16),
        nullable=False,
        default=SourceStatus.pending,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    channel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    epg_url: Mapped[str | None] = mapped_column(Text)
    # Guide URLs the playlist lists when it lists more than one (``epg_url`` is
    # then null): offered on the source's page, attached only by hand.
    advertised_epg_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # The rolled-up health ("ok" | "stale" | "error") we last emailed the tenant
    # about — so alerts fire on a transition, not every worker tick. None = the
    # worker hasn't assessed this source yet.
    alerted_health: Mapped[str | None] = mapped_column(String(16))

    # sha256 hex of this source's URL-update token: lets another system push a
    # new playlist / panel URL to ``POST /api/hooks/source-url`` for a feed
    # whose address changes. Shown once, never stored; null = updates off.
    update_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    update_token_set_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    # Bumped at most once a minute, as the export token's is.
    update_token_last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime)

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
    # The *effective* logo and category: the override below when one is set,
    # else what the source says. Everything that reads a channel (guide,
    # filters, exports, the logo proxy) uses these two, so an override needs
    # no special casing downstream. Recomputed by refresh_source and by
    # set_channel_group / set_channel_logo -- never written directly.
    logo_url: Mapped[str | None] = mapped_column(Text)
    group_title: Mapped[str | None] = mapped_column(String(400))
    # What the source itself last said, kept so clearing an override restores
    # it at once rather than on the next refresh.
    upstream_logo_url: Mapped[str | None] = mapped_column(Text)
    upstream_group_title: Mapped[str | None] = mapped_column(String(400))
    # Set by hand; survive a channel refresh. Null = use the source's.
    logo_override: Mapped[str | None] = mapped_column(Text)
    group_override: Mapped[str | None] = mapped_column(String(400))
    number: Mapped[int | None] = mapped_column(Integer)
    is_hd: Mapped[bool] = mapped_column(nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Fernet-encrypted: a playable URL (m3u/xtream) or the Stalker "cmd" token.
    stream_ref_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # Set by hand when automatic matching can't link a channel to its guide:
    # the key to look this channel up by instead of ext_id / the names. A
    # tuner that numbers BBC One Scotland HD 101 while the guide carries it
    # as 1 has no other way to meet. Survives a channel refresh, which
    # overwrites everything the source owns above.
    epg_override_id: Mapped[str | None] = mapped_column(String(256))

    # Per-channel clock correction, on top of the source's shift.
    clock_shift_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Unticked on the source's channel list: left out of the guide grid,
    # now/next, search, highlights and the M3U/XMLTV exports. Still matched to
    # guide data, so showing it again is instant. Set by hand; survives a
    # channel refresh.
    hidden: Mapped[bool] = mapped_column(nullable=False, default=False, server_default=false())
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    source: Mapped[Source] = relationship(back_populates="channels")
