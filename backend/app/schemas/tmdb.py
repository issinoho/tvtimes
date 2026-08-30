from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CastMember(BaseModel):
    name: str
    character: str = ""


class EnrichmentOut(BaseModel):
    tmdb_id: int | None
    title: str | None
    release_year: str | None
    overview: str | None
    tagline: str | None
    rating: float | None
    runtime: int | None
    director: str | None
    genres: list[str]
    cast: list[CastMember]
    backdrop_url: str | None
    poster_url: str | None
    logo_url: str | None


class HeroOut(BaseModel):
    programme_id: uuid.UUID
    channel_name: str
    title: str
    sub_title: str | None
    start: datetime
    stop: datetime
    description: str | None
    categories: list[str]
    episode_num: str | None
    year: str | None
    is_movie: bool
    tmdb_connected: bool
    enriching: bool
    enrichment: EnrichmentOut | None
