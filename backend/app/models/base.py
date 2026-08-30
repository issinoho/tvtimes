"""Shared model mixins."""

from __future__ import annotations

import uuid

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampMixin

__all__ = ["PkUuidMixin", "TimestampMixin"]


class PkUuidMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
