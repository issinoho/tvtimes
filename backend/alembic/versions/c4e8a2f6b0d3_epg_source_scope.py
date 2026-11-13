"""epg_source_scope

Revision ID: c4e8a2f6b0d3
Revises: b2d6f8a4c1e7
Create Date: 2026-11-13 12:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a2f6b0d3"
down_revision: str | None = "b2d6f8a4c1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Null for every existing row: already-attached feeds stay tenant-wide.
    with op.batch_alter_table("epg_source") as batch:
        batch.add_column(sa.Column("scope_source_id", sa.Uuid(), nullable=True))
        batch.create_index("ix_epg_source_scope_source_id", ["scope_source_id"])
        batch.create_foreign_key(
            "fk_epg_source_scope_source_id_source",
            "source",
            ["scope_source_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("epg_source") as batch:
        batch.drop_constraint("fk_epg_source_scope_source_id_source", type_="foreignkey")
        batch.drop_index("ix_epg_source_scope_source_id")
        batch.drop_column("scope_source_id")
