"""Create routers and router service status

Revision ID: 20260626_0002
Revises: 20260613_0001
Create Date: 2026-06-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260626_0002"
down_revision: str | None = "20260613_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "routers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("api_host", sa.String(length=255), nullable=False),
        sa.Column("api_port", sa.Integer(), nullable=False, server_default=sa.text("8728")),
        sa.Column("api_use_ssl", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("api_username", sa.String(length=255), nullable=False),
        sa.Column("api_password", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("poll_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_routers_is_enabled", "routers", ["is_enabled"])

    op.execute(
        """
        INSERT INTO routers (
            id,
            name,
            api_host,
            api_port,
            api_use_ssl,
            api_username,
            api_password,
            is_enabled,
            poll_enabled,
            sync_enabled,
            poll_interval_seconds
        )
        VALUES (
            1,
            'Default MikroTik',
            '127.0.0.1',
            8728,
            false,
            'cmnc',
            '',
            false,
            true,
            true,
            10
        )
        ON CONFLICT (id) DO NOTHING
        """
    )

    op.create_foreign_key(
        "fk_observed_devices_router_id_routers",
        "observed_devices",
        "routers",
        ["router_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "router_service_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("router_id", sa.Integer(), nullable=False),
        sa.Column("service_name", sa.String(length=64), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="starting"),
        sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["router_id"], ["routers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "router_id",
            "service_name",
            name="uq_router_service_status_router_service",
        ),
    )

    op.create_index(
        "ix_router_service_status_router_id",
        "router_service_status",
        ["router_id"],
    )
    op.create_index(
        "ix_router_service_status_status",
        "router_service_status",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_router_service_status_status", table_name="router_service_status")
    op.drop_index("ix_router_service_status_router_id", table_name="router_service_status")
    op.drop_table("router_service_status")
    op.drop_constraint(
        "fk_observed_devices_router_id_routers",
        "observed_devices",
        type_="foreignkey",
    )
    op.drop_index("ix_routers_is_enabled", table_name="routers")
    op.drop_table("routers")
