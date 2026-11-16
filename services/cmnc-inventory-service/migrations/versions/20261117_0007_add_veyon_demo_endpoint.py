"""Store the recipient-visible demonstration address per MikroTik."""
from alembic import op
import sqlalchemy as sa

revision = '20261117_0007'
down_revision = '20261113_0006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('routers', sa.Column('veyon_demo_host', sa.String(253), nullable=True))
    op.add_column('routers', sa.Column('veyon_demo_port', sa.Integer(), nullable=False, server_default='11400'))


def downgrade():
    op.drop_column('routers', 'veyon_demo_port')
    op.drop_column('routers', 'veyon_demo_host')
