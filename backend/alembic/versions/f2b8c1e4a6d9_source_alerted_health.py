"""source.alerted_health

Revision ID: f2b8c1e4a6d9
Revises: e1a4c7b9d2f3
Create Date: 2026-09-01 11:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "f2b8c1e4a6d9"
down_revision: str | None = "e1a4c7b9d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source", sa.Column("alerted_health", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("source", "alerted_health")
