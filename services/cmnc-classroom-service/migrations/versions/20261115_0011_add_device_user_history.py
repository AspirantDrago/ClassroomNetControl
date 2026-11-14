"""Store Veyon user observations and bounded history intervals."""
from alembic import op
import sqlalchemy as sa

revision = "20261115_0011"
down_revision = "20261108_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("device_user_state",
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("known", sa.Boolean(), nullable=False),
        sa.Column("username", sa.String(256), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))
    op.create_table("device_user_intervals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("username", sa.String(256), nullable=True))
    op.create_index("ix_device_user_intervals_device_start", "device_user_intervals", ["device_id", "start_at"])


def downgrade():
    op.drop_index("ix_device_user_intervals_device_start", table_name="device_user_intervals")
    op.drop_table("device_user_intervals")
    op.drop_table("device_user_state")
