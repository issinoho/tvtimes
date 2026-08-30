"""auth_session.chain_started_at (sign-in time carried across rotations)

Revision ID: a1c7e4f9b2d0
Revises: 87bc5ff5d591
Create Date: 2026-08-31 00:35:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "a1c7e4f9b2d0"
down_revision: str | None = "87bc5ff5d591"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auth_session",
        sa.Column("chain_started_at", app.db.TZDateTime(timezone=True), nullable=True),
    )
    # Existing rows: best-effort "signed in at" = when the row was created.
    op.execute(
        "UPDATE auth_session SET chain_started_at = created_at WHERE chain_started_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("auth_session", "chain_started_at")
