"""source url-update token

Revision ID: c4e8a2f6d1b7
Revises: b9d4f2a7c1e3
Create Date: 2026-11-21 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)

revision: str = "c4e8a2f6d1b7"
down_revision: str | None = "b9d4f2a7c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.add_column(sa.Column("update_token_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("update_token_set_at", app.db.TZDateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("update_token_last_used_at", app.db.TZDateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_source_update_token_hash"), ["update_token_hash"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_source_update_token_hash"))
        batch_op.drop_column("update_token_last_used_at")
        batch_op.drop_column("update_token_set_at")
        batch_op.drop_column("update_token_hash")
