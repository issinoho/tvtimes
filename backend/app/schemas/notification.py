from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NotificationTargetIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    # Raw Apprise URL, e.g. gotify://host/token or ntfy://host/topic.
    url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True
    send_source_alerts: bool = True
    send_reminders: bool = True


class NotificationTargetPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    enabled: bool | None = None
    send_source_alerts: bool | None = None
    send_reminders: bool | None = None


class NotificationTargetOut(BaseModel):
    id: uuid.UUID
    label: str
    service: str  # friendly Apprise service name, e.g. "Gotify"
    redacted_url: str  # token stripped — safe to show
    enabled: bool
    send_source_alerts: bool
    send_reminders: bool
    created_at: datetime
