"""channel hidden

Revision ID: e1c6b8d4a2f9
Revises: d7a3e9b2c5f1
Create Date: 2026-11-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1c6b8d4a2f9"
down_revision: str | None = "d7a3e9b2c5f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("channel", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("channel", schema=None) as batch_op:
        batch_op.drop_column("hidden")
