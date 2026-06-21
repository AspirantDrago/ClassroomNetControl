"""Add service classroom flag

Revision ID: 20260618_0003
Revises: 20260613_0002
Create Date: 2026-06-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260618_0003"
down_revision: str | None = "20260613_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classrooms",
        sa.Column(
            "is_service",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.execute("UPDATE classrooms SET is_service = false WHERE is_service IS NULL")


def downgrade() -> None:
    op.drop_column("classrooms", "is_service")
