"""source advertised epg urls

Revision ID: d7a3e9b2c5f1
Revises: c4e8a2f6d1b7
Create Date: 2026-11-21 23:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3e9b2c5f1"
down_revision: str | None = "c4e8a2f6d1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "advertised_epg_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("source", schema=None) as batch_op:
        batch_op.drop_column("advertised_epg_urls")
