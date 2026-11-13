"""Reserve deleted classrooms against new access assignments."""
from alembic import op
import sqlalchemy as sa

revision = "20261113_0004"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("classroom_deletion_guards",
        sa.Column("classroom_id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False))


def downgrade():
    op.drop_table("classroom_deletion_guards")
