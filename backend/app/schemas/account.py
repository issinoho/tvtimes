from __future__ import annotations

from datetime import datetime

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


class ReportingDeviceOut(BaseModel):
    """One player that has reported watch state. `name` is null for a
    reporter that sent no device label."""

    name: str | None = None
    last_reported_at: datetime
    events: int


class ExportActivityOut(BaseModel):
    """What's actually using the export feeds — the answer to "is the
    living-room box still talking to me?", which nothing else surfaced."""

    token_set_at: datetime | None = None
    last_used_at: datetime | None = None
    devices: list[ReportingDeviceOut] = []
