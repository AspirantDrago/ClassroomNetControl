import asyncio
import logging
import signal
import uuid
from time import perf_counter
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import SecretStr

from cmnc_contracts.events import DhcpLeasesObservedEvent
from cmnc_contracts.routing_keys import MIKROTIK_DHCP_LEASES_OBSERVED

from cmnc_mikrotik_poller_service.inventory_client import (
    InventoryClient,
    RouterConnection,
    RouterServiceStatus,
)
from cmnc_mikrotik_poller_service.messaging import RabbitMqClient
from cmnc_mikrotik_poller_service.mikrotik_client import MikroTikClient
from cmnc_mikrotik_poller_service.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(settings.service_name)

app = FastAPI(title=settings.service_name)

SERVICE_NAME: Final[str] = "mikrotik_poller"
_shutdown_event: Final[asyncio.Event] = asyncio.Event()


@dataclass(slots=True)
class PollerWorkerState:
    router: RouterConnection
    task: asyncio.Task[None]


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
            "Failed to update poller status: router_id=%s",
            router_id,
            exc_info=True,
        )


def get_runtime_inventory_client() -> InventoryClient:
    inventory_client = getattr(app.state, "inventory_client", None)

    if not isinstance(inventory_client, InventoryClient):
        raise HTTPException(status_code=503, detail="Poller service is not ready")

    return inventory_client


def get_runtime_rabbitmq_client() -> RabbitMqClient:
    rabbitmq_client = getattr(app.state, "rabbitmq_client", None)

    if not isinstance(rabbitmq_client, RabbitMqClient):
        raise HTTPException(status_code=503, detail="Poller service is not ready")

    return rabbitmq_client


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "service": settings.service_name,
        "status": "ok",
    }


@app.post("/internal/routers/{router_id}/poll-now")
async def internal_poll_router_now(router_id: int) -> dict[str, Any]:
    return await poll_router_once_manual(
        router_id=router_id,
        inventory_client=get_runtime_inventory_client(),
        rabbitmq_client=get_runtime_rabbitmq_client(),
    )


