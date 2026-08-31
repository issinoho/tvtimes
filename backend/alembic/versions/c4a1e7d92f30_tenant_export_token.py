"""tenant export token (M3U / XMLTV feed auth)

Revision ID: c4a1e7d92f30
Revises: b2d8f1a6c3e5
Create Date: 2026-08-31 13:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "c4a1e7d92f30"
down_revision: str | None = "b2d8f1a6c3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("export_token_hash", sa.String(length=64), nullable=True))
    op.add_column("tenant", sa.Column("export_token_set_at", app.db.TZDateTime(), nullable=True))
    op.create_index("ix_tenant_export_token_hash", "tenant", ["export_token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_tenant_export_token_hash", table_name="tenant")
    op.drop_column("tenant", "export_token_set_at")
    op.drop_column("tenant", "export_token_hash")
