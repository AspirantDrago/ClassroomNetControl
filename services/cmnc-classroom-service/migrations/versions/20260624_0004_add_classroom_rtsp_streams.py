"""Add RTSP stream fields to classrooms

Revision ID: 20260624_0004
Revises: 20260618_0003
Create Date: 2026-06-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260624_0004"
down_revision: str | None = "20260618_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classrooms",
        sa.Column("rtsp_main_stream", sa.Text(), nullable=True),
    )
    op.add_column(
        "classrooms",
        sa.Column("rtsp_sub_stream", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("classrooms", "rtsp_sub_stream")
    op.drop_column("classrooms", "rtsp_main_stream")
