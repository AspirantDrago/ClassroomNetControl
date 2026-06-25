from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cmnc_contracts.events import WanPolicyChangedEvent
from cmnc_contracts.routing_keys import CLASSROOM_DEVICE_WAN_POLICY_CHANGED

from cmnc_classroom_service.db import get_session
from cmnc_classroom_service.messaging import RabbitMqClient
from cmnc_classroom_service.models import Classroom, ClassroomCamera, Device
from cmnc_classroom_service.schemas import (
    BulkWanPolicyChangeResponse,
    ClassroomCameraCreate,
    ClassroomCameraRead,
    ClassroomCameraSourceResponse,
    ClassroomCameraUpdate,
    ClassroomCreate,
    ClassroomLayoutResponse,
    ClassroomRead,
    ClassroomUpdate,
    DesiredBlocklistItem,
    DesiredBlocklistResponse,
    DeviceCreate,
    DevicePinRequest,
    DeviceRead,
    DeviceUpdate,
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
    classrooms = list(result.scalars().all())
    return [ClassroomRead.model_validate(classroom) for classroom in classrooms]


@router.get("/internal/classrooms/{classroom_id}", response_model=ClassroomRead)
async def get_classroom(
    classroom_id: int,
    session: AsyncSession = Depends(get_session),
) -> ClassroomRead:
    classroom = await session.get(Classroom, classroom_id)

    if classroom is None or not classroom.is_active:
        raise HTTPException(status_code=404, detail="Classroom not found")

    return ClassroomRead.model_validate(classroom)


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
        .where(Device.is_pinned.is_(True))
        .order_by(Device.row_index, Device.column_index, Device.id)
    )
    devices = list(result.scalars().all())

    camera_result = await session.execute(
        select(ClassroomCamera)
        .where(ClassroomCamera.classroom_id == classroom_id)
        .order_by(ClassroomCamera.sort_order, ClassroomCamera.id)
    )
    cameras = list(camera_result.scalars().all())

    return ClassroomLayoutResponse(
        classroom=ClassroomRead.model_validate(classroom),
        devices=[DeviceRead.model_validate(device) for device in devices],
        cameras=[ClassroomCameraRead.model_validate(camera) for camera in cameras],
    )


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def get_camera_qualities(camera: ClassroomCamera) -> list[str]:
    qualities: list[str] = []

    if camera.rtsp_main_stream:
        qualities.append("main")

    if camera.rtsp_sub_stream:
        qualities.append("sub")

    return qualities


def ensure_camera_has_valid_streams(
    *,
    rtsp_main_stream: str | None,
    rtsp_sub_stream: str | None,
    default_quality: str,
    is_enabled: bool,
) -> str:
    main = normalize_optional_text(rtsp_main_stream)
    sub = normalize_optional_text(rtsp_sub_stream)

    if default_quality not in {"main", "sub"}:
        raise HTTPException(status_code=422, detail="default_quality must be main or sub")

    if is_enabled and main is None and sub is None:
        raise HTTPException(
            status_code=422,
            detail="Enabled camera must have at least one RTSP stream",
        )

    if default_quality == "sub" and sub is None and main is not None:
        return "main"

    if default_quality == "main" and main is None and sub is not None:
        return "sub"

    return default_quality


def get_camera_rtsp_stream(camera: ClassroomCamera, quality: str) -> str:
    if quality == "main":
        value = camera.rtsp_main_stream
    elif quality == "sub":
        value = camera.rtsp_sub_stream
    else:
        raise HTTPException(status_code=422, detail="quality must be main or sub")

    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=404, detail="Camera stream is not configured")

    return value.strip()


async def get_camera_or_404(
    session: AsyncSession,
    classroom_id: int,
    camera_id: int,
) -> ClassroomCamera:
    camera = await session.get(ClassroomCamera, camera_id)

    if camera is None or camera.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="Camera not found")

    return camera


