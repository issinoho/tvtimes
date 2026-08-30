"""A paired LAN agent that reports HDHomeRun lineups from a home network."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin


class ConnectorStatus(enum.StrEnum):
    unpaired = "unpaired"
    online = "online"
    offline = "offline"


class Connector(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "connector"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # One-time pairing code, cleared once claimed.
    pairing_code: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
    pairing_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    # sha256 hex of the long-lived connector token (the token itself is never stored).
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    version: Mapped[str | None] = mapped_column(String(40))
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    # Last-reported device summary: [{device_id, friendly_name, model, tuner_count}]
    discovered: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    @property
    def is_paired(self) -> bool:
        return self.token_hash is not None
