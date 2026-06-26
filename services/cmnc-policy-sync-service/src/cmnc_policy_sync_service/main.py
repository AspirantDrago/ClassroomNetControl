import asyncio
import logging
import signal
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Final

from aio_pika import IncomingMessage
from pydantic import SecretStr

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
from cmnc_policy_sync_service.inventory_client import (
    InventoryClient,
    RouterConnection,
    RouterServiceStatus,
)
from cmnc_policy_sync_service.messaging import RabbitMqClient
from cmnc_policy_sync_service.mikrotik_client import MikroTikClient, PolicyApplyResult
from cmnc_policy_sync_service.schemas import DesiredBlocklistResponse
from cmnc_policy_sync_service.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(settings.service_name)

SERVICE_NAME: Final[str] = "policy_sync"
_shutdown_event: Final[asyncio.Event] = asyncio.Event()


@dataclass(slots=True)
class SyncWorkerState:
    router: RouterConnection
    task: asyncio.Task[None]
    trigger_queue: asyncio.Queue[WanPolicyChangedEvent | None]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def request_shutdown() -> None:
    logger.info("Shutdown requested")
    _shutdown_event.set()


def configure_signal_handlers() -> None:
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, request_shutdown)


async def update_status_safely(
    inventory_client: InventoryClient,
    *,
    router_id: int,
    worker_id: str | None,
    status: RouterServiceStatus,
    is_running: bool,
    heartbeat_at: datetime | None = None,
    last_started_at: datetime | None = None,
    last_attempt_at: datetime | None = None,
    last_success_at: datetime | None = None,
    last_error_at: datetime | None = None,
    last_error: str | None = None,
    consecutive_failures: int | None = None,
    details: dict[str, object] | None = None,
) -> None:
    try:
        await inventory_client.update_router_service_status(
            router_id=router_id,
            service_name=SERVICE_NAME,
            worker_id=worker_id,
            status=status,
            is_running=is_running,
            heartbeat_at=heartbeat_at,
            last_started_at=last_started_at,
            last_attempt_at=last_attempt_at,
            last_success_at=last_success_at,
            last_error_at=last_error_at,
            last_error=last_error,
            consecutive_failures=consecutive_failures,
            details=details,
        )
    except Exception:
        logger.warning(
            "Failed to update policy sync status: router_id=%s",
            router_id,
            exc_info=True,
        )


async def publish_sync_completed(
    *,
    rabbitmq: RabbitMqClient,
    router_id: int,
    desired: DesiredBlocklistResponse,
    result: PolicyApplyResult,
) -> None:
    completed_event = PolicySyncCompletedEvent(
        router_id=router_id,
        policy_generation=desired.policy_generation,
        added=result.added,
        removed=result.removed,
        connections_killed=result.connections_killed,
        errors=[],
    )

    await rabbitmq.publish_event(
        event=completed_event,
        routing_key=POLICY_SYNC_COMPLETED,
    )


async def publish_sync_failed(
    *,
    rabbitmq: RabbitMqClient,
    router_id: int,
    policy_generation: int,
    error: str,
) -> None:
    failed_event = PolicySyncFailedEvent(
        router_id=router_id,
        policy_generation=policy_generation,
        error=error,
    )

    await rabbitmq.publish_event(
        event=failed_event,
        routing_key=POLICY_SYNC_FAILED,
    )


