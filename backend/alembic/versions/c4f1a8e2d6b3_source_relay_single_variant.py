"""source relay single variant

Revision ID: c4f1a8e2d6b3
Revises: a7d2f5c9e3b1
Create Date: 2026-11-28 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f1a8e2d6b3"
down_revision: str | None = "a7d2f5c9e3b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "relay_single_variant", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.drop_column("relay_single_variant")
