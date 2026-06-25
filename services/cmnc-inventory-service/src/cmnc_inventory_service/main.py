from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cmnc_contracts.routing_keys import MIKROTIK_DHCP_LEASES_OBSERVED

from cmnc_inventory_service.db import get_session
from cmnc_inventory_service.dhcp_handlers import handle_dhcp_leases_observed
from cmnc_inventory_service.messaging import RabbitMqClient
from cmnc_inventory_service.models import ObservedDevice, Router, RouterServiceStatus
from cmnc_inventory_service.schemas import (
    DeleteObservedDevicesRequest,
    DeleteObservedDevicesResponse,
    HealthResponse,
    ObservedDeviceRead,
    ObservedDevicesResponse,
    RouterConnectionRead,
    RouterCreate,
    RouterRead,
    RouterServiceStatusRead,
    RouterServiceStatusUpdate,
    RouterStatusItem,
    RouterUpdate,
)
from cmnc_inventory_service.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    rabbitmq_client = RabbitMqClient(settings.rabbitmq_url)
    await rabbitmq_client.connect()

    queue = await rabbitmq_client.declare_queue(
        queue_name=settings.dhcp_leases_observed_queue,
        routing_key=MIKROTIK_DHCP_LEASES_OBSERVED,
    )
    await queue.consume(handle_dhcp_leases_observed)

    app.state.rabbitmq_client = rabbitmq_client

    yield

    await rabbitmq_client.close()


app = FastAPI(
    title=settings.service_name,
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        service=settings.service_name,
        status="ok",
    )


@app.get("/internal/routers", response_model=list[RouterRead])
async def get_routers(
    session: AsyncSession = Depends(get_session),
) -> list[RouterRead]:
    result = await session.execute(select(Router).order_by(Router.id))
    routers = list(result.scalars().all())
    return [RouterRead.model_validate(router) for router in routers]


@app.get("/internal/routers/active", response_model=list[RouterConnectionRead])
async def get_active_routers(
    session: AsyncSession = Depends(get_session),
) -> list[RouterConnectionRead]:
    result = await session.execute(
        select(Router)
        .where(Router.is_enabled.is_(True))
        .order_by(Router.id)
    )
    routers = list(result.scalars().all())
    return [RouterConnectionRead.model_validate(router) for router in routers]


@app.get("/internal/routers/{router_id}", response_model=RouterRead)
async def get_router(
    router_id: int,
    session: AsyncSession = Depends(get_session),
) -> RouterRead:
    router = await session.get(Router, router_id)

    if router is None:
        raise HTTPException(status_code=404, detail="Router not found")

    return RouterRead.model_validate(router)


@app.get("/internal/routers/{router_id}/connection", response_model=RouterConnectionRead)
async def get_router_connection(
    router_id: int,
    session: AsyncSession = Depends(get_session),
) -> RouterConnectionRead:
    router = await session.get(Router, router_id)

    if router is None:
        raise HTTPException(status_code=404, detail="Router not found")

    return RouterConnectionRead.model_validate(router)


@app.post("/internal/routers", response_model=RouterRead, status_code=201)
async def create_router(
    payload: RouterCreate,
    session: AsyncSession = Depends(get_session),
) -> RouterRead:
    router = Router(
        name=payload.name.strip(),
        api_host=payload.api_host.strip(),
        api_port=payload.api_port,
        api_use_ssl=payload.api_use_ssl,
        api_username=payload.api_username.strip(),
        api_password=payload.api_password,
        is_enabled=payload.is_enabled,
        poll_enabled=payload.poll_enabled,
        sync_enabled=payload.sync_enabled,
        poll_interval_seconds=payload.poll_interval_seconds,
    )

    session.add(router)
    await session.commit()
    await session.refresh(router)

    return RouterRead.model_validate(router)


@app.patch("/internal/routers/{router_id}", response_model=RouterRead)
async def update_router(
    router_id: int,
    payload: RouterUpdate,
    session: AsyncSession = Depends(get_session),
) -> RouterRead:
    router = await session.get(Router, router_id)

    if router is None:
        raise HTTPException(status_code=404, detail="Router not found")

    update_data = payload.model_dump(exclude_unset=True)

    for field_name in {"name", "api_host", "api_username"}:
        value = update_data.get(field_name)
        if isinstance(value, str):
            update_data[field_name] = value.strip()

    for field_name, value in update_data.items():
        setattr(router, field_name, value)

    await session.commit()
    await session.refresh(router)

    return RouterRead.model_validate(router)


@app.get("/internal/routers/status", response_model=list[RouterStatusItem])
async def get_routers_status(
    session: AsyncSession = Depends(get_session),
) -> list[RouterStatusItem]:
    routers_result = await session.execute(select(Router).order_by(Router.id))
    routers = list(routers_result.scalars().all())

    status_result = await session.execute(
        select(RouterServiceStatus).order_by(
            RouterServiceStatus.router_id,
            RouterServiceStatus.service_name,
        )
    )
    statuses = list(status_result.scalars().all())

    statuses_by_router: dict[int, list[RouterServiceStatus]] = {}
    for status in statuses:
        statuses_by_router.setdefault(status.router_id, []).append(status)

    return [
        RouterStatusItem(
            router=RouterRead.model_validate(router),
            services=[
                RouterServiceStatusRead.model_validate(status)
                for status in statuses_by_router.get(router.id, [])
            ],
        )
        for router in routers
    ]


