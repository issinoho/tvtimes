from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EpgSourceIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class EpgSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    source_id: uuid.UUID | None
    last_status: str
    last_error: str | None
    programme_count: int
    last_fetched_at: datetime | None
    refresh_interval_minutes: int
    created_at: datetime


class ProgrammeOut(BaseModel):
    id: uuid.UUID
    start: datetime
    stop: datetime
    title: str
    sub_title: str | None
    description: str | None
    categories: list[str]
    episode_num: str | None
    year: str | None
    icon_url: str | None
    director: str | None
    is_movie: bool
    # True when a player has reported watching enough of this airing — see
    # app.services.watch. Always False for an account with nothing reporting.
    watched: bool = False


class ScheduleOut(BaseModel):
    channel_id: uuid.UUID
    channel_name: str
    timezone: str
    programmes: list[ProgrammeOut]


class GuideChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    number: int | None
    logo_url: str | None
    group_title: str | None
    is_hd: bool
    timezone: str
    clock_shift_seconds: int
    programmes: list[ProgrammeOut]


class SearchChannelOut(BaseModel):
    """The channel context for a search hit — GuideChannelOut without the
    per-row programme list."""

    id: uuid.UUID
    name: str
    number: int | None
    logo_url: str | None
    group_title: str | None
    is_hd: bool
    timezone: str
    clock_shift_seconds: int


class SearchHitOut(BaseModel):
    channel: SearchChannelOut
    programme: ProgrammeOut


class SearchOut(BaseModel):
    query: str
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    results: list[SearchHitOut]


class NowNextRowOut(BaseModel):
    channel: SearchChannelOut
    current: ProgrammeOut | None
    upcoming: ProgrammeOut | None


class NowNextOut(BaseModel):
    now: datetime
    channels: list[NowNextRowOut]


class HighlightsOut(BaseModel):
    films_soon: list[SearchHitOut]
    top_rated: list[SearchHitOut]


class ChannelPatchIn(BaseModel):
    """Patch semantics: an omitted field is left alone."""

    # Added to every programme time for this channel - e.g. +10800 to line a
    # US-West feed up with an East-coast EPG. Clamped to +/- 24h.
    clock_shift_seconds: int | None = Field(default=None, ge=-86_400, le=86_400)
    # The guide key to match this channel on, when the automatic ones don't.
    # Empty string clears it and restores automatic matching -- None means
    # "not supplied", which is how an empty text input has to reach us.
    epg_override_id: str | None = Field(default=None, max_length=256)


class ChannelPatchOut(BaseModel):
    id: uuid.UUID
    clock_shift_seconds: int
    epg_override_id: str | None = None


class PlayLinkOut(BaseModel):
    m3u_url: str  # absolute; carries ?ticket=<jwt>; downloads as a one-channel .m3u
    stream_url: str  # absolute; carries ?ticket=<jwt>; 302s to the upstream stream
    expires_in: int  # seconds until the ticket expires


class GuideOut(BaseModel):
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    channels: list[GuideChannelOut]
