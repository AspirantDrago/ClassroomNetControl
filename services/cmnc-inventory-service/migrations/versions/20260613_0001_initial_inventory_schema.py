"""Initial inventory schema

Revision ID: 20260613_0001
Revises:
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260613_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "observed_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("router_id", sa.Integer(), nullable=False),
        sa.Column("mac_address", sa.String(length=32), nullable=False),
        sa.Column("active_ip", sa.String(length=64), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("dynamic", sa.Boolean(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "router_id",
            "mac_address",
            name="uq_observed_devices_router_mac",
        ),
    )

    op.create_index(
        "ix_observed_devices_router_id",
        "observed_devices",
        ["router_id"],
    )

    op.create_index(
        "ix_observed_devices_active_ip",
        "observed_devices",
        ["active_ip"],
    )

    op.create_index(
        "ix_observed_devices_last_seen_at",
        "observed_devices",
        ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_observed_devices_last_seen_at", table_name="observed_devices")
    op.drop_index("ix_observed_devices_active_ip", table_name="observed_devices")
    op.drop_index("ix_observed_devices_router_id", table_name="observed_devices")
    op.drop_table("observed_devices")
