"""Drop classroom RTSP fields

Revision ID: 20260624_0006
Revises: 20260624_0005
Create Date: 2026-06-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260624_0006"
down_revision: str | None = "20260624_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("classrooms", "rtsp_sub_stream")
    op.drop_column("classrooms", "rtsp_main_stream")


def downgrade() -> None:
    op.add_column(
        "classrooms",
        sa.Column("rtsp_main_stream", sa.Text(), nullable=True),
    )
    op.add_column(
        "classrooms",
        sa.Column("rtsp_sub_stream", sa.Text(), nullable=True),
    )

    op.execute(
        """
        UPDATE classrooms AS c
        SET
            rtsp_main_stream = cc.rtsp_main_stream,
            rtsp_sub_stream = cc.rtsp_sub_stream
        FROM classroom_cameras AS cc
        WHERE cc.id = (
            SELECT cc2.id
            FROM classroom_cameras AS cc2
            WHERE cc2.classroom_id = c.id
            ORDER BY cc2.sort_order, cc2.id
            LIMIT 1
        )
        """
    )
