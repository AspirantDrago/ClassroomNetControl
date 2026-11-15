"""Exclude non-PC devices from Veyon."""
from alembic import op
import sqlalchemy as sa
revision="20261115_0012"
down_revision="20261115_0011"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("devices",sa.Column("is_non_pc",sa.Boolean(),nullable=False,server_default=sa.false()))

def downgrade():
    op.drop_column("devices","is_non_pc")
