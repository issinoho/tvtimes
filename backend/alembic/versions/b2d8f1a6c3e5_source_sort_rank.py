"""source.sort_rank (user-defined source order)

Revision ID: b2d8f1a6c3e5
Revises: a1c7e4f9b2d0
Create Date: 2026-08-31 01:05:00.000000
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "b2d8f1a6c3e5"
down_revision: str | None = "a1c7e4f9b2d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source",
        sa.Column("sort_rank", sa.Integer(), nullable=False, server_default="0"),
    )
    # Seed a stable order for existing rows: oldest source first, per tenant.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, tenant_id FROM source ORDER BY tenant_id, created_at")
    ).fetchall()
    counters: dict[object, int] = defaultdict(int)
    for row_id, tenant_id in rows:
        bind.execute(
            sa.text("UPDATE source SET sort_rank = :rank WHERE id = :id"),
            {"rank": counters[tenant_id], "id": row_id},
        )
        counters[tenant_id] += 1


def downgrade() -> None:
    op.drop_column("source", "sort_rank")
