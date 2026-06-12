import asyncio
import logging
import signal
from typing import Final

from aio_pika import IncomingMessage

from cmnc_contracts.events import (
    PolicySyncCompletedEvent,
    PolicySyncFailedEvent,
    WanPolicyChangedEvent,
)
from cmnc_contracts.routing_keys import (
    CLASSROOM_DEVICE_WAN_POLICY_CHANGED,
    POLICY_SYNC_COMPLETED,
    POLICY_SYNC_FAILED,
)

from cmnc_policy_sync_service.classroom_client import ClassroomServiceClient
from cmnc_policy_sync_service.messaging import RabbitMqClient
from cmnc_policy_sync_service.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(settings.service_name)

_shutdown_event: Final[asyncio.Event] = asyncio.Event()


def request_shutdown() -> None:
    logger.info("Shutdown requested")
    _shutdown_event.set()


async def handle_wan_policy_changed(
    message: IncomingMessage,
    rabbitmq: RabbitMqClient,
    classroom_client: ClassroomServiceClient,
) -> None:
    async with message.process(requeue=False):
        event = WanPolicyChangedEvent.model_validate_json(message.body)

        logger.info(
            "Received WAN policy changed event: device_id=%s, classroom_id=%s, "
            "router_id=%s, generation=%s, wan_allowed=%s",
            event.device_id,
            event.classroom_id,
            event.router_id,
            event.policy_generation,
            event.wan_allowed,
        )

        try:
            desired_blocklist = await classroom_client.get_desired_blocklist(
                router_id=event.router_id,
            )

            logger.info(
                "Desired blocklist received: router_id=%s, generation=%s, "
                "address_list=%s, blocked_count=%s",
                desired_blocklist.router_id,
                desired_blocklist.policy_generation,
                desired_blocklist.address_list_name,
                len(desired_blocklist.blocked),
            )

            for item in desired_blocklist.blocked:
                logger.info(
                    "Blocked device: device_id=%s, mac=%s, ip=%s, comment=%s",
                    item.device_id,
                    item.mac_address,
                    item.ip_address,
                    item.comment,
                )

            completed_event = PolicySyncCompletedEvent(
                router_id=event.router_id,
                policy_generation=desired_blocklist.policy_generation,
                added=0,
                removed=0,
                connections_killed=0,
                errors=[],
            )

            await rabbitmq.publish_event(
                event=completed_event,
                routing_key=POLICY_SYNC_COMPLETED,
            )

        except Exception as exc:
            logger.exception("Policy sync failed")

            failed_event = PolicySyncFailedEvent(
                router_id=event.router_id,
                policy_generation=event.policy_generation,
                error=str(exc),
            )

            await rabbitmq.publish_event(
                event=failed_event,
                routing_key=POLICY_SYNC_FAILED,
            )


async def main() -> None:
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_shutdown)

    rabbitmq = RabbitMqClient(settings.rabbitmq_url)
    classroom_client = ClassroomServiceClient(settings.classroom_service_url)

    await rabbitmq.connect()

    queue = await rabbitmq.declare_queue(
        queue_name=settings.wan_policy_changed_queue,
        routing_key=CLASSROOM_DEVICE_WAN_POLICY_CHANGED,
    )

    await queue.consume(
        lambda message: handle_wan_policy_changed(
            message=message,
            rabbitmq=rabbitmq,
            classroom_client=classroom_client,
        )
    )

    logger.info("%s started", settings.service_name)

    await _shutdown_event.wait()

    await rabbitmq.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
