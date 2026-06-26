"""Fix router table sequences after explicit seed ids

Revision ID: 20260626_0003
Revises: 20260626_0002
Create Date: 2026-06-26
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260626_0003"
down_revision: str | None = "20260626_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            max_router_id bigint;
            max_status_id bigint;
        BEGIN
            SELECT MAX(id) INTO max_router_id FROM routers;

            IF max_router_id IS NULL THEN
                PERFORM setval(pg_get_serial_sequence('routers', 'id'), 1, false);
            ELSE
                PERFORM setval(pg_get_serial_sequence('routers', 'id'), max_router_id, true);
            END IF;

            SELECT MAX(id) INTO max_status_id FROM router_service_status;

            IF max_status_id IS NULL THEN
                PERFORM setval(pg_get_serial_sequence('router_service_status', 'id'), 1, false);
            ELSE
                PERFORM setval(pg_get_serial_sequence('router_service_status', 'id'), max_status_id, true);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    pass