async def poll_router_once_manual(
    *,
    router_id: int,
    inventory_client: InventoryClient,
    rabbitmq_client: RabbitMqClient,
) -> dict[str, Any]:
    worker_id = f"{settings.service_name}:manual:{router_id}:{uuid.uuid4()}"
    started_at = now_utc()

    try:
        router = await inventory_client.get_router_connection(router_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Router not found") from exc

        raise HTTPException(status_code=502, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Inventory service unavailable: {exc}") from exc

    if not router.is_enabled:
        return {
            "ok": False,
            "router_id": router.id,
            "router_name": router.name,
            "leases_count": None,
            "snapshot_published": None,
            "duration_ms": 0,
            "error": "Router is disabled",
            "details": {
                "manual": True,
                "api_host": router.api_host,
                "api_port": router.api_port,
                "api_use_ssl": router.api_use_ssl,
            },
        }

    mikrotik_client = MikroTikClient(
        base_url=router.base_url,
        username=router.api_username,
        password=SecretStr(router.api_password),
        verify_tls=settings.mikrotik_verify_tls,
        timeout_seconds=settings.mikrotik_timeout_seconds,
    )

    last_attempt_at = now_utc()
    await update_status_safely(
        inventory_client,
        router_id=router.id,
        worker_id=worker_id,
        status="starting",
        is_running=router.poll_enabled,
        heartbeat_at=last_attempt_at,
        last_started_at=started_at,
        last_attempt_at=last_attempt_at,
        consecutive_failures=0,
        details={
            "manual": True,
            "api_host": router.api_host,
            "api_port": router.api_port,
            "api_use_ssl": router.api_use_ssl,
        },
    )

    started_perf = perf_counter()

    try:
        result_details = await poll_once(
            router=router,
            mikrotik_client=mikrotik_client,
            rabbitmq_client=rabbitmq_client,
        )
    except Exception as exc:
        finished_at = now_utc()
        duration_ms = int((perf_counter() - started_perf) * 1000)
        error_text = f"{type(exc).__name__}: {exc}"
        details: dict[str, Any] = {
            "manual": True,
            "duration_ms": duration_ms,
            "api_host": router.api_host,
            "api_port": router.api_port,
            "api_use_ssl": router.api_use_ssl,
        }

        logger.exception(
            "Manual MikroTik polling failed: router_id=%s, router_name=%s",
            router.id,
            router.name,
        )

        await update_status_safely(
            inventory_client,
            router_id=router.id,
            worker_id=worker_id,
            status="error",
            is_running=router.poll_enabled,
            heartbeat_at=finished_at,
            last_started_at=started_at,
            last_attempt_at=last_attempt_at,
            last_error_at=finished_at,
            last_error=error_text,
            consecutive_failures=1,
            details=details,
        )

        return {
            "ok": False,
            "router_id": router.id,
            "router_name": router.name,
            "leases_count": None,
            "snapshot_published": None,
            "duration_ms": duration_ms,
            "error": error_text,
            "details": details,
        }

    finished_at = now_utc()
    duration_ms = int((perf_counter() - started_perf) * 1000)
    details = {
        **(result_details or {}),
        "manual": True,
        "duration_ms": duration_ms,
    }

    await update_status_safely(
        inventory_client,
        router_id=router.id,
        worker_id=worker_id,
        status="ok",
        is_running=router.poll_enabled,
        heartbeat_at=finished_at,
        last_started_at=started_at,
        last_attempt_at=last_attempt_at,
        last_success_at=finished_at,
        consecutive_failures=0,
        details=details,
    )

    return {
        "ok": True,
        "router_id": router.id,
        "router_name": router.name,
        "leases_count": details.get("leases_count"),
        "snapshot_published": details.get("snapshot_published"),
        "duration_ms": duration_ms,
        "error": None,
        "details": details,
    }


async def poll_once(
    *,
    router: RouterConnection,
    mikrotik_client: MikroTikClient,
    rabbitmq_client: RabbitMqClient,
) -> dict[str, object] | None:
    leases = await mikrotik_client.get_dhcp_leases()

    if not leases and not settings.publish_empty_snapshots:
        logger.info(
            "No DHCP leases received, empty snapshot skipped: router_id=%s",
            router.id,
        )
        return {
            "leases_count": 0,
            "snapshot_published": False,
        }

    event = DhcpLeasesObservedEvent(
        router_id=router.id,
        leases=leases,
    )

    await rabbitmq_client.publish_event(
        event=event,
        routing_key=MIKROTIK_DHCP_LEASES_OBSERVED,
    )

    logger.info(
        "DHCP leases snapshot published: router_id=%s, router_name=%s, leases=%s",
        router.id,
        router.name,
        len(leases),
    )

    return {
        "leases_count": len(leases),
        "snapshot_published": True,
        "api_host": router.api_host,
        "api_port": router.api_port,
        "api_use_ssl": router.api_use_ssl,
    }


async def poll_router_worker(
    *,
    router: RouterConnection,
    inventory_client: InventoryClient,
    rabbitmq_client: RabbitMqClient,
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
    )

    logger.info(
        "Poller worker started: router_id=%s, router_name=%s, base_url=%s",
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

            last_attempt_at = now_utc()
            try:
                result_details = await poll_once(
                    router=router,
                    mikrotik_client=mikrotik_client,
                    rabbitmq_client=rabbitmq_client,
                )
                last_success_at = now_utc()
                last_error = None
                last_error_at = None
                consecutive_failures = 0

                if result_details is not None:
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

                logger.exception(
                    "MikroTik polling failed: router_id=%s, router_name=%s, failures=%s",
                    router.id,
                    router.name,
                    consecutive_failures,
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

            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(),
                    timeout=max(router.poll_interval_seconds, 1),
                )
            except TimeoutError:
                pass
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
            "Poller worker stopped: router_id=%s, router_name=%s",
            router.id,
            router.name,
        )


async def cancel_worker(state: PollerWorkerState) -> None:
    state.task.cancel()
    with suppress(asyncio.CancelledError):
        await state.task


def router_config_changed(old: RouterConnection, new: RouterConnection) -> bool:
    return old != new


async def supervisor(
    *,
    inventory_client: InventoryClient,
    rabbitmq_client: RabbitMqClient,
) -> None:
    workers: dict[int, PollerWorkerState] = {}

    while not _shutdown_event.is_set():
        try:
            routers = await inventory_client.get_active_routers()
        except Exception:
            logger.exception("Failed to load active routers from inventory service")
            routers = []

        routers_by_id = {router.id: router for router in routers}

        for router in routers:
            existing = workers.get(router.id)

            if not router.poll_enabled:
                if existing is not None:
                    logger.info(
                        "Stopping poller worker because polling is disabled: router_id=%s",
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
                        "reason": "poll_enabled is false",
                        "api_host": router.api_host,
                        "api_port": router.api_port,
                        "api_use_ssl": router.api_use_ssl,
                    },
                )
                continue

            if existing is not None and router_config_changed(existing.router, router):
                logger.info(
                    "Restarting poller worker because router settings changed: router_id=%s",
                    router.id,
                )
                await cancel_worker(existing)
                workers.pop(router.id, None)
                existing = None

            if existing is None or existing.task.done():
                if existing is not None and existing.task.done():
                    logger.warning(
                        "Restarting stopped poller worker: router_id=%s",
                        router.id,
                    )
                    workers.pop(router.id, None)

                task = asyncio.create_task(
                    poll_router_worker(
                        router=router,
                        inventory_client=inventory_client,
                        rabbitmq_client=rabbitmq_client,
                    )
                )
                workers[router.id] = PollerWorkerState(router=router, task=task)

        for router_id, state in list(workers.items()):
            if router_id not in routers_by_id:
                logger.info(
                    "Stopping poller worker because router is not active: router_id=%s",
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

    inventory_client = InventoryClient(
        base_url=settings.inventory_service_url,
        timeout_seconds=settings.mikrotik_timeout_seconds,
    )
    rabbitmq_client = RabbitMqClient(settings.rabbitmq_url)
    await rabbitmq_client.connect()

    app.state.inventory_client = inventory_client
    app.state.rabbitmq_client = rabbitmq_client

    api_config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    api_server = uvicorn.Server(api_config)
    api_task = asyncio.create_task(api_server.serve())
    supervisor_task = asyncio.create_task(
        supervisor(
            inventory_client=inventory_client,
            rabbitmq_client=rabbitmq_client,
        )
    )

    logger.info(
        "%s started: api=%s:%s",
        settings.service_name,
        settings.host,
        settings.port,
    )

    try:
        done, _pending = await asyncio.wait(
            {api_task, supervisor_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    finally:
        _shutdown_event.set()
        api_server.should_exit = True

        for task in (supervisor_task, api_task):
            if not task.done():
                task.cancel()

        for task in (supervisor_task, api_task):
            with suppress(asyncio.CancelledError):
                await task

        await rabbitmq_client.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
