from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --- device-facing (unauthenticated) ----------------------------------------


class PairingStartIn(BaseModel):
    name: str = Field(default="TV", max_length=120)


class PairingStartOut(BaseModel):
    code: str
    poll_secret: str
    expires_in: int
    interval: int


class PairingPollIn(BaseModel):
    poll_secret: str = Field(min_length=1, max_length=200)


class PairingPollOut(BaseModel):
    status: Literal["pending", "approved"]
    # Only with "approved", and only on that one response.
    token: str | None = None
    # The address tvtimes' own links use (TVTIMES_PUBLIC_ORIGIN); a device
    # should prefer it when it can reach it, so its stream URLs and the
    # playlist's agree.
    origin: str | None = None


# --- tenant-facing ------------------------------------------------------------


class DeviceApproveIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    approved_at: datetime | None
    last_used_at: datetime | None
    # False between approval and the device collecting its token.
    paired: bool
