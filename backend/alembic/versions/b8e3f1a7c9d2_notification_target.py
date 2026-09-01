"""notification_target

Revision ID: b8e3f1a7c9d2
Revises: a3c9d1f7b2e8
Create Date: 2026-09-01 14:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "b8e3f1a7c9d2"
down_revision: str | None = "a3c9d1f7b2e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_target",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("url_encrypted", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "send_source_alerts", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("send_reminders", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
            name=op.f("fk_notification_target_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_target")),
    )
    with op.batch_alter_table("notification_target", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notification_target_tenant_id"), ["tenant_id"])


def downgrade() -> None:
    op.drop_table("notification_target")
