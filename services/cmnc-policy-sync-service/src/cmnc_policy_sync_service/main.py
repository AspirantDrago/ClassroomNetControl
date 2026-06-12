import asyncio
import logging
import signal
from contextlib import suppress
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
from cmnc_policy_sync_service.mikrotik_client import MikroTikClient
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


def configure_signal_handlers() -> None:
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, request_shutdown)


async def handle_wan_policy_changed(
        message: IncomingMessage,
        rabbitmq: RabbitMqClient,
        classroom_client: ClassroomServiceClient,
        mikrotik_client: MikroTikClient,
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

            result = await mikrotik_client.apply_desired_blocklist(
                desired=desired_blocklist,
                kill_connections_on_block=settings.kill_connections_on_block,
            )

            if result.errors:
                failed_event = PolicySyncFailedEvent(
                    router_id=event.router_id,
                    policy_generation=desired_blocklist.policy_generation,
                    error="; ".join(result.errors),
                )

                await rabbitmq.publish_event(
                    event=failed_event,
                    routing_key=POLICY_SYNC_FAILED,
                )

                return

            completed_event = PolicySyncCompletedEvent(
                router_id=event.router_id,
                policy_generation=desired_blocklist.policy_generation,
                added=result.added,
                removed=result.removed,
                connections_killed=result.connections_killed,
                errors=[],
            )

            await rabbitmq.publish_event(
                event=completed_event,
                routing_key=POLICY_SYNC_COMPLETED,
            )

            logger.info(
                "Policy sync completed: added=%s, removed=%s, updated=%s, "
                "connections_killed=%s",
                result.added,
                result.removed,
                result.updated,
                result.connections_killed,
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
    configure_signal_handlers()

    rabbitmq = RabbitMqClient(settings.rabbitmq_url)
    classroom_client = ClassroomServiceClient(settings.classroom_service_url)

    mikrotik_client = MikroTikClient(
        base_url=settings.mikrotik_base_url,
        username=settings.mikrotik_username,
        password=settings.mikrotik_password,
        verify_tls=settings.mikrotik_verify_tls,
        timeout_seconds=settings.mikrotik_timeout_seconds,
        managed_comment_prefix=settings.managed_comment_prefix,
    )

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
            mikrotik_client=mikrotik_client,
        )
    )

    logger.info("%s started", settings.service_name)

    await _shutdown_event.wait()

    await rabbitmq.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
