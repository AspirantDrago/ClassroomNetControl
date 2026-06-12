from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from sqlalchemy import select

from cmnc_classroom_service.api import router
from cmnc_classroom_service.db import async_session_maker, init_db
from cmnc_classroom_service.messaging import RabbitMqPublisher
from cmnc_classroom_service.models import Classroom, Device
from cmnc_classroom_service.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await init_db()

    if settings.seed_demo_data:
        await seed_demo_data()

    publisher = RabbitMqPublisher(settings.rabbitmq_url)
    await publisher.connect()
    app.state.rabbitmq_publisher = publisher

    yield

    await publisher.close()


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