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


class SourceAlertsIn(BaseModel):
    enabled: bool


class ActivityNotificationsIn(BaseModel):
    """Per-tenant push opt-ins for user actions. Patch semantics — an omitted
    field is left unchanged. Push only; these never send email."""

    reminder_set: bool | None = None
    title_watch_set: bool | None = None
    play: bool | None = None
    watchlist_remove: bool | None = None
