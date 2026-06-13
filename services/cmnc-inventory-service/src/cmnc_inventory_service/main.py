from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging

import uvicorn
from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cmnc_contracts.routing_keys import MIKROTIK_DHCP_LEASES_OBSERVED

from cmnc_inventory_service.db import get_session
from cmnc_inventory_service.dhcp_handlers import handle_dhcp_leases_observed
from cmnc_inventory_service.messaging import RabbitMqClient
from cmnc_inventory_service.models import ObservedDevice
from cmnc_inventory_service.schemas import (
    HealthResponse,
    ObservedDeviceRead,
    ObservedDevicesResponse,
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
