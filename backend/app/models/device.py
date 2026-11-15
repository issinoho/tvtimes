"""A TV (or other player) paired to an account through the find-and-approve
flow, holding its own export token.

The device starts the pairing itself, unauthenticated (``POST
/api/pairing/start``): a row with no tenant, a short code it shows on screen
and the sha256 of a poll secret only it knows. Someone signed in enters the
code under Settings -> Devices, which attaches the row to their tenant. The
device's next poll mints its export token -- returned once, only its sha256
kept -- and from then on it reads ``/api/exports/*`` like the account's own
token does, until it is removed. Pending rows that are never approved
expire and are swept away.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TZDateTime
from app.models.base import PkUuidMixin, TimestampMixin


class PairedDevice(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "paired_device"

    # Null until someone approves the code; the account it then belongs to.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # What the device calls itself (e.g. "Living room Fire TV"), shown in the list.
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Shown on the TV; cleared once approved.
    pairing_code: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
    # sha256 of the secret the device polls with; cleared once it has its token.
    poll_secret_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    # Until when the code can be approved (pending) or the token collected (approved).
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    approved_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    # sha256 of the device's own export token. Set once the device collects it.
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    # Bumped at most once a minute, as the account token's is.
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime)
