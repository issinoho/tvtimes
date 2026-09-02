"""tenant activity-notification opt-ins

Revision ID: c4d7e9a1f3b6
Revises: b8e3f1a7c9d2
Create Date: 2026-09-02 10:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "c4d7e9a1f3b6"
down_revision: str | None = "b8e3f1a7c9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    "notify_on_reminder_set",
    "notify_on_title_watch_set",
    "notify_on_play",
    "notify_on_watchlist_remove",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column(
            "tenant",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("tenant", name)
