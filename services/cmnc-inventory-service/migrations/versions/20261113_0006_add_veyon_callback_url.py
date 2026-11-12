"""Configure a client-reachable CMNC callback URL per router."""
from alembic import op
import sqlalchemy as sa
revision = "20261113_0006"
down_revision = "20261110_0005"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("routers", sa.Column("veyon_callback_url", sa.String(2048), nullable=True))

def downgrade():
    op.drop_column("routers", "veyon_callback_url")