async def sync_router_policy(
    *,
    router: RouterConnection,
    classroom_client: ClassroomServiceClient,
    mikrotik_client: MikroTikClient,
    rabbitmq: RabbitMqClient,
) -> dict[str, object]:
    started = perf_counter()

    desired_blocklist = await classroom_client.get_desired_blocklist(
        router_id=router.id,
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

    duration_ms = int((perf_counter() - started) * 1000)

    details: dict[str, object] = {
        "policy_generation": desired_blocklist.policy_generation,
        "desired_count": len(desired_blocklist.blocked),
        "added_count": result.added,
        "removed_count": result.removed,
        "updated_count": result.updated,
        "connections_killed_count": result.connections_killed,
        "duration_ms": duration_ms,
        "address_list_name": desired_blocklist.address_list_name,
        "api_host": router.api_host,
        "api_port": router.api_port,
        "api_use_ssl": router.api_use_ssl,
    }

    if result.errors:
        error = "; ".join(result.errors)
        await publish_sync_failed(
            rabbitmq=rabbitmq,
            router_id=router.id,
            policy_generation=desired_blocklist.policy_generation,
            error=error,
        )
        raise RuntimeError(error)

    await publish_sync_completed(
        rabbitmq=rabbitmq,
        router_id=router.id,
        desired=desired_blocklist,
        result=result,
    )

    logger.info(
        "Policy sync completed: router_id=%s, added=%s, removed=%s, updated=%s, "
        "connections_killed=%s",
        router.id,
        result.added,
        result.removed,
        result.updated,
        result.connections_killed,
    )

    return details


async def wait_for_trigger_or_timeout(
    queue: asyncio.Queue[WanPolicyChangedEvent | None],
) -> WanPolicyChangedEvent | None:
    try:
        event = await asyncio.wait_for(
            queue.get(),
            timeout=settings.reconcile_interval_seconds,
        )
    except TimeoutError:
        return None

    latest_event = event

    while True:
        try:
            next_event = queue.get_nowait()
        except asyncio.QueueEmpty:
            return latest_event

        if next_event is not None:
            latest_event = next_event


async def sync_router_worker(
    *,
    router: RouterConnection,
    trigger_queue: asyncio.Queue[WanPolicyChangedEvent | None],
    inventory_client: InventoryClient,
    classroom_client: ClassroomServiceClient,
    rabbitmq: RabbitMqClient,
) -> None:
    worker_id = f"{settings.service_name}:{router.id}:{uuid.uuid4()}"
    started_at = now_utc()
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures = 0
    details: dict[str, object] = {
        "api_host": router.api_host,
        "api_port": router.api_port,
        "api_use_ssl": router.api_use_ssl,
    }

    mikrotik_client = MikroTikClient(
        base_url=router.base_url,
        username=router.api_username,
        password=SecretStr(router.api_password),
        verify_tls=settings.mikrotik_verify_tls,
        timeout_seconds=settings.mikrotik_timeout_seconds,
        managed_comment_prefix=settings.managed_comment_prefix,
    )

    logger.info(
        "Policy sync worker started: router_id=%s, router_name=%s, base_url=%s",
        router.id,
        router.name,
        router.base_url,
    )

    await update_status_safely(
        inventory_client,
        router_id=router.id,
        worker_id=worker_id,
        status="starting",
        is_running=True,
        heartbeat_at=started_at,
        last_started_at=started_at,
        consecutive_failures=0,
        details=details,
    )

    try:
        while not _shutdown_event.is_set():
            heartbeat_at = now_utc()
            await update_status_safely(
                inventory_client,
                router_id=router.id,
                worker_id=worker_id,
                status="ok" if consecutive_failures == 0 else "warning",
                is_running=True,
                heartbeat_at=heartbeat_at,
                last_started_at=started_at,
                last_attempt_at=last_attempt_at,
                last_success_at=last_success_at,
                last_error_at=last_error_at,
                last_error=last_error,
                consecutive_failures=consecutive_failures,
                details=details,
            )

            trigger_event = await wait_for_trigger_or_timeout(trigger_queue)
            if _shutdown_event.is_set():
                break

            last_attempt_at = now_utc()
            try:
                result_details = await sync_router_policy(
                    router=router,
                    classroom_client=classroom_client,
                    mikrotik_client=mikrotik_client,
                    rabbitmq=rabbitmq,
                )

                last_success_at = now_utc()
                last_error = None
                last_error_at = None
                consecutive_failures = 0
                details = result_details

                await update_status_safely(
                    inventory_client,
                    router_id=router.id,
                    worker_id=worker_id,
                    status="ok",
                    is_running=True,
                    heartbeat_at=last_success_at,
                    last_started_at=started_at,
                    last_attempt_at=last_attempt_at,
                    last_success_at=last_success_at,
                    consecutive_failures=0,
                    details=details,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error_at = now_utc()
                last_error = f"{type(exc).__name__}: {exc}"
                consecutive_failures += 1
                status: RouterServiceStatus = "warning" if consecutive_failures < 3 else "error"
                policy_generation = trigger_event.policy_generation if trigger_event is not None else 0

                logger.exception(
                    "Policy sync failed: router_id=%s, router_name=%s, failures=%s",
                    router.id,
                    router.name,
                    consecutive_failures,
                )

                if trigger_event is not None:
                    await publish_sync_failed(
                        rabbitmq=rabbitmq,
                        router_id=router.id,
                        policy_generation=policy_generation,
                        error=last_error,
                    )

                await update_status_safely(
                    inventory_client,
                    router_id=router.id,
                    worker_id=worker_id,
                    status=status,
                    is_running=True,
                    heartbeat_at=last_error_at,
                    last_started_at=started_at,
                    last_attempt_at=last_attempt_at,
                    last_success_at=last_success_at,
                    last_error_at=last_error_at,
                    last_error=last_error,
                    consecutive_failures=consecutive_failures,
                    details=details,
                )
    finally:
        stopped_at = now_utc()
        await update_status_safely(
            inventory_client,
            router_id=router.id,
            worker_id=worker_id,
            status="disabled",
            is_running=False,
            heartbeat_at=stopped_at,
            last_started_at=started_at,
            last_attempt_at=last_attempt_at,
            last_success_at=last_success_at,
            last_error_at=last_error_at,
            last_error=last_error,
            consecutive_failures=consecutive_failures,
            details=details,
        )
        logger.info(
            "Policy sync worker stopped: router_id=%s, router_name=%s",
            router.id,
            router.name,
        )


async def cancel_worker(state: SyncWorkerState) -> None:
    state.task.cancel()
    with suppress(asyncio.CancelledError):
        await state.task


def router_config_changed(old: RouterConnection, new: RouterConnection) -> bool:
    return old != new


async def handle_wan_policy_changed(
    message: IncomingMessage,
    workers: dict[int, SyncWorkerState],
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

        state = workers.get(event.router_id)
        if state is None:
            logger.warning(
                "No active policy sync worker for event router_id=%s. "
                "The next periodic reconcile will apply it after the worker starts.",
                event.router_id,
            )
            return

        try:
            state.trigger_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "Policy sync trigger queue is full, compacting to one pending trigger: router_id=%s",
                event.router_id,
            )
            with suppress(asyncio.QueueEmpty):
                state.trigger_queue.get_nowait()
            state.trigger_queue.put_nowait(event)


async def supervisor(
    *,
    inventory_client: InventoryClient,
    classroom_client: ClassroomServiceClient,
    rabbitmq: RabbitMqClient,
    workers: dict[int, SyncWorkerState],
) -> None:
    while not _shutdown_event.is_set():
        try:
            routers = await inventory_client.get_active_routers()
        except Exception:
            logger.exception("Failed to load active routers from inventory service")
            routers = []

        routers_by_id = {router.id: router for router in routers}

        for router in routers:
            existing = workers.get(router.id)

            if not router.sync_enabled:
                if existing is not None:
                    logger.info(
                        "Stopping policy sync worker because sync is disabled: router_id=%s",
                        router.id,
                    )
                    await cancel_worker(existing)
                    workers.pop(router.id, None)

                await update_status_safely(
                    inventory_client,
                    router_id=router.id,
                    worker_id=None,
                    status="disabled",
                    is_running=False,
                    heartbeat_at=now_utc(),
                    consecutive_failures=0,
                    details={
                        "reason": "sync_enabled is false",
                        "api_host": router.api_host,
                        "api_port": router.api_port,
                        "api_use_ssl": router.api_use_ssl,
                    },
                )
                continue

            if existing is not None and router_config_changed(existing.router, router):
                logger.info(
                    "Restarting policy sync worker because router settings changed: router_id=%s",
                    router.id,
                )
                await cancel_worker(existing)
                workers.pop(router.id, None)
                existing = None

            if existing is None or existing.task.done():
                if existing is not None and existing.task.done():
                    logger.warning(
                        "Restarting stopped policy sync worker: router_id=%s",
                        router.id,
                    )
                    workers.pop(router.id, None)

                trigger_queue: asyncio.Queue[WanPolicyChangedEvent | None] = asyncio.Queue(
                    maxsize=settings.router_event_queue_max_size,
                )
                task = asyncio.create_task(
                    sync_router_worker(
                        router=router,
                        trigger_queue=trigger_queue,
                        inventory_client=inventory_client,
                        classroom_client=classroom_client,
                        rabbitmq=rabbitmq,
                    )
                )
                workers[router.id] = SyncWorkerState(
                    router=router,
                    task=task,
                    trigger_queue=trigger_queue,
                )

        for router_id, state in list(workers.items()):
            if router_id not in routers_by_id:
                logger.info(
                    "Stopping policy sync worker because router is not active: router_id=%s",
                    router_id,
                )
                await cancel_worker(state)
                workers.pop(router_id, None)

        try:
            await asyncio.wait_for(
                _shutdown_event.wait(),
                timeout=settings.supervisor_interval_seconds,
            )
        except TimeoutError:
            pass

    for state in list(workers.values()):
        await cancel_worker(state)


async def main() -> None:
    configure_signal_handlers()

    workers: dict[int, SyncWorkerState] = {}
    inventory_client = InventoryClient(
        base_url=settings.inventory_service_url,
        timeout_seconds=settings.mikrotik_timeout_seconds,
    )
    classroom_client = ClassroomServiceClient(settings.classroom_service_url)
    rabbitmq = RabbitMqClient(settings.rabbitmq_url)

    await rabbitmq.connect()

    queue = await rabbitmq.declare_queue(
        queue_name=settings.wan_policy_changed_queue,
        routing_key=CLASSROOM_DEVICE_WAN_POLICY_CHANGED,
    )

    await queue.consume(lambda message: handle_wan_policy_changed(message, workers))

    logger.info("%s started", settings.service_name)

    try:
        await supervisor(
            inventory_client=inventory_client,
            classroom_client=classroom_client,
            rabbitmq=rabbitmq,
            workers=workers,
        )
    finally:
        await rabbitmq.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
