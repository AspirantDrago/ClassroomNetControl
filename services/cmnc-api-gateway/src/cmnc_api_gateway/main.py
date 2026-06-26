import ipaddress
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from cmnc_api_gateway.clients import ServiceClient
from cmnc_api_gateway.schemas import (
    ClassroomDashboardResponse,
    DashboardDevice,
    DynamicDevice,
    HealthResponse,
    LoginRequest,
    PrincipalResponse,
    ResolvePrincipalResponse,
    TokenResponse,
)
from cmnc_api_gateway.settings import settings
from cmnc_contracts.permissions import (
    ROLE_ADMIN,
    ROLE_MODERATOR,
    ROLE_SUPERADMIN,
    ROLE_TEACHER,
    ROLE_WORKSTATION,
    PERMISSION_CLASSROOMS_MANAGE,
    PERMISSION_CLASSROOMS_READ_ALL,
    PERMISSION_DEVICES_MANAGE,
    PERMISSION_USERS_MANAGE_ADMIN,
    PERMISSION_USERS_MANAGE_LOWER,
    PERMISSION_WAN_CONTROL_ALL,
    PERMISSION_WAN_CONTROL_ASSIGNED,
    PERMISSION_WORKSTATIONS_MANAGE,
)

app = FastAPI(title=settings.service_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

auth_client = ServiceClient(settings.auth_service_url)
classroom_client = ServiceClient(settings.classroom_service_url)
inventory_client = ServiceClient(settings.inventory_service_url)
poller_client = ServiceClient(settings.mikrotik_poller_service_url)
policy_sync_client = ServiceClient(settings.policy_sync_service_url)
maintenance_client = ServiceClient(settings.maintenance_service_url)
camera_client = ServiceClient(settings.camera_service_url)


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None

    prefix = "Bearer "

    if not authorization.startswith(prefix):
        return None

    token = authorization.removeprefix(prefix).strip()
    return token or None


def get_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client is None:
        return None
    return request.client.host


async def get_current_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> PrincipalResponse:
    bearer_token = extract_bearer_token(authorization)
    client_ip = get_client_ip(request)

    try:
        data = await auth_client.post_json(
            "/internal/auth/resolve-principal",
            json={
                "bearer_token": bearer_token,
                "client_ip": client_ip,
            },
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc

    response = ResolvePrincipalResponse.model_validate(data)

    if not response.authenticated or response.principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    return response.principal


def has_permission(principal: PrincipalResponse, permission: str) -> bool:
    return permission in principal.permissions


def require_permission(principal: PrincipalResponse, permission: str) -> None:
    if not has_permission(principal, permission):
        raise HTTPException(status_code=403, detail="Permission denied")


def require_any_permission(principal: PrincipalResponse, permissions: set[str]) -> None:
    if any(has_permission(principal, permission) for permission in permissions):
        return

    raise HTTPException(status_code=403, detail="Permission denied")


def require_user_role_management(
    principal: PrincipalResponse,
    role: str,
) -> None:
    if role == ROLE_WORKSTATION:
        raise HTTPException(
            status_code=422,
            detail="Workstation role must be managed through workstation endpoints",
        )

    if role in {ROLE_SUPERADMIN, ROLE_ADMIN}:
        require_permission(principal, PERMISSION_USERS_MANAGE_ADMIN)
        return

    if role in {ROLE_MODERATOR, ROLE_TEACHER}:
        require_permission(principal, PERMISSION_USERS_MANAGE_LOWER)
        return

    raise HTTPException(status_code=422, detail="Unknown role")


def filter_manageable_users(
    principal: PrincipalResponse,
    users: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if has_permission(principal, PERMISSION_USERS_MANAGE_ADMIN):
        return users

    if has_permission(principal, PERMISSION_USERS_MANAGE_LOWER):
        return [
            user
            for user in users
            if user.get("role") in {ROLE_MODERATOR, ROLE_TEACHER}
        ]

    return []


def require_workstation_management(principal: PrincipalResponse) -> None:
    require_permission(principal, PERMISSION_WORKSTATIONS_MANAGE)


def require_maintenance_access(principal: PrincipalResponse) -> None:
    if principal.role in {ROLE_SUPERADMIN, ROLE_ADMIN}:
        return

    raise HTTPException(status_code=403, detail="Permission denied")


def ensure_workstation_payload_role(payload: dict[str, Any]) -> None:
    role = payload.get("role", ROLE_WORKSTATION)

    if role != ROLE_WORKSTATION:
        raise HTTPException(
            status_code=422,
            detail="Workstation endpoint accepts only workstation role",
        )


def can_access_all_classrooms(principal: PrincipalResponse) -> bool:
    return has_permission(principal, PERMISSION_CLASSROOMS_READ_ALL)


def can_access_service_classrooms(principal: PrincipalResponse) -> bool:
    return principal.role in {ROLE_SUPERADMIN, ROLE_ADMIN}


def can_view_dynamic_devices(principal: PrincipalResponse) -> bool:
    return principal.role in {ROLE_SUPERADMIN, ROLE_ADMIN}


def can_read_classroom_rtsp(principal: PrincipalResponse) -> bool:
    return has_permission(principal, PERMISSION_CLASSROOMS_MANAGE)


def get_camera_qualities(camera: dict[str, Any]) -> list[str]:
    qualities: list[str] = []

    if camera.get("rtsp_main_stream"):
        qualities.append("main")

    if camera.get("rtsp_sub_stream"):
        qualities.append("sub")

    return qualities



def get_camera_info(camera: dict[str, Any]) -> dict[str, Any]:
    qualities = get_camera_qualities(camera)
    default_quality = camera.get("default_quality")

    if default_quality not in qualities and qualities:
        default_quality = "sub" if "sub" in qualities else qualities[0]

    return {
        "id": camera.get("id"),
        "name": camera.get("name") or "Камера",
        "enabled": bool(camera.get("is_enabled") and qualities),
        "qualities": qualities,
        "default_quality": default_quality or "sub",
    }



def get_cameras_info(cameras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        get_camera_info(camera)
        for camera in cameras
        if isinstance(camera, dict) and camera.get("is_enabled") is True
    ]


def get_requested_camera_quality(
    payload: dict[str, Any],
    camera: dict[str, Any],
) -> str:
    raw_quality = payload.get("quality")
    qualities = get_camera_qualities(camera)

    if raw_quality is None:
        default_quality = camera.get("default_quality")

        if default_quality in qualities:
            return str(default_quality)

        if len(qualities) == 1:
            return qualities[0]

        if "sub" in qualities:
            return "sub"

        raise HTTPException(status_code=422, detail="quality is required")

    if raw_quality not in {"main", "sub"}:
        raise HTTPException(status_code=422, detail="quality must be main or sub")

    if raw_quality not in qualities:
        raise HTTPException(status_code=404, detail="Camera stream is not configured")

    return str(raw_quality)


def ensure_camera_belongs_to_classroom(
    classroom_id: int,
    camera: dict[str, Any],
) -> None:
    if camera.get("classroom_id") != classroom_id:
        raise HTTPException(status_code=404, detail="Camera not found")


async def get_classroom_cameras_or_502(classroom_id: int) -> list[dict[str, Any]]:
    try:
        cameras = await classroom_client.get_json(
            f"/internal/classrooms/{classroom_id}/cameras"
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Classroom not found") from exc
        raise HTTPException(status_code=502, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Classroom service unavailable: {exc}",
        ) from exc

    if not isinstance(cameras, list):
        raise HTTPException(status_code=502, detail="Invalid classroom service response")

    return [camera for camera in cameras if isinstance(camera, dict)]


async def get_camera_or_404(classroom_id: int, camera_id: int) -> dict[str, Any]:
    cameras = await get_classroom_cameras_or_502(classroom_id)

    for camera in cameras:
        if camera.get("id") == camera_id:
            ensure_camera_belongs_to_classroom(classroom_id, camera)
            return camera

    raise HTTPException(status_code=404, detail="Camera not found")



async def get_camera_source(
    classroom_id: int,
    camera_id: int,
    quality: str,
) -> dict[str, Any]:
    try:
        source = await classroom_client.get_json(
            f"/internal/classrooms/{classroom_id}/cameras/{camera_id}/source?quality={quality}"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Classroom service unavailable: {exc}",
        ) from exc

    if not isinstance(source, dict) or not isinstance(source.get("rtsp_url"), str):
        raise HTTPException(status_code=502, detail="Invalid classroom service response")

    return source


async def stream_camera_service_response(path: str) -> StreamingResponse:
    client = httpx.AsyncClient(timeout=None)

    try:
        request = client.build_request(
            "GET",
            f"{settings.camera_service_url}{path}",
        )
        upstream = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"Camera service unavailable: {exc}",
        ) from exc

    if upstream.status_code != 200:
        detail = (await upstream.aread()).decode("utf-8", errors="replace")
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    async def iterator():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        iterator(),
        media_type=upstream.headers.get("content-type") or "application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


def serialize_classroom_for_principal(
    principal: PrincipalResponse,
    classroom: dict[str, Any],
) -> dict[str, Any]:
    data = dict(classroom)

    if not can_read_classroom_rtsp(principal):
        data.pop("rtsp_main_stream", None)
        data.pop("rtsp_sub_stream", None)

    return data


async def get_classroom_or_404(classroom_id: int) -> dict[str, Any]:
    try:
        data = await classroom_client.get_json(f"/internal/classrooms/{classroom_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Classroom not found") from exc

        raise HTTPException(status_code=502, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Classroom service unavailable: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Invalid classroom service response")

    return data


def ensure_service_classroom_access(
    principal: PrincipalResponse,
    classroom: dict[str, Any],
) -> None:
    if classroom.get("is_service") is not True:
        return

    if can_access_service_classrooms(principal):
        return

    raise HTTPException(status_code=404, detail="Classroom not found")


async def ensure_classroom_access(
    principal: PrincipalResponse,
    classroom_id: int,
) -> None:
    classroom = await get_classroom_or_404(classroom_id)
    ensure_service_classroom_access(principal, classroom)

    if can_access_all_classrooms(principal):
        return

    if classroom_id not in principal.classroom_ids:
        raise HTTPException(status_code=403, detail="Classroom access denied")


def require_wan_control_permission(principal: PrincipalResponse) -> None:
    if has_permission(principal, PERMISSION_WAN_CONTROL_ALL):
        return

    if has_permission(principal, PERMISSION_WAN_CONTROL_ASSIGNED):
        return

    raise HTTPException(status_code=403, detail="WAN control is not allowed")


def ip_in_subnet(
    ip: str | None,
    subnet_cidr: str,
) -> bool:
    if not ip:
        return False

    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(subnet_cidr, strict=False)
    except ValueError:
        return False


def normalize_mac_address(mac_address: str) -> str:
    return mac_address.strip().upper()


def ensure_ip_belongs_to_classroom(
    ip: str | None,
    subnet_cidr: str,
    field_name: str,
) -> None:
    if not ip:
        return

    if not ip_in_subnet(ip, subnet_cidr):
        raise HTTPException(
            status_code=409,
            detail=f"{field_name} does not belong to classroom subnet",
        )


def ensure_observed_device_has_static_lease(
    observed_device: dict[str, Any],
) -> None:
    dynamic = observed_device.get("dynamic")

    if dynamic is not False:
        raise HTTPException(
            status_code=409,
            detail=(
                "Device cannot be pinned because MikroTik DHCP lease is not static. "
                "Create a static DHCP lease on MikroTik first."
            ),
        )

    if not observed_device.get("active_ip"):
        raise HTTPException(
            status_code=409,
            detail="Device cannot be pinned because static IP was not received from MikroTik.",
        )


async def get_device_classroom_id(device_id: int) -> int | None:
    try:
        data = await classroom_client.get_json(f"/internal/devices/{device_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise

    if not isinstance(data, dict):
        return None

    classroom_id = data.get("classroom_id")

    if not isinstance(classroom_id, int):
        return None

    return classroom_id


async def ensure_wan_device_access(
    principal: PrincipalResponse,
    device_id: int,
) -> None:
    require_wan_control_permission(principal)

    classroom_id = await get_device_classroom_id(device_id)

    if classroom_id is None:
        raise HTTPException(status_code=404, detail="Device not found")

    await ensure_classroom_access(principal, classroom_id)


async def ensure_wan_classroom_access(
    principal: PrincipalResponse,
    classroom_id: int,
) -> None:
    require_wan_control_permission(principal)
    await ensure_classroom_access(principal, classroom_id)


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed


def get_pinned_macs(devices: list[dict[str, Any]]) -> set[str]:
    return {
        device["mac_address"].upper()
        for device in devices
        if isinstance(device.get("mac_address"), str)
    }


def find_observed_device_by_id(
    observed_devices: list[dict[str, Any]],
    observed_device_id: int,
) -> dict[str, Any] | None:
    for item in observed_devices:
        if item.get("id") == observed_device_id:
            return item

    return None


def ensure_observed_device_is_unpinned_in_classroom(
    observed_device: dict[str, Any],
    pinned_macs: set[str],
    subnet_cidr: str,
) -> None:
    mac_address = observed_device.get("mac_address")

    if not isinstance(mac_address, str):
        raise HTTPException(status_code=502, detail="Invalid inventory service response")

    if mac_address.upper() in pinned_macs:
        raise HTTPException(
            status_code=409,
            detail="Observed device is already pinned and cannot be deleted from inventory",
        )

    if not ip_in_subnet(observed_device.get("active_ip"), subnet_cidr):
        raise HTTPException(
            status_code=404,
            detail="Observed device does not belong to this classroom subnet",
        )


def get_classroom_router_id(classroom: dict[str, Any]) -> int:
    router_id = classroom.get("router_id")

    if not isinstance(router_id, int):
        raise HTTPException(status_code=502, detail="Invalid classroom service response")

    return router_id


async def get_classroom_layout_and_observed_devices(
    classroom_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    layout = await classroom_client.get_json(
        f"/internal/classrooms/{classroom_id}/layout"
    )

    if not isinstance(layout, dict):
        raise HTTPException(status_code=502, detail="Invalid service response")

    classroom = layout.get("classroom")
    devices = layout.get("devices")

    if not isinstance(classroom, dict) or not isinstance(devices, list):
        raise HTTPException(status_code=502, detail="Invalid service response")

    router_id = get_classroom_router_id(classroom)
    observed = await inventory_client.get_json(
        f"/internal/routers/{router_id}/observed-devices"
    )

    if not isinstance(observed, dict):
        raise HTTPException(status_code=502, detail="Invalid service response")

    observed_devices = observed.get("devices")

    if not isinstance(observed_devices, list):
        raise HTTPException(status_code=502, detail="Invalid service response")

    return classroom, devices, observed_devices


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        service=settings.service_name,
        status="ok",
    )


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    try:
        data = await auth_client.post_json(
            "/internal/auth/login",
            json=payload.model_dump(),
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc

    return TokenResponse.model_validate(data)


@app.get("/api/me", response_model=PrincipalResponse)
async def me(
    request: Request,
    authorization: str | None = Header(default=None),
) -> PrincipalResponse:
    return await get_current_principal(request, authorization)


@app.patch("/api/me", response_model=PrincipalResponse)
async def update_me(
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> PrincipalResponse:
    principal = await get_current_principal(request, authorization)

    if principal.principal_type != "user":
        raise HTTPException(
            status_code=403,
            detail="Only user accounts can be updated",
        )

    display_name = payload.get("display_name")

    if not isinstance(display_name, str) or not display_name.strip():
        raise HTTPException(status_code=422, detail="display_name is required")

    account_payload: dict[str, Any] = {
        "display_name": display_name.strip(),
    }

    password = payload.get("password")

    if password is not None:
        if not isinstance(password, str) or not password.strip():
            raise HTTPException(
                status_code=422,
                detail="password must be a non-empty string",
            )

        account_payload["password"] = password

    try:
        data = await auth_client.patch_json(
            f"/internal/auth/users/{principal.id}/account",
            json=account_payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc

    return PrincipalResponse.model_validate(data)


@app.get("/api/classrooms")
async def get_classrooms(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)

    try:
        classrooms = await classroom_client.get_json("/internal/classrooms")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Classroom service unavailable: {exc}") from exc

    if not isinstance(classrooms, list):
        raise HTTPException(status_code=502, detail="Invalid classroom service response")

    visible_classrooms = [
        classroom
        for classroom in classrooms
        if isinstance(classroom, dict)
        and (classroom.get("is_service") is not True or can_access_service_classrooms(principal))
    ]

    if can_access_all_classrooms(principal):
        return [
            serialize_classroom_for_principal(principal, classroom)
            for classroom in visible_classrooms
        ]

    return [
        serialize_classroom_for_principal(principal, classroom)
        for classroom in visible_classrooms
        if classroom["id"] in principal.classroom_ids
    ]


@app.get(
    "/api/classrooms/{classroom_id}/dashboard",
    response_model=ClassroomDashboardResponse,
)
async def get_classroom_dashboard(
    classroom_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> ClassroomDashboardResponse:
    principal = await get_current_principal(request, authorization)
    await ensure_classroom_access(principal, classroom_id)

    try:
        layout = await classroom_client.get_json(
            f"/internal/classrooms/{classroom_id}/layout"
        )
        classroom = layout["classroom"]
        router_id = get_classroom_router_id(classroom)
        observed = await inventory_client.get_json(
            f"/internal/routers/{router_id}/observed-devices"
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Classroom not found") from exc

        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    classroom = layout["classroom"]
    devices = layout["devices"]
    observed_devices = observed["devices"]
    layout_cameras = layout.get("cameras", [])

    if not isinstance(layout_cameras, list):
        raise HTTPException(status_code=502, detail="Invalid classroom service response")

    cameras = get_cameras_info([
        item for item in layout_cameras if isinstance(item, dict)
    ])
    observed_by_mac = {
        item["mac_address"].upper(): item
        for item in observed_devices
    }

    pinned_macs = {
        device["mac_address"].upper()
        for device in devices
    }

    dashboard_devices: list[DashboardDevice] = []

    for device in devices:
        observed_device = observed_by_mac.get(device["mac_address"].upper())

        dashboard_devices.append(
            DashboardDevice(
                **device,
                active_ip=observed_device["active_ip"] if observed_device else None,
                observed_hostname=observed_device["hostname"] if observed_device else None,
                online=bool(observed_device and observed_device["active"]),
                last_seen_at=observed_device["last_seen_at"] if observed_device else None,
            )
        )

    dynamic_devices: list[DynamicDevice] = []

    if can_view_dynamic_devices(principal):
        for item in observed_devices:
            mac = item["mac_address"].upper()

            if mac in pinned_macs:
                continue

            if not ip_in_subnet(item["active_ip"], classroom["subnet_cidr"]):
                continue

            dynamic_devices.append(DynamicDevice.model_validate(item))

    return ClassroomDashboardResponse(
        classroom=serialize_classroom_for_principal(principal, classroom),
        devices=dashboard_devices,
        dynamic_devices=dynamic_devices,
        cameras=cameras,
    )


@app.post("/api/admin/classrooms/{classroom_id}/observed-devices/{observed_device_id}/delete")
async def admin_delete_observed_device(
    classroom_id: int,
    observed_device_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_DEVICES_MANAGE)

    try:
        classroom, devices, observed_devices = await get_classroom_layout_and_observed_devices(
            classroom_id
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Classroom not found") from exc
        raise HTTPException(status_code=502, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    observed_device = find_observed_device_by_id(
        observed_devices,
        observed_device_id,
    )

    if observed_device is None:
        raise HTTPException(status_code=404, detail="Observed device not found")

    ensure_observed_device_is_unpinned_in_classroom(
        observed_device=observed_device,
        pinned_macs=get_pinned_macs(devices),
        subnet_cidr=classroom["subnet_cidr"],
    )

    if observed_device.get("active") is not False:
        raise HTTPException(
            status_code=409,
            detail="Only inactive observed devices can be deleted manually",
        )

    try:
        return await inventory_client.post_json(
            f"/internal/routers/{get_classroom_router_id(classroom)}/observed-devices/delete",
            json={"ids": [observed_device_id]},
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Inventory service unavailable: {exc}",
        ) from exc


@app.post("/api/admin/classrooms/{classroom_id}/observed-devices/cleanup-stale")
async def admin_cleanup_stale_observed_devices(
    classroom_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_DEVICES_MANAGE)

    try:
        classroom, devices, observed_devices = await get_classroom_layout_and_observed_devices(
            classroom_id
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Classroom not found") from exc
        raise HTTPException(status_code=502, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    pinned_macs = get_pinned_macs(devices)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    ids_to_delete: list[int] = []

    for observed_device in observed_devices:
        observed_device_id = observed_device.get("id")
        if not isinstance(observed_device_id, int):
            continue

        mac_address = observed_device.get("mac_address")
        if not isinstance(mac_address, str) or mac_address.upper() in pinned_macs:
            continue

        if not ip_in_subnet(observed_device.get("active_ip"), classroom["subnet_cidr"]):
            continue

        last_seen_at = parse_datetime(observed_device.get("last_seen_at"))
        if last_seen_at is None:
            continue

        if last_seen_at < cutoff:
            ids_to_delete.append(observed_device_id)

    if not ids_to_delete:
        return {
            "deleted_ids": [],
            "deleted_count": 0,
        }

    try:
        return await inventory_client.post_json(
            f"/internal/routers/{get_classroom_router_id(classroom)}/observed-devices/delete",
            json={"ids": ids_to_delete},
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Inventory service unavailable: {exc}",
        ) from exc


@app.post("/api/classrooms/{classroom_id}/wan/block-all")
async def block_classroom_wan(
    classroom_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    await ensure_wan_classroom_access(principal, classroom_id)

    try:
        return await classroom_client.post_json(
            f"/internal/classrooms/{classroom_id}/wan/block-all"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


@app.post("/api/classrooms/{classroom_id}/wan/allow-all")
async def allow_classroom_wan(
    classroom_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    await ensure_wan_classroom_access(principal, classroom_id)

    try:
        return await classroom_client.post_json(
            f"/internal/classrooms/{classroom_id}/wan/allow-all"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


@app.post("/api/devices/{device_id}/wan/block")
async def block_device_wan(
    device_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    await ensure_wan_device_access(principal, device_id)

    try:
        return await classroom_client.post_json(
            f"/internal/devices/{device_id}/wan/block"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


@app.post("/api/devices/{device_id}/wan/allow")
async def allow_device_wan(
    device_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    await ensure_wan_device_access(principal, device_id)

    try:
        return await classroom_client.post_json(
            f"/internal/devices/{device_id}/wan/allow"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc




async def proxy_inventory_admin_request(
    call,
    *,
    unavailable_detail: str = "Inventory service unavailable",
) -> Any:
    try:
        return await call()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{unavailable_detail}: {exc}",
        ) from exc


def get_required_router_string(router: dict[str, Any], field_name: str) -> str:
    value = router.get(field_name)

    if not isinstance(value, str) or value.strip() == "":
        raise HTTPException(
            status_code=502,
            detail=f"Inventory service response does not contain {field_name}",
        )

    return value.strip()


def get_required_router_int(router: dict[str, Any], field_name: str) -> int:
    value = router.get(field_name)

    if not isinstance(value, int):
        raise HTTPException(
            status_code=502,
            detail=f"Inventory service response does not contain {field_name}",
        )

    return value


def get_router_bool(router: dict[str, Any], field_name: str, default: bool = False) -> bool:
    value = router.get(field_name, default)

    if isinstance(value, bool):
        return value

    return default


def get_router_rest_base_url(router: dict[str, Any]) -> str:
    scheme = "https" if router.get("api_use_ssl") is True else "http"
    host = get_required_router_string(router, "api_host")
    port = get_required_router_int(router, "api_port")
    return f"{scheme}://{host}:{port}/rest"


def get_response_preview(response: httpx.Response, limit: int = 500) -> str | None:
    try:
        text = response.text.strip()
    except UnicodeDecodeError:
        return None

    if not text:
        return None

    if len(text) <= limit:
        return text

    return f"{text[:limit]}..."


def response_looks_like_html(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()

    if "text/html" in content_type:
        return True

    preview = get_response_preview(response, limit=80)
    if preview is None:
        return False

    lowered = preview.lower()
    return lowered.startswith("<!doctype html") or lowered.startswith("<html")


async def test_mikrotik_router_connection(router: dict[str, Any]) -> dict[str, Any]:
    router_id = router.get("id")
    base_url = get_router_rest_base_url(router)
    checked_url = f"{base_url}/system/resource"
    username = get_required_router_string(router, "api_username")
    password = get_required_router_string(router, "api_password")
    verify_tls = get_router_bool(router, "api_verify_tls")

    base_result: dict[str, Any] = {
        "ok": False,
        "router_id": router_id if isinstance(router_id, int) else None,
        "base_url": base_url,
        "checked_url": checked_url,
        "verify_tls": verify_tls,
        "status_code": None,
        "error": None,
        "redirect_location": None,
        "response_preview": None,
        "resource": None,
        "identity": None,
    }

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            verify=verify_tls,
            auth=(username, password),
            follow_redirects=False,
        ) as client:
            response = await client.get(checked_url)

            identity_response: httpx.Response | None = None
            if response.is_success:
                try:
                    identity_response = await client.get(f"{base_url}/system/identity")
                except httpx.HTTPError:
                    identity_response = None
    except httpx.TimeoutException as exc:
        return {
            **base_result,
            "error": f"MikroTik REST API timeout: {exc}",
        }
    except httpx.ConnectError as exc:
        return {
            **base_result,
            "error": f"Cannot connect to MikroTik REST API: {exc}",
        }
    except httpx.RequestError as exc:
        return {
            **base_result,
            "error": f"MikroTik REST API request failed: {exc}",
        }

    preview = get_response_preview(response)
    redirect_location = response.headers.get("location")

    if response.is_redirect:
        return {
            **base_result,
            "status_code": response.status_code,
            "redirect_location": redirect_location,
            "response_preview": preview,
            "error": (
                "MikroTik REST API returned redirect. "
                "Usually this means that the configured host/port points to a web UI "
                "or to a non-REST endpoint instead of RouterOS REST API."
            ),
        }

    if response.status_code in {401, 403}:
        return {
            **base_result,
            "status_code": response.status_code,
            "response_preview": preview,
            "error": "MikroTik REST API authentication failed. Check username and password.",
        }

    if response_looks_like_html(response):
        return {
            **base_result,
            "status_code": response.status_code,
            "response_preview": preview,
            "error": (
                "The endpoint returned HTML, not RouterOS REST JSON. "
                "Check that REST API is enabled and host/port are correct."
            ),
        }

    if not response.is_success:
        return {
            **base_result,
            "status_code": response.status_code,
            "response_preview": preview,
            "error": f"MikroTik REST API returned HTTP {response.status_code}.",
        }

    try:
        resource = response.json()
    except ValueError:
        return {
            **base_result,
            "status_code": response.status_code,
            "response_preview": preview,
            "error": "MikroTik REST API returned non-JSON response.",
        }

    if not isinstance(resource, dict):
        return {
            **base_result,
            "status_code": response.status_code,
            "response_preview": preview,
            "error": "MikroTik REST API resource response is not an object.",
        }

    identity: dict[str, Any] | None = None
    if identity_response is not None and identity_response.is_success:
        try:
            identity_raw = identity_response.json()
            if isinstance(identity_raw, dict):
                identity = identity_raw
        except ValueError:
            identity = None

    return {
        **base_result,
        "ok": True,
        "status_code": response.status_code,
        "resource": resource,
        "identity": identity,
    }


@app.get("/api/admin/routers")
async def admin_get_routers(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    return await proxy_inventory_admin_request(
        lambda: inventory_client.get_json("/internal/routers")
    )


@app.post("/api/admin/routers")
async def admin_create_router(
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    return await proxy_inventory_admin_request(
        lambda: inventory_client.post_json(
            "/internal/routers",
            json=payload,
        )
    )


@app.patch("/api/admin/routers/{router_id}")
async def admin_update_router(
    router_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    return await proxy_inventory_admin_request(
        lambda: inventory_client.patch_json(
            f"/internal/routers/{router_id}",
            json=payload,
        )
    )


@app.post("/api/admin/routers/{router_id}/test-connection")
async def admin_test_router_connection(
    router_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    try:
        router = await inventory_client.get_json(
            f"/internal/routers/{router_id}/connection"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Inventory service unavailable: {exc}",
        ) from exc

    if not isinstance(router, dict):
        raise HTTPException(status_code=502, detail="Invalid inventory service response")

    return await test_mikrotik_router_connection(router)


@app.post("/api/admin/routers/{router_id}/poll-now")
async def admin_poll_router_now(
    router_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    try:
        return await poller_client.post_json(
            f"/internal/routers/{router_id}/poll-now"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Poller service unavailable: {exc}",
        ) from exc


@app.post("/api/admin/routers/{router_id}/sync-now")
async def admin_sync_router_now(
    router_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    try:
        return await policy_sync_client.post_json(
            f"/internal/routers/{router_id}/sync-now"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Policy sync service unavailable: {exc}",
        ) from exc


@app.get("/api/admin/routers/status")
async def admin_get_routers_status(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    return await proxy_inventory_admin_request(
        lambda: inventory_client.get_json("/internal/routers/status")
    )


@app.get("/api/admin/routers/{router_id}/status")
async def admin_get_router_status(
    router_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    return await proxy_inventory_admin_request(
        lambda: inventory_client.get_json(f"/internal/routers/{router_id}/status")
    )


@app.post("/api/admin/classrooms")
async def admin_create_classroom(
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    try:
        return await classroom_client.post_json(
            "/internal/classrooms",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


@app.patch("/api/admin/classrooms/{classroom_id}")
async def admin_update_classroom(
    classroom_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    try:
        return await classroom_client.patch_json(
            f"/internal/classrooms/{classroom_id}",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc




@app.get("/api/admin/classrooms/{classroom_id}/cameras")
async def admin_get_classroom_cameras(
    classroom_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    try:
        cameras = await classroom_client.get_json(
            f"/internal/classrooms/{classroom_id}/cameras"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Classroom service unavailable: {exc}",
        ) from exc

    if not isinstance(cameras, list):
        raise HTTPException(status_code=502, detail="Invalid classroom service response")

    return cameras


@app.post("/api/admin/classrooms/{classroom_id}/cameras")
async def admin_create_classroom_camera(
    classroom_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    try:
        return await classroom_client.post_json(
            f"/internal/classrooms/{classroom_id}/cameras",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Classroom service unavailable: {exc}",
        ) from exc


@app.patch("/api/admin/classrooms/{classroom_id}/cameras/{camera_id}")
async def admin_update_classroom_camera(
    classroom_id: int,
    camera_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    try:
        return await classroom_client.patch_json(
            f"/internal/classrooms/{classroom_id}/cameras/{camera_id}",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Classroom service unavailable: {exc}",
        ) from exc


@app.delete("/api/admin/classrooms/{classroom_id}/cameras/{camera_id}", status_code=204)
async def admin_delete_classroom_camera(
    classroom_id: int,
    camera_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_CLASSROOMS_MANAGE)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{settings.classroom_service_url}/internal/classrooms/{classroom_id}/cameras/{camera_id}"
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Classroom service unavailable: {exc}",
        ) from exc

    return Response(status_code=204)


@app.post("/api/admin/devices")
async def admin_create_device(
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_DEVICES_MANAGE)

    if payload.get("is_pinned") is True:
        raise HTTPException(
            status_code=409,
            detail=(
                "Pinned devices must be created through "
                "/api/admin/classrooms/{classroom_id}/devices/pin-observed "
                "so MikroTik static DHCP lease can be verified."
            ),
        )

    try:
        return await classroom_client.post_json(
            "/internal/devices",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


@app.patch("/api/admin/devices/{device_id}")
async def admin_update_device(
    device_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_DEVICES_MANAGE)

    allowed_payload = {
        key: value
        for key, value in payload.items()
        if key in {"inventory_name", "row_index", "column_index", "wan_protected"}
    }

    try:
        return await classroom_client.patch_json(
            f"/internal/devices/{device_id}",
            json=allowed_payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


@app.post("/api/admin/devices/{device_id}/pin")
async def admin_pin_device(
    device_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_DEVICES_MANAGE)

    try:
        return await classroom_client.post_json(
            f"/internal/devices/{device_id}/pin",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


@app.post("/api/admin/devices/{device_id}/unpin")
async def admin_unpin_device(
    device_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_DEVICES_MANAGE)

    try:
        return await classroom_client.post_json(
            f"/internal/devices/{device_id}/unpin",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


@app.post("/api/admin/classrooms/{classroom_id}/devices/pin-observed")
async def admin_pin_observed_device(
    classroom_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_permission(principal, PERMISSION_DEVICES_MANAGE)

    raw_mac_address = payload.get("mac_address")
    if not isinstance(raw_mac_address, str) or not raw_mac_address.strip():
        raise HTTPException(status_code=422, detail="mac_address is required")

    row_index = payload.get("row_index")
    if row_index is not None and not isinstance(row_index, int):
        raise HTTPException(status_code=422,
                            detail="row_index must be an integer or null")

    column_index = payload.get("column_index")
    if column_index is not None and not isinstance(column_index, int):
        raise HTTPException(status_code=422,
                            detail="column_index must be an integer or null")

    wan_protected = payload.get("wan_protected", True)
    if not isinstance(wan_protected, bool):
        raise HTTPException(status_code=422, detail="wan_protected must be a boolean")

    raw_inventory_name = payload.get("inventory_name")
    if raw_inventory_name is not None and not isinstance(raw_inventory_name, str):
        raise HTTPException(status_code=422, detail="inventory_name must be a string")

    inventory_name_from_request = (
        raw_inventory_name.strip()
        if isinstance(raw_inventory_name, str) and raw_inventory_name.strip()
        else None
    )

    mac_address = normalize_mac_address(raw_mac_address)

    try:
        layout = await classroom_client.get_json(
            f"/internal/classrooms/{classroom_id}/layout"
        )
        classroom = layout["classroom"]
        router_id = get_classroom_router_id(classroom)
        observed = await inventory_client.get_json(
            f"/internal/routers/{router_id}/observed-devices"
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Classroom not found") from exc

        raise HTTPException(status_code=502, detail=exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    classroom = layout["classroom"]
    observed_devices = observed["devices"]

    observed_device = None

    for item in observed_devices:
        if normalize_mac_address(item["mac_address"]) == mac_address:
            observed_device = item
            break

    if observed_device is None:
        raise HTTPException(
            status_code=404,
            detail="Observed device with this MAC was not found in inventory",
        )

    ensure_observed_device_has_static_lease(observed_device)

    static_ip = observed_device["active_ip"]

    ensure_ip_belongs_to_classroom(
        ip=static_ip,
        subnet_cidr=classroom["subnet_cidr"],
        field_name="static_ip",
    )

    inventory_name = (
        inventory_name_from_request
        or observed_device.get("hostname")
        or f"Device {mac_address}"
    )

    hostname = observed_device.get("hostname")

    create_payload = {
        "classroom_id": classroom_id,
        "mac_address": mac_address,
        "inventory_name": inventory_name,
        "hostname": hostname,
        "static_ip": static_ip,
        "row_index": row_index,
        "column_index": column_index,
        "is_pinned": True,
        "wan_protected": wan_protected,
        "wan_allowed": True,
    }

    try:
        return await classroom_client.post_json(
            "/internal/devices",
            json=create_payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


@app.get("/api/admin/roles")
async def admin_list_roles(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_any_permission(
        principal,
        {
            PERMISSION_USERS_MANAGE_ADMIN,
            PERMISSION_USERS_MANAGE_LOWER,
            PERMISSION_WORKSTATIONS_MANAGE,
        },
    )

    try:
        return await auth_client.get_json("/internal/admin/roles")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc


@app.get("/api/admin/users")
async def admin_list_users(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_any_permission(
        principal,
        {PERMISSION_USERS_MANAGE_ADMIN, PERMISSION_USERS_MANAGE_LOWER},
    )

    try:
        users = await auth_client.get_json("/internal/admin/users")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc

    if not isinstance(users, list):
        raise HTTPException(status_code=502, detail="Invalid auth service response")

    return filter_manageable_users(principal, users)


@app.post("/api/admin/users")
async def admin_create_user(
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    role = payload.get("role")

    if not isinstance(role, str):
        raise HTTPException(status_code=422, detail="role is required")

    require_user_role_management(principal, role)

    try:
        return await auth_client.post_json(
            "/internal/admin/users",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)

    try:
        current_user = await auth_client.get_json(f"/internal/admin/users/{user_id}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc

    current_role = current_user.get("role") if isinstance(current_user, dict) else None
    if not isinstance(current_role, str):
        raise HTTPException(status_code=502, detail="Invalid auth service response")

    require_user_role_management(principal, current_role)

    new_role = payload.get("role")
    if new_role is not None:
        if not isinstance(new_role, str):
            raise HTTPException(status_code=422, detail="role must be a string")
        require_user_role_management(principal, new_role)

    try:
        return await auth_client.patch_json(
            f"/internal/admin/users/{user_id}",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc


@app.post("/api/admin/users/{user_id}/classrooms")
async def admin_update_user_classrooms(
    user_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)

    try:
        current_user = await auth_client.get_json(f"/internal/admin/users/{user_id}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc

    current_role = current_user.get("role") if isinstance(current_user, dict) else None
    if not isinstance(current_role, str):
        raise HTTPException(status_code=502, detail="Invalid auth service response")

    require_user_role_management(principal, current_role)

    try:
        return await auth_client.post_json(
            f"/internal/admin/users/{user_id}/classrooms",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc


@app.get("/api/admin/workstations")
async def admin_list_workstations(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_workstation_management(principal)

    try:
        return await auth_client.get_json("/internal/admin/workstations")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc


@app.post("/api/admin/workstations")
async def admin_create_workstation(
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_workstation_management(principal)
    ensure_workstation_payload_role(payload)

    try:
        return await auth_client.post_json(
            "/internal/admin/workstations",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc


@app.patch("/api/admin/workstations/{workstation_id}")
async def admin_update_workstation(
    workstation_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_workstation_management(principal)
    ensure_workstation_payload_role(payload)

    try:
        return await auth_client.patch_json(
            f"/internal/admin/workstations/{workstation_id}",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc


@app.post("/api/admin/workstations/{workstation_id}/classrooms")
async def admin_update_workstation_classrooms(
    workstation_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_workstation_management(principal)

    try:
        return await auth_client.post_json(
            f"/internal/admin/workstations/{workstation_id}/classrooms",
            json=payload,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Auth service unavailable: {exc}",
        ) from exc


async def create_camera_session_response(
    classroom_id: int,
    camera: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    camera_id = camera.get("id")

    if not isinstance(camera_id, int):
        raise HTTPException(status_code=502, detail="Invalid classroom service response")

    quality = get_requested_camera_quality(payload, camera)
    source = await get_camera_source(classroom_id, camera_id, quality)
    rtsp_url = source["rtsp_url"]

    try:
        data = await camera_client.post_json(
            "/internal/camera/sessions",
            json={
                "camera_id": camera_id,
                "rtsp_url": rtsp_url,
                "quality": quality,
            },
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Camera service unavailable: {exc}",
        ) from exc

    if not isinstance(data, dict) or not isinstance(data.get("session_id"), str):
        raise HTTPException(status_code=502, detail="Invalid camera service response")

    session_id = data["session_id"]

    return {
        "mode": data.get("mode", "hls"),
        "quality": data.get("quality", quality),
        "camera_id": camera_id,
        "session_id": session_id,
        "url": f"/api/camera/sessions/{session_id}/hls/index.m3u8",
        "expires_in_seconds": data.get("expires_in_seconds"),
    }



@app.post("/api/classrooms/{classroom_id}/cameras/{camera_id}/session")
async def create_named_classroom_camera_session(
    classroom_id: int,
    camera_id: int,
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    await ensure_classroom_access(principal, classroom_id)
    camera = await get_camera_or_404(classroom_id, camera_id)
    return await create_camera_session_response(classroom_id, camera, payload)


@app.delete("/api/camera/sessions/{session_id}", status_code=204)
async def stop_camera_session(
    session_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    await get_current_principal(request, authorization)

    try:
        await camera_client.post_json(f"/internal/camera/sessions/{session_id}/stop")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=exc.response.text,
            ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Camera service unavailable: {exc}",
        ) from exc

    return Response(status_code=204)


@app.get("/api/camera/sessions/{session_id}/hls/{filename}")
async def get_camera_hls_file(session_id: str, filename: str) -> StreamingResponse:
    return await stream_camera_service_response(
        f"/internal/camera/sessions/{session_id}/hls/{filename}"
    )


@app.get("/api/admin/maintenance/containers")
async def admin_get_maintenance_containers(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_maintenance_access(principal)

    try:
        return await maintenance_client.get_json("/internal/maintenance/containers")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Maintenance service unavailable: {exc}",
        ) from exc


@app.get("/api/admin/maintenance/containers/{container_id}/logs")
async def admin_get_maintenance_container_logs(
    container_id: str,
    request: Request,
    tail: int = 100,
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_maintenance_access(principal)

    if tail not in {100, 1000, 10000}:
        raise HTTPException(status_code=422, detail="tail must be one of: 100, 1000, 10000")

    try:
        return await maintenance_client.get_json(
            f"/internal/maintenance/containers/{container_id}/logs?tail={tail}"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Maintenance service unavailable: {exc}",
        ) from exc


@app.get("/api/admin/maintenance/backups/database")
async def admin_download_database_backup(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    principal = await get_current_principal(request, authorization)
    require_maintenance_access(principal)

    try:
        content, content_type, content_disposition = await maintenance_client.get_bytes(
            "/internal/maintenance/backups/database"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Maintenance service unavailable: {exc}",
        ) from exc

    headers: dict[str, str] = {}
    if content_disposition:
        headers["Content-Disposition"] = content_disposition

    return Response(
        content=content,
        media_type=content_type or "application/octet-stream",
        headers=headers,
    )


@app.post("/api/admin/maintenance/backups/database")
async def admin_upload_database_backup(
    request: Request,
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> Any:
    principal = await get_current_principal(request, authorization)
    require_maintenance_access(principal)

    filename = file.filename or "backup.backup"
    content = await file.read()

    if not content:
        raise HTTPException(status_code=422, detail="Backup file is empty")

    try:
        return await maintenance_client.post_file(
            path="/internal/maintenance/backups/database",
            field_name="file",
            filename=filename,
            content=content,
            content_type=file.content_type or "application/octet-stream",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Maintenance service unavailable: {exc}",
        ) from exc


def get_default_build_info() -> dict[str, Any]:
    return {
        "git_commit_count": 0,
        "compose_build_number": 0,
        "version": "v 0.0",
        "built_at": None,
    }


@app.get("/api/build-info")
async def build_info() -> dict[str, Any]:
    path = Path("/app/.build-info.json")

    if not path.is_file():
        return get_default_build_info()

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return get_default_build_info()

    if not isinstance(data, dict):
        return get_default_build_info()

    return data


def run() -> None:
    uvicorn.run(
        "cmnc_api_gateway.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    run()
