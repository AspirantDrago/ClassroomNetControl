import ipaddress
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException

from cmnc_api_gateway.clients import ServiceClient
from cmnc_api_gateway.schemas import (
    AuthUserResponse,
    ClassroomDashboardResponse,
    DashboardDevice,
    DynamicDevice,
    HealthResponse,
    PinObservedDeviceRequest,
)
from cmnc_api_gateway.settings import settings

app = FastAPI(title=settings.service_name)

auth_client = ServiceClient(settings.auth_service_url)
classroom_client = ServiceClient(settings.classroom_service_url)
inventory_client = ServiceClient(settings.inventory_service_url)


async def get_current_user(
    authorization: str | None = None,
) -> AuthUserResponse:
    token = None

    if authorization:
        token = authorization.removeprefix("Bearer ").strip()

    try:
        data = await auth_client.post_json(
            "/internal/auth/validate-token",
            json={"token": token},
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Auth service unavailable: {exc}") from exc

    if not isinstance(data, dict) or not data.get("valid"):
        raise HTTPException(status_code=401, detail="Invalid token")

    return AuthUserResponse.model_validate(data["user"])


def ensure_classroom_access(
    user: AuthUserResponse,
    classroom_id: int,
) -> None:
    if user.role == "admin":
        return

    if classroom_id not in user.allowed_classroom_ids:
        raise HTTPException(status_code=403, detail="Classroom access denied")


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


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        service=settings.service_name,
        status="ok",
    )


@app.get("/api/me", response_model=AuthUserResponse)
async def me(
    authorization: str | None = Header(default=None),
) -> AuthUserResponse:
    return await get_current_user(authorization)


@app.get("/api/classrooms")
async def get_classrooms(
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)

    try:
        classrooms = await classroom_client.get_json("/internal/classrooms")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Classroom service unavailable: {exc}") from exc

    if user.role == "admin":
        return classrooms

    return [
        classroom
        for classroom in classrooms
        if classroom["id"] in user.allowed_classroom_ids
    ]


@app.get(
    "/api/classrooms/{classroom_id}/dashboard",
    response_model=ClassroomDashboardResponse,
)
async def get_classroom_dashboard(
    classroom_id: int,
    authorization: str | None = Header(default=None),
) -> ClassroomDashboardResponse:
    user = await get_current_user(authorization)
    ensure_classroom_access(user, classroom_id)

    try:
        layout = await classroom_client.get_json(
            f"/internal/classrooms/{classroom_id}/layout"
        )
        observed = await inventory_client.get_json(
            f"/internal/routers/{settings.default_router_id}/observed-devices"
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

    for item in observed_devices:
        mac = item["mac_address"].upper()

        if mac in pinned_macs:
            continue

        if not ip_in_subnet(item["active_ip"], classroom["subnet_cidr"]):
            continue

        dynamic_devices.append(DynamicDevice.model_validate(item))

    return ClassroomDashboardResponse(
        classroom=classroom,
        devices=dashboard_devices,
        dynamic_devices=dynamic_devices,
    )


@app.post("/api/devices/{device_id}/wan/block")
async def block_device_wan(
    device_id: int,
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)

    if user.role not in {"admin", "teacher"}:
        raise HTTPException(status_code=403, detail="WAN control is not allowed")

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
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)

    if user.role not in {"admin", "teacher"}:
        raise HTTPException(status_code=403, detail="WAN control is not allowed")

    try:
        return await classroom_client.post_json(
            f"/internal/devices/{device_id}/wan/allow"
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc


def require_admin(user: AuthUserResponse) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


@app.post("/api/admin/classrooms")
async def admin_create_classroom(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)
    require_admin(user)

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
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)
    require_admin(user)

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


@app.post("/api/admin/devices")
async def admin_create_device(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)
    require_admin(user)

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
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)
    require_admin(user)

    try:
        return await classroom_client.patch_json(
            f"/internal/devices/{device_id}",
            json=payload,
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
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)
    require_admin(user)

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
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)
    require_admin(user)

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
    payload: PinObservedDeviceRequest,
    authorization: str | None = Header(default=None),
) -> Any:
    user = await get_current_user(authorization)
    require_admin(user)

    mac_address = normalize_mac_address(payload.mac_address)

    try:
        layout = await classroom_client.get_json(
            f"/internal/classrooms/{classroom_id}/layout"
        )
        observed = await inventory_client.get_json(
            f"/internal/routers/{settings.default_router_id}/observed-devices"
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
        payload.inventory_name
        or observed_device.get("hostname")
        or f"Device {mac_address}"
    )

    hostname = payload.hostname

    if hostname is None:
        hostname = observed_device.get("hostname")

    create_payload = {
        "classroom_id": classroom_id,
        "mac_address": mac_address,
        "inventory_name": inventory_name,
        "hostname": hostname,
        "static_ip": static_ip,
        "row_index": payload.row_index,
        "column_index": payload.column_index,
        "is_pinned": True,
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
