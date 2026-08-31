from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class WatchlistAddIn(BaseModel):
    kind: Literal["programme", "title"]
    programme_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=500)
    lead_minutes: int = Field(default=15, ge=1, le=180)

    @model_validator(mode="after")
    def _check(self) -> WatchlistAddIn:
        if self.kind == "programme" and self.programme_id is None:
            raise ValueError("programme_id is required for kind=programme")
        if self.kind == "title" and not (self.title and self.title.strip()):
            raise ValueError("title is required for kind=title")
        return self


class WatchlistItemOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    lead_minutes: int
    created_at: datetime
    # kind=programme, or the next match for kind=title
    channel_id: uuid.UUID | None = None
    channel_name: str | None = None
    start: datetime | None = None
    stop: datetime | None = None
    timezone: str | None = None


class WatchlistOut(BaseModel):
    items: list[WatchlistItemOut]
