"""tenant.source_alerts_enabled

Revision ID: a3c9d1f7b2e8
Revises: f2b8c1e4a6d9
Create Date: 2026-09-01 12:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "a3c9d1f7b2e8"
down_revision: str | None = "f2b8c1e4a6d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column(
            "source_alerts_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant", "source_alerts_enabled")
