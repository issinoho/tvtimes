"""channel group/logo override

Revision ID: b9d4f2a7c1e3
Revises: a7c3e9f1b5d2
Create Date: 2026-11-21 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d4f2a7c1e3"
down_revision: str | None = "a7c3e9f1b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("channel", schema=None) as batch_op:
        batch_op.add_column(sa.Column("upstream_logo_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("upstream_group_title", sa.String(length=400), nullable=True))
        batch_op.add_column(sa.Column("logo_override", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("group_override", sa.String(length=400), nullable=True))
    # No overrides exist yet, so today's effective values are the source's.
    op.execute(
        "UPDATE channel SET upstream_logo_url = logo_url, upstream_group_title = group_title"
    )


def downgrade() -> None:
    # Leave the effective columns as they are (overrides applied): dropping
    # the override columns is all a rollback needs.
    with op.batch_alter_table("channel", schema=None) as batch_op:
        batch_op.drop_column("group_override")
        batch_op.drop_column("logo_override")
        batch_op.drop_column("upstream_group_title")
        batch_op.drop_column("upstream_logo_url")
