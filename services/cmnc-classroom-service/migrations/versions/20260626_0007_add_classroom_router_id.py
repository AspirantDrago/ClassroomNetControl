"""Add router_id to classrooms

Revision ID: 20260626_0007
Revises: 20260624_0006
Create Date: 2026-06-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260626_0007"
down_revision: str | None = "20260624_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classrooms",
        sa.Column(
            "router_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_index("ix_classrooms_router_id", "classrooms", ["router_id"])


def downgrade() -> None:
    op.drop_index("ix_classrooms_router_id", table_name="classrooms")
    op.drop_column("classrooms", "router_id")
