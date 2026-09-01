"""favourite_channel

Revision ID: e1a4c7b9d2f3
Revises: d7f3a9c1b8e4
Create Date: 2026-09-01 10:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "e1a4c7b9d2f3"
down_revision: str | None = "d7f3a9c1b8e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "favourite_channel",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
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
            name=op.f("fk_favourite_channel_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name=op.f("fk_favourite_channel_user_id_user_account"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channel.id"],
            name=op.f("fk_favourite_channel_channel_id_channel"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_favourite_channel")),
        sa.UniqueConstraint("user_id", "channel_id", name="uq_favourite_channel_user_channel"),
    )
    with op.batch_alter_table("favourite_channel", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_favourite_channel_tenant_id"), ["tenant_id"])
        batch_op.create_index(batch_op.f("ix_favourite_channel_user_id"), ["user_id"])
        batch_op.create_index(batch_op.f("ix_favourite_channel_channel_id"), ["channel_id"])


def downgrade() -> None:
    op.drop_table("favourite_channel")