@app.get(
    "/internal/routers/{router_id}/status",
    response_model=list[RouterServiceStatusRead],
)
async def get_router_status(
    router_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[RouterServiceStatusRead]:
    router = await session.get(Router, router_id)

    if router is None:
        raise HTTPException(status_code=404, detail="Router not found")

    result = await session.execute(
        select(RouterServiceStatus)
        .where(RouterServiceStatus.router_id == router_id)
        .order_by(RouterServiceStatus.service_name)
    )
    statuses = list(result.scalars().all())

    return [RouterServiceStatusRead.model_validate(status) for status in statuses]


@app.put(
    "/internal/routers/{router_id}/status/{service_name}",
    response_model=RouterServiceStatusRead,
)
async def upsert_router_service_status(
    router_id: int,
    service_name: str,
    payload: RouterServiceStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> RouterServiceStatusRead:
    if service_name != payload.service_name:
        raise HTTPException(status_code=422, detail="service_name mismatch")

    router = await session.get(Router, router_id)

    if router is None:
        raise HTTPException(status_code=404, detail="Router not found")

    result = await session.execute(
        select(RouterServiceStatus)
        .where(RouterServiceStatus.router_id == router_id)
        .where(RouterServiceStatus.service_name == service_name)
    )
    status = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if status is None:
        status = RouterServiceStatus(
            router_id=router_id,
            service_name=service_name,
            worker_id=payload.worker_id,
            status=payload.status,
            is_running=payload.is_running,
            heartbeat_at=payload.heartbeat_at or now,
            last_started_at=payload.last_started_at,
            last_attempt_at=payload.last_attempt_at,
            last_success_at=payload.last_success_at,
            last_error_at=payload.last_error_at,
            last_error=payload.last_error,
            consecutive_failures=payload.consecutive_failures or 0,
            details=payload.details,
        )
        session.add(status)
    else:
        status.worker_id = payload.worker_id
        status.status = payload.status
        status.is_running = payload.is_running
        status.heartbeat_at = payload.heartbeat_at or now
        status.last_started_at = payload.last_started_at
        status.last_attempt_at = payload.last_attempt_at
        status.last_success_at = payload.last_success_at
        status.last_error_at = payload.last_error_at
        status.last_error = payload.last_error
        status.consecutive_failures = payload.consecutive_failures or 0
        status.details = payload.details

    await session.commit()
    await session.refresh(status)

    return RouterServiceStatusRead.model_validate(status)


@app.get(
    "/internal/observed-devices",
    response_model=ObservedDevicesResponse,
)
async def get_observed_devices(
        session: AsyncSession = Depends(get_session),
) -> ObservedDevicesResponse:
    result = await session.execute(
        select(ObservedDevice).order_by(
            ObservedDevice.router_id,
            ObservedDevice.mac_address,
        )
    )
    devices = list(result.scalars().all())

    return ObservedDevicesResponse(
        devices=[ObservedDeviceRead.model_validate(device) for device in devices],
    )


@app.get(
    "/internal/routers/{router_id}/observed-devices",
    response_model=ObservedDevicesResponse,
)
async def get_observed_devices_by_router(
        router_id: int,
        session: AsyncSession = Depends(get_session),
) -> ObservedDevicesResponse:
    result = await session.execute(
        select(ObservedDevice)
        .where(ObservedDevice.router_id == router_id)
        .order_by(ObservedDevice.mac_address)
    )
    devices = list(result.scalars().all())

    return ObservedDevicesResponse(
        devices=[ObservedDeviceRead.model_validate(device) for device in devices],
    )


@app.post(
    "/internal/routers/{router_id}/observed-devices/delete",
    response_model=DeleteObservedDevicesResponse,
)
async def delete_observed_devices_by_router(
        router_id: int,
        payload: DeleteObservedDevicesRequest,
        session: AsyncSession = Depends(get_session),
) -> DeleteObservedDevicesResponse:
    ids = sorted(set(payload.ids))

    if not ids:
        return DeleteObservedDevicesResponse(
            deleted_ids=[],
            deleted_count=0,
        )

    result = await session.execute(
        select(ObservedDevice)
        .where(ObservedDevice.router_id == router_id)
        .where(ObservedDevice.id.in_(ids))
    )
    devices = list(result.scalars().all())

    deleted_ids = sorted(device.id for device in devices)

    for device in devices:
        await session.delete(device)

    await session.commit()

    return DeleteObservedDevicesResponse(
        deleted_ids=deleted_ids,
        deleted_count=len(deleted_ids),
    )


def run() -> None:
    uvicorn.run(
        "cmnc_inventory_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    run()
