"""Remember per-router DHCP snapshot ordering, including empty snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "20261110_0005"
down_revision = "20260626_0004"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("routers", sa.Column("dhcp_snapshot_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column("routers", "dhcp_snapshot_at")
