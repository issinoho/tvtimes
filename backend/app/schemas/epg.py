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
