"""export_token_last_used

Revision ID: a7c3e5b9d1f2
Revises: d5f2b8c1e7a4
Create Date: 2026-09-03 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa  # noqa: F401
from alembic import op

revision: str = "a7c3e5b9d1f2"
down_revision: str | None = "d5f2b8c1e7a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Null for every existing tenant: "never seen since this shipped", which
    # is the honest answer -- there was nothing recording it before now.
    op.add_column(
        "tenant",
        sa.Column("export_token_last_used_at", app.db.TZDateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant", "export_token_last_used_at")
