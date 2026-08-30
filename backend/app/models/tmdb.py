"""Global TMDB enrichment cache.

Content is public, so rows are shared across tenants; whichever tenant has a
TMDB token populates them. Keyed by (media_type, normalised title, year).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Enum, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin


class MediaType(enum.StrEnum):
    movie = "movie"
    tv = "tv"


class TmdbEnrichment(PkUuidMixin, Base):
    __tablename__ = "tmdb_enrichment"
    __table_args__ = (
        UniqueConstraint("media_type", "query_key", "query_year", name="uq_tmdb_enrichment_key"),
        Index("ix_tmdb_enrichment_fetched", "fetched_at"),
    )

    media_type: Mapped[MediaType] = mapped_column(
        Enum(MediaType, native_enum=False, length=8), nullable=False
    )
    query_key: Mapped[str] = mapped_column(String(300), nullable=False)  # normalised title
    query_year: Mapped[str] = mapped_column(String(8), nullable=False, default="")  # "" = none

    negative: Mapped[bool] = mapped_column(nullable=False, default=False)
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(500))
    release_year: Mapped[str | None] = mapped_column(String(8))
    overview: Mapped[str | None] = mapped_column(Text)
    tagline: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[float | None] = mapped_column(Float)
    runtime: Mapped[int | None] = mapped_column(Integer)
    director: Mapped[str | None] = mapped_column(Text)
    genres: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cast: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    backdrop_url: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)