@router.get(
    "/internal/classrooms/{classroom_id}/cameras",
    response_model=list[ClassroomCameraRead],
)
async def get_classroom_cameras(
    classroom_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[ClassroomCameraRead]:
    await ensure_classroom_exists(session, classroom_id)

    result = await session.execute(
        select(ClassroomCamera)
        .where(ClassroomCamera.classroom_id == classroom_id)
        .order_by(ClassroomCamera.sort_order, ClassroomCamera.id)
    )
    cameras = list(result.scalars().all())

    return [ClassroomCameraRead.model_validate(camera) for camera in cameras]


@router.post(
    "/internal/classrooms/{classroom_id}/cameras",
    response_model=ClassroomCameraRead,
    status_code=201,
)
async def create_classroom_camera(
    classroom_id: int,
    payload: ClassroomCameraCreate,
    session: AsyncSession = Depends(get_session),
) -> ClassroomCameraRead:
    await ensure_classroom_exists(session, classroom_id)

    rtsp_main_stream = normalize_optional_text(payload.rtsp_main_stream)
    rtsp_sub_stream = normalize_optional_text(payload.rtsp_sub_stream)
    default_quality = ensure_camera_has_valid_streams(
        rtsp_main_stream=rtsp_main_stream,
        rtsp_sub_stream=rtsp_sub_stream,
        default_quality=payload.default_quality,
        is_enabled=payload.is_enabled,
    )

    camera = ClassroomCamera(
        classroom_id=classroom_id,
        name=payload.name.strip(),
        sort_order=payload.sort_order,
        is_enabled=payload.is_enabled,
        rtsp_main_stream=rtsp_main_stream,
        rtsp_sub_stream=rtsp_sub_stream,
        default_quality=default_quality,
    )
    session.add(camera)

    await commit_or_409(
        session,
        detail="Camera with the same sort order already exists in classroom",
    )
    await session.refresh(camera)

    return ClassroomCameraRead.model_validate(camera)


@router.patch(
    "/internal/classrooms/{classroom_id}/cameras/{camera_id}",
    response_model=ClassroomCameraRead,
)
async def update_classroom_camera(
    classroom_id: int,
    camera_id: int,
    payload: ClassroomCameraUpdate,
    session: AsyncSession = Depends(get_session),
) -> ClassroomCameraRead:
    camera = await get_camera_or_404(session, classroom_id, camera_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "name" in update_data and isinstance(update_data["name"], str):
        update_data["name"] = update_data["name"].strip()

    if "rtsp_main_stream" in update_data:
        update_data["rtsp_main_stream"] = normalize_optional_text(
            update_data["rtsp_main_stream"]
        )

    if "rtsp_sub_stream" in update_data:
        update_data["rtsp_sub_stream"] = normalize_optional_text(
            update_data["rtsp_sub_stream"]
        )

    final_main = update_data.get("rtsp_main_stream", camera.rtsp_main_stream)
    final_sub = update_data.get("rtsp_sub_stream", camera.rtsp_sub_stream)
    final_quality = update_data.get("default_quality", camera.default_quality)
    final_enabled = update_data.get("is_enabled", camera.is_enabled)

    update_data["default_quality"] = ensure_camera_has_valid_streams(
        rtsp_main_stream=final_main,
        rtsp_sub_stream=final_sub,
        default_quality=final_quality,
        is_enabled=final_enabled,
    )

    for field_name, value in update_data.items():
        setattr(camera, field_name, value)

    await commit_or_409(
        session,
        detail="Camera update violates database constraints",
    )
    await session.refresh(camera)

    return ClassroomCameraRead.model_validate(camera)


@router.delete(
    "/internal/classrooms/{classroom_id}/cameras/{camera_id}",
    status_code=204,
)
async def delete_classroom_camera(
    classroom_id: int,
    camera_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    camera = await get_camera_or_404(session, classroom_id, camera_id)
    await session.delete(camera)
    await session.commit()
    return Response(status_code=204)


@router.get(
    "/internal/classrooms/{classroom_id}/cameras/{camera_id}/source",
    response_model=ClassroomCameraSourceResponse,
)
async def get_classroom_camera_source(
    classroom_id: int,
    camera_id: int,
    quality: str,
    session: AsyncSession = Depends(get_session),
) -> ClassroomCameraSourceResponse:
    camera = await get_camera_or_404(session, classroom_id, camera_id)

    if not camera.is_enabled:
        raise HTTPException(status_code=404, detail="Camera not found")

    rtsp_url = get_camera_rtsp_stream(camera, quality)

    return ClassroomCameraSourceResponse(
        camera_id=camera.id,
        classroom_id=camera.classroom_id,
        quality=quality,
        rtsp_url=rtsp_url,
    )


@router.get(
    "/internal/devices/{device_id}",
    response_model=DeviceRead,
)
async def get_device(
    device_id: int,
    session: AsyncSession = Depends(get_session),
) -> DeviceRead:
    device = await session.get(Device, device_id)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    return DeviceRead.model_validate(device)


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

    classroom = await ensure_classroom_exists(session, device.classroom_id)

    if wan_allowed is False:
        if device.wan_protected:
            raise HTTPException(
                status_code=409,
                detail="Device is protected from WAN blocking.",
            )

        if not device.is_pinned:
            raise HTTPException(
                status_code=409,
                detail="Device is not pinned. WAN blocking is allowed only for pinned devices.",
            )

        if device.static_ip is None:
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
        router_id=classroom.router_id,
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


@router.post(
    "/internal/classrooms/{classroom_id}/wan/block-all",
    response_model=BulkWanPolicyChangeResponse,
)
async def block_classroom_wan(
    classroom_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BulkWanPolicyChangeResponse:
    return await set_classroom_wan_state(
        session=session,
        rabbitmq_client=get_rabbitmq_client(request),
        classroom_id=classroom_id,
        wan_allowed=False,
    )


@router.post(
    "/internal/classrooms/{classroom_id}/wan/allow-all",
    response_model=BulkWanPolicyChangeResponse,
)
async def allow_classroom_wan(
    classroom_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BulkWanPolicyChangeResponse:
    return await set_classroom_wan_state(
        session=session,
        rabbitmq_client=get_rabbitmq_client(request),
        classroom_id=classroom_id,
        wan_allowed=True,
    )


async def set_classroom_wan_state(
    session: AsyncSession,
    rabbitmq_client: RabbitMqClient,
    classroom_id: int,
    wan_allowed: bool,
) -> BulkWanPolicyChangeResponse:
    classroom = await ensure_classroom_exists(session, classroom_id)

    result = await session.execute(
        select(Device)
        .where(Device.classroom_id == classroom_id)
        .where(Device.is_pinned.is_(True))
        .where(Device.wan_protected.is_(False))
        .order_by(Device.id)
    )
    devices = list(result.scalars().all())

    changed_count = 0
    queued_devices: list[Device] = []

    for device in devices:
        if device.wan_allowed != wan_allowed:
            device.wan_allowed = wan_allowed
            device.policy_generation += 1
            changed_count += 1
            device.sync_status = "pending"
            device.sync_error = None
            queued_devices.append(device)
            continue

        if device.sync_status != "applied":
            device.sync_status = "pending"
            device.sync_error = None
            queued_devices.append(device)

    policy_generation = max(
        (device.policy_generation for device in devices),
        default=0,
    )

    await session.commit()

    if queued_devices:
        event_device = queued_devices[0]
        event = WanPolicyChangedEvent(
            router_id=classroom.router_id,
            classroom_id=classroom_id,
            device_id=event_device.id,
            policy_generation=policy_generation,
            wan_allowed=wan_allowed,
            changed_by_user_id=None,
        )

        await rabbitmq_client.publish_event(
            event=event,
            routing_key=CLASSROOM_DEVICE_WAN_POLICY_CHANGED,
        )

    return BulkWanPolicyChangeResponse(
        classroom_id=classroom_id,
        wan_allowed=wan_allowed,
        affected_count=len(devices),
        changed_count=changed_count,
        queued_count=len(queued_devices),
        device_ids=[device.id for device in devices],
        policy_generation=policy_generation,
        sync_status="pending" if queued_devices else "applied",
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
        .join(Classroom, Classroom.id == Device.classroom_id)
        .where(Classroom.router_id == router_id)
        .where(Device.is_pinned.is_(True))
        .where(Device.static_ip.is_not(None))
    )
    policy_generation = int(generation_result.scalar_one())

    result = await session.execute(
        select(Device)
        .join(Classroom, Classroom.id == Device.classroom_id)
        .where(Classroom.router_id == router_id)
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
                f"router-id={router_id}; "
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


def normalize_mac_address(mac_address: str) -> str:
    return mac_address.strip().upper()


async def ensure_classroom_exists(
    session: AsyncSession,
    classroom_id: int,
) -> Classroom:
    classroom = await session.get(Classroom, classroom_id)

    if classroom is None:
        raise HTTPException(status_code=404, detail="Classroom not found")

    return classroom


async def commit_or_409(
    session: AsyncSession,
    detail: str = "Database constraint violation",
) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc


@router.post(
    "/internal/classrooms",
    response_model=ClassroomRead,
    status_code=201,
)
async def create_classroom(
    payload: ClassroomCreate,
    session: AsyncSession = Depends(get_session),
) -> ClassroomRead:
    classroom = Classroom(
        router_id=payload.router_id,
        name=payload.name,
        subnet_cidr=payload.subnet_cidr,
        vlan_id=payload.vlan_id,
        display_order=payload.display_order,
        is_active=payload.is_active,
        is_service=payload.is_service,
    )

    session.add(classroom)

    await commit_or_409(
        session,
        detail="Classroom with the same unique fields already exists",
    )
    await session.refresh(classroom)

    return ClassroomRead.model_validate(classroom)


@router.patch(
    "/internal/classrooms/{classroom_id}",
    response_model=ClassroomRead,
)
async def update_classroom(
    classroom_id: int,
    payload: ClassroomUpdate,
    session: AsyncSession = Depends(get_session),
) -> ClassroomRead:
    classroom = await session.get(Classroom, classroom_id)

    if classroom is None:
        raise HTTPException(status_code=404, detail="Classroom not found")

    update_data = payload.model_dump(exclude_unset=True)

    if update_data.get("router_id") is None and "router_id" in update_data:
        raise HTTPException(status_code=422, detail="router_id cannot be null")

    for field_name, value in update_data.items():
        setattr(classroom, field_name, value)

    await commit_or_409(
        session,
        detail="Classroom update violates database constraints",
    )
    await session.refresh(classroom)

    return ClassroomRead.model_validate(classroom)


@router.post(
    "/internal/devices",
    response_model=DeviceRead,
    status_code=201,
)
async def create_device(
    payload: DeviceCreate,
    session: AsyncSession = Depends(get_session),
) -> DeviceRead:
    await ensure_classroom_exists(session, payload.classroom_id)

    normalized_mac = normalize_mac_address(payload.mac_address)

    existing_result = await session.execute(
        select(Device).where(Device.mac_address == normalized_mac)
    )
    existing_device = existing_result.scalar_one_or_none()

    if existing_device is not None:
        if existing_device.is_pinned:
            raise HTTPException(
                status_code=409,
                detail="Device with the same MAC already exists",
            )

        if not payload.is_pinned:
            raise HTTPException(
                status_code=409,
                detail="Device with the same MAC already exists",
            )

        existing_device.classroom_id = payload.classroom_id
        existing_device.inventory_name = payload.inventory_name
        existing_device.hostname = payload.hostname
        existing_device.static_ip = payload.static_ip
        existing_device.row_index = payload.row_index
        existing_device.column_index = payload.column_index
        existing_device.is_pinned = True
        existing_device.wan_allowed = True if payload.wan_protected else payload.wan_allowed
        existing_device.wan_protected = payload.wan_protected
        existing_device.sync_status = "applied"
        existing_device.sync_error = None

        await commit_or_409(
            session,
            detail="Device with the same grid position already exists",
        )
        await session.refresh(existing_device)

        return DeviceRead.model_validate(existing_device)

    device = Device(
        classroom_id=payload.classroom_id,
        mac_address=normalized_mac,
        inventory_name=payload.inventory_name,
        hostname=payload.hostname,
        static_ip=payload.static_ip,
        row_index=payload.row_index,
        column_index=payload.column_index,
        is_pinned=payload.is_pinned,
        wan_allowed=True if payload.wan_protected else payload.wan_allowed,
        wan_protected=payload.wan_protected,
        sync_status="applied",
        sync_error=None,
    )

    session.add(device)

    await commit_or_409(
        session,
        detail="Device with the same MAC or grid position already exists",
    )
    await session.refresh(device)

    return DeviceRead.model_validate(device)


@router.patch(
    "/internal/devices/{device_id}",
    response_model=DeviceRead,
)
async def update_device(
    device_id: int,
    payload: DeviceUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DeviceRead:
    device = await session.get(Device, device_id)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    update_data = payload.model_dump(exclude_unset=True)

    if "classroom_id" in update_data and update_data["classroom_id"] is not None:
        await ensure_classroom_exists(session, update_data["classroom_id"])

    if "mac_address" in update_data and update_data["mac_address"] is not None:
        update_data["mac_address"] = normalize_mac_address(update_data["mac_address"])

    should_publish_policy_event = False

    if update_data.get("wan_protected") is True and device.wan_allowed is False:
        device.wan_allowed = True
        device.policy_generation += 1
        device.sync_status = "pending"
        device.sync_error = None
        should_publish_policy_event = True

    for field_name, value in update_data.items():
        setattr(device, field_name, value)

    await commit_or_409(
        session,
        detail="Device update violates MAC or grid position constraints",
    )
    await session.refresh(device)

    if should_publish_policy_event:
        classroom = await ensure_classroom_exists(session, device.classroom_id)
        event = WanPolicyChangedEvent(
            router_id=classroom.router_id,
            classroom_id=device.classroom_id,
            device_id=device.id,
            policy_generation=device.policy_generation,
            wan_allowed=device.wan_allowed,
            changed_by_user_id=None,
        )

        await get_rabbitmq_client(request).publish_event(
            event=event,
            routing_key=CLASSROOM_DEVICE_WAN_POLICY_CHANGED,
        )

    return DeviceRead.model_validate(device)


@router.post(
    "/internal/devices/{device_id}/pin",
    response_model=DeviceRead,
)
async def pin_device(
    device_id: int,
    payload: DevicePinRequest,
    session: AsyncSession = Depends(get_session),
) -> DeviceRead:
    await ensure_classroom_exists(session, payload.classroom_id)

    device = await session.get(Device, device_id)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    device.classroom_id = payload.classroom_id
    device.inventory_name = payload.inventory_name
    device.hostname = payload.hostname
    device.static_ip = payload.static_ip
    device.row_index = payload.row_index
    device.column_index = payload.column_index
    device.is_pinned = True

    await commit_or_409(
        session,
        detail="Pinning device violates grid position constraints",
    )
    await session.refresh(device)

    return DeviceRead.model_validate(device)


@router.post(
    "/internal/devices/{device_id}/unpin",
    response_model=DeviceRead,
)
async def unpin_device(
    device_id: int,
    session: AsyncSession = Depends(get_session),
) -> DeviceRead:
    device = await session.get(Device, device_id)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.wan_allowed is False:
        raise HTTPException(
            status_code=409,
            detail="Cannot unpin device while WAN is blocked. Allow WAN first.",
        )

    device.is_pinned = False
    device.row_index = None
    device.column_index = None
    device.static_ip = None
    device.wan_protected = False
    device.sync_status = "applied"
    device.sync_error = None

    await commit_or_409(
        session,
        detail="Unpin device failed",
    )
    await session.refresh(device)

    return DeviceRead.model_validate(device)
