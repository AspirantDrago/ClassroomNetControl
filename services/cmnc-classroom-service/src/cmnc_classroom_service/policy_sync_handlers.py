import logging

from aio_pika import IncomingMessage
from sqlalchemy import select, tuple_, update

from cmnc_contracts.events import PolicySyncCompletedEvent, PolicySyncFailedEvent

from cmnc_classroom_service.db import async_session_maker
from cmnc_classroom_service.models import Classroom, Device

logger = logging.getLogger(__name__)


async def handle_policy_sync_completed(message: IncomingMessage) -> None:
    async with message.process(requeue=False):
        event = PolicySyncCompletedEvent.model_validate_json(message.body)

        logger.info(
            "Received policy sync completed: router_id=%s, generation=%s",
            event.router_id,
            event.policy_generation,
        )

        if event.device_generations is None:
            logger.warning("Ignoring legacy sync result without device snapshot: router_id=%s", event.router_id)
            return
        if not event.device_generations:
            return

        async with async_session_maker() as session:
            result = await session.execute(
                update(Device)
                .where(Device.sync_status.in_(["pending", "failed"]))
                .where(Device.classroom_id.in_(select(Classroom.id).where(Classroom.router_id == event.router_id)))
                .where(tuple_(Device.id, Device.policy_generation).in_(list(event.device_generations.items())))
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

        if event.device_generations is None:
            logger.warning("Ignoring legacy sync result without device snapshot: router_id=%s", event.router_id)
            return
        if not event.device_generations:
            return

        async with async_session_maker() as session:
            result = await session.execute(
                update(Device)
                .where(Device.sync_status == "pending")
                .where(Device.classroom_id.in_(select(Classroom.id).where(Classroom.router_id == event.router_id)))
                .where(tuple_(Device.id, Device.policy_generation).in_(list(event.device_generations.items())))
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
