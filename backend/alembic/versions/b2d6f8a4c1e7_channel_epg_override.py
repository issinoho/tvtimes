"""channel_epg_override

Revision ID: b2d6f8a4c1e7
Revises: a7c3e5b9d1f2
Create Date: 2026-09-03 22:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2d6f8a4c1e7"
down_revision: str | None = "a7c3e5b9d1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Null everywhere: automatic matching is unchanged unless someone sets one.
    op.add_column("channel", sa.Column("epg_override_id", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("channel", "epg_override_id")
