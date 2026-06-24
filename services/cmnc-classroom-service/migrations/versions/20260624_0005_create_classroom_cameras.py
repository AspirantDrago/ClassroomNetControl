"""Create classroom cameras table

Revision ID: 20260624_0005
Revises: 20260624_0004
Create Date: 2026-06-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260624_0005"
down_revision: str | None = "20260624_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classroom_cameras",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("classroom_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("rtsp_main_stream", sa.Text(), nullable=True),
        sa.Column("rtsp_sub_stream", sa.Text(), nullable=True),
        sa.Column("default_quality", sa.String(length=16), nullable=False, server_default="sub"),
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
        sa.CheckConstraint("default_quality IN ('main', 'sub')", name="ck_classroom_cameras_default_quality"),
        sa.ForeignKeyConstraint(["classroom_id"], ["classrooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "classroom_id",
            "sort_order",
            name="uq_classroom_cameras_classroom_sort_order",
        ),
    )
    op.create_index(
        "ix_classroom_cameras_classroom_id",
        "classroom_cameras",
        ["classroom_id"],
    )

    op.execute(
        """
        INSERT INTO classroom_cameras (
            classroom_id,
            name,
            sort_order,
            is_enabled,
            rtsp_main_stream,
            rtsp_sub_stream,
            default_quality,
            created_at,
            updated_at
        )
        SELECT
            id,
            'Основная камера',
            0,
            true,
            NULLIF(BTRIM(rtsp_main_stream), ''),
            NULLIF(BTRIM(rtsp_sub_stream), ''),
            CASE
                WHEN rtsp_sub_stream IS NOT NULL AND BTRIM(rtsp_sub_stream) <> '' THEN 'sub'
                ELSE 'main'
            END,
            now(),
            now()
        FROM classrooms
        WHERE
            (rtsp_main_stream IS NOT NULL AND BTRIM(rtsp_main_stream) <> '')
            OR (rtsp_sub_stream IS NOT NULL AND BTRIM(rtsp_sub_stream) <> '')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_classroom_cameras_classroom_id", table_name="classroom_cameras")
    op.drop_table("classroom_cameras")
