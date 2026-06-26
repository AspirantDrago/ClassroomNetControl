"""Add per-router TLS verification setting

Revision ID: 20260626_0004
Revises: 20260626_0003
Create Date: 2026-06-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260626_0004"
down_revision: str | None = "20260626_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "routers",
        sa.Column(
            "api_verify_tls",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("routers", "api_verify_tls")
