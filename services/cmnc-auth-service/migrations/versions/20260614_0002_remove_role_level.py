"""Remove role level

Revision ID: 20260614_0002
Revises: 20260614_0001
Create Date: 2026-06-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260614_0002"
down_revision: str | None = "20260614_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_roles_level", table_name="roles")
    op.drop_constraint("roles_level_key", "roles", type_="unique")
    op.drop_column("roles", "level")


def downgrade() -> None:
    op.add_column(
        "roles",
        sa.Column("level", sa.Integer(), nullable=True),
    )

    op.execute(
        """
        UPDATE roles
        SET level = CASE name
            WHEN 'workstation' THEN 10
            WHEN 'teacher' THEN 20
            WHEN 'moderator' THEN 50
            WHEN 'admin' THEN 80
            WHEN 'superadmin' THEN 100
        END
        """
    )

    op.alter_column("roles", "level", nullable=False)
    op.create_unique_constraint("roles_level_key", "roles", ["level"])
    op.create_index("ix_roles_level", "roles", ["level"])
