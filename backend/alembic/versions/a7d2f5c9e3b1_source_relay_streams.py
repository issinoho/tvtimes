"""source relay streams

Revision ID: a7d2f5c9e3b1
Revises: e1c6b8d4a2f9
Create Date: 2026-11-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d2f5c9e3b1"
down_revision: str | None = "e1c6b8d4a2f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("relay_streams", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # Directly-added HDHomeRun tuners are LAN-only, so relay them by default.
    op.execute("UPDATE source SET relay_streams = TRUE WHERE kind = 'hdhomerun'")


def downgrade() -> None:
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.drop_column("relay_streams")
