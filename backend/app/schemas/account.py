from __future__ import annotations

from pydantic import BaseModel, Field


class TimezoneIn(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
