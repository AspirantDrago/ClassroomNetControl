"""Add per-device protection from classroom-wide Veyon actions."""
from alembic import op
import sqlalchemy as sa

revision = "20261108_0009"
down_revision = "20260713_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("veyon_bulk_protected", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("devices", "veyon_bulk_protected")
