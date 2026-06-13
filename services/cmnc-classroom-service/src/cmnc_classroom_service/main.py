from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from sqlalchemy import select

from cmnc_contracts.routing_keys import POLICY_SYNC_COMPLETED, POLICY_SYNC_FAILED

from cmnc_classroom_service.api import router
from cmnc_classroom_service.db import async_session_maker
from cmnc_classroom_service.messaging import RabbitMqClient
from cmnc_classroom_service.models import Classroom, Device
from cmnc_classroom_service.policy_sync_handlers import (
    handle_policy_sync_completed,
    handle_policy_sync_failed,
)
from cmnc_classroom_service.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if settings.seed_demo_data:
        await seed_demo_data()

    rabbitmq_client = RabbitMqClient(settings.rabbitmq_url)
    await rabbitmq_client.connect()

    completed_queue = await rabbitmq_client.declare_queue(
        queue_name=settings.policy_sync_completed_queue,
        routing_key=POLICY_SYNC_COMPLETED,
    )
    await completed_queue.consume(handle_policy_sync_completed)

    failed_queue = await rabbitmq_client.declare_queue(
        queue_name=settings.policy_sync_failed_queue,
        routing_key=POLICY_SYNC_FAILED,
    )
    await failed_queue.consume(handle_policy_sync_failed)

    app.state.rabbitmq_client = rabbitmq_client

    yield

    await rabbitmq_client.close()


app = FastAPI(
    title=settings.service_name,
    lifespan=lifespan,
)
app.include_router(router)


async def seed_demo_data() -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(Classroom).limit(1))
        existing_classroom = result.scalar_one_or_none()

        if existing_classroom is not None:
            return

        classroom = Classroom(
            name="Аудитория 1",
            subnet_cidr="192.168.100.0/24",
            vlan_id=100,
            display_order=1,
        )

        session.add(classroom)
        await session.flush()

        devices = [
            Device(
                classroom_id=classroom.id,
                mac_address="AA:BB:CC:DD:EE:01",
                inventory_name="PC-01",
                hostname="PC-01",
                static_ip="192.168.100.11",
                row_index=1,
                column_index=1,
            ),
            Device(
                classroom_id=classroom.id,
                mac_address="AA:BB:CC:DD:EE:02",
                inventory_name="PC-02",
                hostname="PC-02",
                static_ip="192.168.100.12",
                row_index=1,
                column_index=2,
            ),
            Device(
                classroom_id=classroom.id,
                mac_address="AA:BB:CC:DD:EE:03",
                inventory_name="PC-03",
                hostname="PC-03",
                static_ip="192.168.100.13",
                row_index=1,
                column_index=3,
            ),
        ]

        session.add_all(devices)
        await session.commit()


def run() -> None:
    uvicorn.run(
        "cmnc_classroom_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    run()