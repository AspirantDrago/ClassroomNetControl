"""Initial schema

Revision ID: 20260614_0001
Revises:
Create Date: 2026-06-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import INET


revision: str = "20260614_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("level"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "workstations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("ip_address", INET(), nullable=False),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint("ip_address"),
    )

    op.create_table(
        "classroom_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "workstation_id",
            sa.Integer(),
            sa.ForeignKey("workstations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "classroom_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            """
            (
                user_id IS NOT NULL
                AND workstation_id IS NULL
            )
            OR
            (
                user_id IS NULL
                AND workstation_id IS NOT NULL
            )
            """,
            name="ck_classroom_access_single_principal",
        ),
        sa.UniqueConstraint(
            "user_id",
            "classroom_id",
            name="uq_classroom_access_user",
        ),
        sa.UniqueConstraint(
            "workstation_id",
            "classroom_id",
            name="uq_classroom_access_workstation",
        ),
    )

    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("id", sa.Integer),
            sa.column("name", sa.String),
            sa.column("level", sa.Integer),
        ),
        [
            {"id": 1, "name": "workstation", "level": 10},
            {"id": 2, "name": "teacher", "level": 20},
            {"id": 3, "name": "moderator", "level": 50},
            {"id": 4, "name": "admin", "level": 80},
            {"id": 5, "name": "superadmin", "level": 100},
        ],
    )

    op.create_index(
        "ix_classroom_access_user_id",
        "classroom_access",
        ["user_id"],
    )

    op.create_index(
        "ix_classroom_access_workstation_id",
        "classroom_access",
        ["workstation_id"],
    )

    op.create_index(
        "ix_classroom_access_classroom_id",
        "classroom_access",
        ["classroom_id"],
    )

    op.create_index(
        "ix_roles_level",
        "roles",
        ["level"],
    )


def downgrade() -> None:
    op.drop_table("classroom_access")
    op.drop_table("workstations")
    op.drop_table("users")
    op.drop_table("roles")
