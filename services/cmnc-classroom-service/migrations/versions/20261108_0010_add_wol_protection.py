"""Add per-device protection from classroom-wide Wake-on-LAN."""
from alembic import op
import sqlalchemy as sa

revision = "20261108_0010"
down_revision = "20261108_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("wol_protected", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("devices", "wol_protected")
