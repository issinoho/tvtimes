"""Source API bodies. Create/replace uses a `kind`-discriminated union; the
kind-specific fields become the encrypted config, the rest are common options."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

_MAC = r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$"


class _CommonIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    timezone_override: str | None = Field(default=None, max_length=64)
    clock_shift_seconds: int = Field(default=0, ge=-86_400, le=86_400)
    refresh_interval_minutes: int = Field(default=360, ge=15, le=10_080)


class M3uSourceIn(_CommonIn):
    kind: Literal["m3u"] = "m3u"
    url: str = Field(min_length=1, max_length=2048)

    def config_dict(self) -> dict[str, object]:
        return {"url": self.url}


class XtreamSourceIn(_CommonIn):
    kind: Literal["xtream"] = "xtream"
    server_url: str = Field(min_length=1, max_length=2048)
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=256)
    output: str = Field(default="ts", pattern=r"^[a-z0-9]{1,8}$")

    def config_dict(self) -> dict[str, object]:
        return {
            "server_url": self.server_url,
            "username": self.username,
            "password": self.password,
            "output": self.output,
        }


class StalkerSourceIn(_CommonIn):
    kind: Literal["stalker"] = "stalker"
    portal_url: str = Field(min_length=1, max_length=2048)
    mac: str = Field(pattern=_MAC)
    serial: str | None = Field(default=None, max_length=64)
    device_id: str | None = Field(default=None, max_length=128)
    stb_type: str = Field(default="MAG250", max_length=32)

    def config_dict(self) -> dict[str, object]:
        return {
            "portal_url": self.portal_url,
            "mac": self.mac,
            "serial": self.serial,
            "device_id": self.device_id,
            "stb_type": self.stb_type,
        }


class HdhomerunSourceIn(_CommonIn):
    kind: Literal["hdhomerun"] = "hdhomerun"
    # Blank ⇒ auto-discover on the LAN (needs UDP broadcast). Otherwise the
    # tuner's address on the home network, e.g. http://192.168.1.50.
    device_url: str = Field(default="", max_length=2048)

    def config_dict(self) -> dict[str, object]:
        return {"device_url": self.device_url}


SourceIn = Annotated[
    M3uSourceIn | XtreamSourceIn | StalkerSourceIn | HdhomerunSourceIn,
    Field(discriminator="kind"),
]


class SourcePatchIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    timezone_override: str | None = Field(default=None, max_length=64)
    clock_shift_seconds: int | None = Field(default=None, ge=-86_400, le=86_400)
    refresh_interval_minutes: int | None = Field(default=None, ge=15, le=10_080)


class SourceOrderIn(BaseModel):
    # The tenant's source ids, in the desired display order.
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    display_name: str
    enabled: bool
    config_summary: str = ""  # filled by the router from the decrypted config
    timezone_override: str | None
    clock_shift_seconds: int
    refresh_interval_minutes: int
    sort_rank: int
    last_status: str
    last_error: str | None
    channel_count: int
    epg_url: str | None
    last_refreshed_at: datetime | None
    created_at: datetime

    # Rolled-up health (channel fetch + guide feed + staleness), filled by the
    # router. Defaults keep ``model_validate(source)`` happy.
    health: Literal["ok", "stale", "error"] = "ok"
    epg_status: str | None = None
    epg_error: str | None = None
    epg_last_fetched_at: datetime | None = None
    programme_count: int = 0


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    ext_id: str | None
    logo_url: str | None
    group_title: str | None
    number: int | None
    is_hd: bool


class ChannelPage(BaseModel):
    items: list[ChannelOut]
    total: int
    limit: int
    offset: int
