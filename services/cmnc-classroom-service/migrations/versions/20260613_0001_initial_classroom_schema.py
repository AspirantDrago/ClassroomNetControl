"""Initial classroom schema

Revision ID: 20260613_0001
Revises:
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260613_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classrooms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("subnet_cidr", sa.String(length=64), nullable=False),
        sa.Column("vlan_id", sa.Integer(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("classroom_id", sa.Integer(), nullable=False),
        sa.Column("mac_address", sa.String(length=32), nullable=False),
        sa.Column("inventory_name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("static_ip", sa.String(length=64), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("column_index", sa.Integer(), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("wan_allowed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("policy_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sync_status", sa.String(length=32), nullable=False, server_default=sa.text("'applied'")),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["classroom_id"], ["classrooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mac_address", name="uq_devices_mac_address"),
        sa.UniqueConstraint(
            "classroom_id",
            "row_index",
            "column_index",
            name="uq_devices_classroom_grid_position",
        ),
    )


def downgrade() -> None:
    op.drop_table("devices")
    op.drop_table("classrooms")
