"""Add WAN protected flag

Revision ID: 20260613_0002
Revises: 20260613_0001
Create Date: 2026-06-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260613_0002"
down_revision: str | None = "20260613_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "wan_protected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("devices", "wan_protected")
