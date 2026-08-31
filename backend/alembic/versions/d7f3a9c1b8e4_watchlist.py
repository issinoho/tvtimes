"""watchlist_item + watchlist_notification

Revision ID: d7f3a9c1b8e4
Revises: c4a1e7d92f30
Create Date: 2026-08-31 15:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import app.db  # noqa: F401  custom column types (app.db.TZDateTime)
import sqlalchemy as sa
from alembic import op

revision: str = "d7f3a9c1b8e4"
down_revision: str | None = "c4a1e7d92f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watchlist_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title_display", sa.String(length=500), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=True),
        sa.Column("start_utc", app.db.TZDateTime(), nullable=True),
        sa.Column("stop_utc", app.db.TZDateTime(), nullable=True),
        sa.Column("title_norm", sa.String(length=500), nullable=True),
        sa.Column("lead_minutes", sa.Integer(), nullable=False, server_default="15"),
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
            name=op.f("fk_watchlist_item_tenant_id_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name=op.f("fk_watchlist_item_user_id_user_account"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channel.id"],
            name=op.f("fk_watchlist_item_channel_id_channel"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist_item")),
    )
    with op.batch_alter_table("watchlist_item", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_watchlist_item_tenant_id"), ["tenant_id"])
        batch_op.create_index(batch_op.f("ix_watchlist_item_user_id"), ["user_id"])
        batch_op.create_index(batch_op.f("ix_watchlist_item_channel_id"), ["channel_id"])
        batch_op.create_index(batch_op.f("ix_watchlist_item_title_norm"), ["title_norm"])

    op.create_table(
        "watchlist_notification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("watchlist_item_id", sa.Uuid(), nullable=False),
        sa.Column("airing_key", sa.String(length=80), nullable=False),
        sa.Column("sent_at", app.db.TZDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["watchlist_item_id"],
            ["watchlist_item.id"],
            name=op.f("fk_watchlist_notification_watchlist_item_id_watchlist_item"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist_notification")),
        sa.UniqueConstraint(
            "watchlist_item_id", "airing_key", name="uq_watchlist_notification_item_airing"
        ),
    )
    with op.batch_alter_table("watchlist_notification", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_watchlist_notification_watchlist_item_id"), ["watchlist_item_id"]
        )


def downgrade() -> None:
    op.drop_table("watchlist_notification")
    op.drop_table("watchlist_item")
