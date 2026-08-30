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


class ChannelPatchIn(BaseModel):
    # Added to every programme time for this channel - e.g. +10800 to line a
    # US-West feed up with an East-coast EPG. Clamped to +/- 24h.
    clock_shift_seconds: int = Field(ge=-86_400, le=86_400)


class ChannelShiftOut(BaseModel):
    id: uuid.UUID
    clock_shift_seconds: int


class GuideOut(BaseModel):
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    channels: list[GuideChannelOut]
