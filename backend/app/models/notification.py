"""Per-tenant push notification targets.

Each row is one Apprise URL (Gotify / ntfy / Discord / …), Fernet-encrypted
because it usually carries a token. Delivery fans out to every enabled target;
it runs alongside — never replaces — the email path.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import PkUuidMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class NotificationTarget(PkUuidMixin, TimestampMixin, Base):
    __tablename__ = "notification_target"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    # Fernet-encrypted Apprise URL (app.auth.crypto).
    url_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    send_source_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    send_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tenant: Mapped[Tenant] = relationship()
