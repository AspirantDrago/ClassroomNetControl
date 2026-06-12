from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cmnc_contracts.events import WanPolicyChangedEvent
from cmnc_contracts.routing_keys import CLASSROOM_DEVICE_WAN_POLICY_CHANGED

from cmnc_classroom_service.db import get_session
from cmnc_classroom_service.messaging import RabbitMqClient
from cmnc_classroom_service.models import Classroom, Device
from cmnc_classroom_service.schemas import (
    ClassroomLayoutResponse,
    ClassroomRead,
    DesiredBlocklistItem,
    DesiredBlocklistResponse,
    DeviceRead,
    HealthResponse,
    WanPolicyChangeResponse,
)
from cmnc_classroom_service.settings import settings

router = APIRouter()


def get_rabbitmq_client(request: Request) -> RabbitMqClient:
    rabbitmq_client = getattr(request.app.state, "rabbitmq_client", None)

    if rabbitmq_client is None:
        raise RuntimeError("RabbitMQ client is not initialized")

    return rabbitmq_client


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        service=settings.service_name,
        status="ok",
    )


@router.get("/internal/classrooms", response_model=list[ClassroomRead])
async def get_classrooms(
    session: AsyncSession = Depends(get_session),
) -> list[ClassroomRead]:
    result = await session.execute(
        select(Classroom)
        .where(Classroom.is_active.is_(True))
        .order_by(Classroom.display_order, Classroom.id)
    )
    return list(result.scalars().all())


@router.get(
    "/internal/classrooms/{classroom_id}/layout",
    response_model=ClassroomLayoutResponse,
)
async def get_classroom_layout(
    classroom_id: int,
    session: AsyncSession = Depends(get_session),
) -> ClassroomLayoutResponse:
    classroom = await session.get(Classroom, classroom_id)

    if classroom is None:
        raise HTTPException(status_code=404, detail="Classroom not found")

    result = await session.execute(
        select(Device)
        .where(Device.classroom_id == classroom_id)
        .order_by(Device.row_index, Device.column_index, Device.id)
    )
    devices = list(result.scalars().all())

    return ClassroomLayoutResponse(
        classroom=ClassroomRead.model_validate(classroom),
        devices=[DeviceRead.model_validate(device) for device in devices],
    )


@router.post(
    "/internal/devices/{device_id}/wan/block",
    response_model=WanPolicyChangeResponse,
)
async def block_device_wan(
    device_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WanPolicyChangeResponse:
    return await set_device_wan_state(
        session=session,
        rabbitmq_client=get_rabbitmq_client(request),
        device_id=device_id,
        wan_allowed=False,
    )


@router.post(
    "/internal/devices/{device_id}/wan/allow",
    response_model=WanPolicyChangeResponse,
)
async def allow_device_wan(
    device_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WanPolicyChangeResponse:
    return await set_device_wan_state(
        session=session,
        rabbitmq_client=get_rabbitmq_client(request),
        device_id=device_id,
        wan_allowed=True,
    )


async def set_device_wan_state(
    session: AsyncSession,
    rabbitmq_client: RabbitMqClient,
    device_id: int,
    wan_allowed: bool,
) -> WanPolicyChangeResponse:
    device = await session.get(Device, device_id)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if wan_allowed is False and device.static_ip is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Device has no static IP. WAN blocking is allowed only "
                "for pinned devices with static IP."
            ),
        )

    if device.wan_allowed != wan_allowed:
        device.wan_allowed = wan_allowed
        device.policy_generation += 1

    device.sync_status = "pending"
    device.sync_error = None

    await session.commit()
    await session.refresh(device)

    event = WanPolicyChangedEvent(
        router_id=settings.default_router_id,
        classroom_id=device.classroom_id,
        device_id=device.id,
        policy_generation=device.policy_generation,
        wan_allowed=device.wan_allowed,
        changed_by_user_id=None,
    )

    await rabbitmq_client.publish_event(
        event=event,
        routing_key=CLASSROOM_DEVICE_WAN_POLICY_CHANGED,
    )

    return WanPolicyChangeResponse(
        device_id=device.id,
        wan_allowed=device.wan_allowed,
        policy_generation=device.policy_generation,
        sync_status=device.sync_status,
    )


@router.get(
    "/internal/routers/{router_id}/desired-blocklist",
    response_model=DesiredBlocklistResponse,
)
async def get_desired_blocklist(
    router_id: int,
    session: AsyncSession = Depends(get_session),
) -> DesiredBlocklistResponse:
    generation_result = await session.execute(
        select(func.coalesce(func.max(Device.policy_generation), 0))
        .where(Device.is_pinned.is_(True))
        .where(Device.static_ip.is_not(None))
    )
    policy_generation = int(generation_result.scalar_one())

    result = await session.execute(
        select(Device)
        .where(Device.wan_allowed.is_(False))
        .where(Device.is_pinned.is_(True))
        .where(Device.static_ip.is_not(None))
        .order_by(Device.id)
    )
    blocked_devices = list(result.scalars().all())

    blocked = [
        DesiredBlocklistItem(
            device_id=device.id,
            mac_address=device.mac_address,
            ip_address=device.static_ip or "",
            comment=(
                f"managed-by=cmnc; "
                f"device-id={device.id}; "
                f"mac={device.mac_address}; "
                f"generation={device.policy_generation}"
            ),
        )
        for device in blocked_devices
    ]

    return DesiredBlocklistResponse(
        router_id=router_id,
        policy_generation=policy_generation,
        address_list_name=settings.managed_address_list_name,
        blocked=blocked,
    )
