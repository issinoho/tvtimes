from __future__ import annotations

from pydantic import BaseModel, Field


class TimezoneIn(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)


class TmdbTokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=1024)


class ExportTokenOut(BaseModel):
    token: str
    playlist_url: str
    epg_url: str
