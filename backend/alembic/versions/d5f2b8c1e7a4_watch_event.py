"""watch_event

Revision ID: d5f2b8c1e7a4
Revises: c4d7e9a1f3b6
Create Date: 2026-09-03 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "d5f2b8c1e7a4"
down_revision: str | None = "c4d7e9a1f3b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watch_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", app.db.TZDateTime(), nullable=False),
        sa.Column("ended_at", app.db.TZDateTime(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("device", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            app.db.TZDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            app.db.TZDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name=op.f("fk_watch_event_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channel.id"],
            name=op.f("fk_watch_event_channel_id_channel"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watch_event")),
        sa.UniqueConstraint("channel_id", "started_at", name="uq_watch_event_channel_start"),
    )
    with op.batch_alter_table("watch_event", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_watch_event_tenant_id"), ["tenant_id"])
        batch_op.create_index(batch_op.f("ix_watch_event_channel_id"), ["channel_id"])
        batch_op.create_index("ix_watch_event_tenant_started", ["tenant_id", "started_at"])


def downgrade() -> None:
    op.drop_table("watch_event")
