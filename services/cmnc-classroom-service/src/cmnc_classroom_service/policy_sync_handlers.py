import logging

from aio_pika import IncomingMessage
from sqlalchemy import update

from cmnc_contracts.events import PolicySyncCompletedEvent, PolicySyncFailedEvent

from cmnc_classroom_service.db import async_session_maker
from cmnc_classroom_service.models import Device

logger = logging.getLogger(__name__)


async def handle_policy_sync_completed(message: IncomingMessage) -> None:
    async with message.process(requeue=False):
        event = PolicySyncCompletedEvent.model_validate_json(message.body)

        logger.info(
            "Received policy sync completed: router_id=%s, generation=%s",
            event.router_id,
            event.policy_generation,
        )

        async with async_session_maker() as session:
            result = await session.execute(
                update(Device)
                .where(Device.sync_status == "pending")
                .where(Device.policy_generation <= event.policy_generation)
                .values(
                    sync_status="applied",
                    sync_error=None,
                )
            )

            await session.commit()

        logger.info(
            "Policy sync completed applied to %s devices",
            result.rowcount,
        )


async def handle_policy_sync_failed(message: IncomingMessage) -> None:
    async with message.process(requeue=False):
        event = PolicySyncFailedEvent.model_validate_json(message.body)

        logger.warning(
            "Received policy sync failed: router_id=%s, generation=%s, error=%s",
            event.router_id,
            event.policy_generation,
            event.error,
        )

        async with async_session_maker() as session:
            result = await session.execute(
                update(Device)
                .where(Device.sync_status == "pending")
                .where(Device.policy_generation <= event.policy_generation)
                .values(
                    sync_status="failed",
                    sync_error=event.error,
                )
            )

            await session.commit()

        logger.warning(
            "Policy sync failed applied to %s devices",
            result.rowcount,
        )
