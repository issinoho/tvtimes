from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --- tenant-facing ---------------------------------------------------------


class ConnectorCreateIn(BaseModel):
    name: str = Field(default="Home network", min_length=1, max_length=120)


class ConnectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    version: str | None
    last_seen_at: datetime | None
    pairing_code: str | None
    pairing_expires_at: datetime | None
    devices: list[dict[str, Any]]
    source_id: uuid.UUID | None
    created_at: datetime


class ConnectorCreatedOut(ConnectorOut):
    install_hint: str


# --- connector-facing ----------------------------------------------------------


class PairIn(BaseModel):
    code: str = Field(min_length=4, max_length=16)


class PairOut(BaseModel):
    connector_id: uuid.UUID
    token: str
    heartbeat_interval: int


class HeartbeatIn(BaseModel):
    version: str | None = Field(default=None, max_length=40)


class HeartbeatOut(BaseModel):
    ok: bool = True
    heartbeat_interval: int


class LineupChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=400)
    stream_url: str = Field(min_length=1, max_length=2048)
    number: int | None = Field(default=None, ge=0, le=100_000)
    hd: bool = False


class LineupIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    friendly_name: str = Field(default="HDHomeRun", max_length=120)
    model: str | None = Field(default=None, max_length=64)
    tuner_count: int | None = Field(default=None, ge=0, le=64)
    epg_url: str | None = Field(default=None, max_length=2048)
    channels: list[LineupChannelIn] = Field(default_factory=list, max_length=5000)


class LineupOut(BaseModel):
    ok: bool = True
    channels: int
