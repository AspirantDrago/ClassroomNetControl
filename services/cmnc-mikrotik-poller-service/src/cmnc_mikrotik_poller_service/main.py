import asyncio
import logging
import signal
from contextlib import suppress
from typing import Final

from cmnc_contracts.events import DhcpLeasesObservedEvent
from cmnc_contracts.routing_keys import MIKROTIK_DHCP_LEASES_OBSERVED

from cmnc_mikrotik_poller_service.messaging import RabbitMqClient
from cmnc_mikrotik_poller_service.mikrotik_client import MikroTikClient
from cmnc_mikrotik_poller_service.settings import settings

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


async def poll_once(
        mikrotik_client: MikroTikClient,
        rabbitmq_client: RabbitMqClient,
) -> None:
    leases = await mikrotik_client.get_dhcp_leases()

    if not leases and not settings.publish_empty_snapshots:
        logger.info("No DHCP leases received, empty snapshot skipped")
        return

    event = DhcpLeasesObservedEvent(
        router_id=settings.router_id,
        leases=leases,
    )

    await rabbitmq_client.publish_event(
        event=event,
        routing_key=MIKROTIK_DHCP_LEASES_OBSERVED,
    )

    logger.info(
        "DHCP leases snapshot published: router_id=%s, leases=%s",
        settings.router_id,
        len(leases),
    )


async def main() -> None:
    configure_signal_handlers()

    mikrotik_client = MikroTikClient(
        base_url=settings.mikrotik_base_url,
        username=settings.mikrotik_username,
        password=settings.mikrotik_password,
        verify_tls=settings.mikrotik_verify_tls,
        timeout_seconds=settings.mikrotik_timeout_seconds,
    )

    rabbitmq_client = RabbitMqClient(settings.rabbitmq_url)
    await rabbitmq_client.connect()

    logger.info("%s started", settings.service_name)

    try:
        while not _shutdown_event.is_set():
            try:
                await poll_once(
                    mikrotik_client=mikrotik_client,
                    rabbitmq_client=rabbitmq_client,
                )
            except Exception:
                logger.exception("MikroTik polling failed")

            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(),
                    timeout=settings.poll_interval_seconds,
                )
            except TimeoutError:
                pass
    finally:
        await rabbitmq_client.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
