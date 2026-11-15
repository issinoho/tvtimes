"""paired_device

Revision ID: a7c3e9f1b5d2
Revises: c4e8a2f6b0d3
Create Date: 2026-11-15 23:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9f1b5d2"
down_revision: str | None = "c4e8a2f6b0d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paired_device",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("pairing_code", sa.String(length=16), nullable=True),
        sa.Column("poll_secret_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", app.db.TZDateTime(), nullable=True),
        sa.Column("approved_at", app.db.TZDateTime(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("last_used_at", app.db.TZDateTime(), nullable=True),
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
            name=op.f("fk_paired_device_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paired_device")),
    )
    with op.batch_alter_table("paired_device", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_paired_device_tenant_id"), ["tenant_id"])
        batch_op.create_index(
            batch_op.f("ix_paired_device_pairing_code"), ["pairing_code"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_paired_device_poll_secret_hash"), ["poll_secret_hash"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_paired_device_token_hash"), ["token_hash"], unique=True
        )


def downgrade() -> None:
    op.drop_table("paired_device")
