import asyncio
import ipaddress
from typing import Literal, Any

import httpx
from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field

from cmnc_api_gateway import main as gateway


class KeyInput(BaseModel):
    key_name: str = Field(default="CMNC", min_length=1, max_length=128, pattern=r"^[\w.-]+$")
    private_key: str = Field(min_length=1, max_length=65536, repr=False)


class ControlInput(BaseModel):
    token: str | None = Field(default=None, max_length=128)
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=64)


class Confirmation(BaseModel):
    confirmed: Literal[True]


async def service_call(method, path, payload=None):
    try:
        async with httpx.AsyncClient(timeout=35, trust_env=False) as client:
            response = await client.request(method, gateway.settings.veyon_service_url.rstrip("/") + path, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Сервис Veyon недоступен") from exc
    if not response.is_success:
        detail = "Ошибка сервиса Veyon"
        try:
            value = response.json().get("detail")
            if isinstance(value, str):
                detail = value
        except (ValueError, AttributeError):
            pass
        raise HTTPException(response.status_code if response.status_code in {409, 422, 503} else 502, detail)
    return response


async def authorized_layout(classroom_id, request, authorization):
    principal = await gateway.get_current_principal(request, authorization)
    await gateway.ensure_classroom_access(principal, classroom_id)
    return await gateway.get_wol_classroom_layout(classroom_id)


def bulk_veyon_devices(layout):
    # Every classroom-wide Veyon action must use this server-owned selection.
    # Direct device actions deliberately do not apply this filter.
    return [device for device in layout["devices"] if not device.get("veyon_bulk_protected", False)]


def device_target(layout, device):
    classroom = layout["classroom"]
    host = device.get("static_ip")
    try:
        address = ipaddress.ip_address(host)
        subnet = ipaddress.ip_network(classroom["subnet_cidr"], strict=False)
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "Для Veyon устройству нужен IP-адрес в подсети аудитории") from exc
    if address not in subnet or address.is_loopback or address.is_multicast or address.is_unspecified:
        raise HTTPException(409, "IP-адрес устройства не принадлежит подсети аудитории")
    return {"device_id": device["id"], "classroom_id": classroom["id"],
            "router_id": gateway.get_classroom_router_id(classroom), "host": str(address)}


async def authorized_target(device_id, request, authorization, principal=None):
    # Resolve server-owned device IDs; never accept a host/IP or private key from viewers.
    if principal is None:
        principal = await gateway.get_current_principal(request, authorization)
    try:
        classroom_id = await gateway.get_device_classroom_id(device_id)
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Сервис аудиторий недоступен") from exc
    if classroom_id is None:
        raise HTTPException(404, "Устройство не найдено")
    await gateway.ensure_classroom_access(principal, classroom_id)
    layout = await gateway.get_wol_classroom_layout(classroom_id)
    device = next((item for item in layout["devices"] if item["id"] == device_id), None)
    if device is None:
        raise HTTPException(404, "Устройство не найдено в аудитории")
    return device_target(layout, device)


async def check_key_admin(scope, scope_id, request, authorization):
    principal = await gateway.get_current_principal(request, authorization)
    gateway.require_permission(principal, gateway.PERMISSION_CLASSROOMS_MANAGE)
    if scope == "classroom":
        return await gateway.get_classroom_or_404(scope_id)
    await gateway.get_router_connection_from_inventory(scope_id)
    return None


def register_veyon_routes(app):
    @app.get("/api/admin/veyon/keys/{scope}/{scope_id}")
    async def key_info(scope: Literal["router", "classroom"], scope_id: int, request: Request,
                       authorization: str | None = Header(default=None)):
        classroom = await check_key_admin(scope, scope_id, request, authorization)
        response = await service_call("GET", f"/internal/keys/{scope}/{scope_id}")
        metadata = response.json()
        if classroom:
            override = await service_call("GET", f"/internal/keys/router/{gateway.get_classroom_router_id(classroom)}")
            metadata["router_override"] = override.json()["configured"]
        return metadata

    @app.put("/api/admin/veyon/keys/{scope}/{scope_id}")
    async def save_key(scope: Literal["router", "classroom"], scope_id: int, payload: KeyInput,
                       request: Request, authorization: str | None = Header(default=None)):
        await check_key_admin(scope, scope_id, request, authorization)
        response = await service_call("PUT", f"/internal/keys/{scope}/{scope_id}", payload.model_dump())
        return response.json()

    @app.delete("/api/admin/veyon/keys/{scope}/{scope_id}")
    async def delete_key(scope: Literal["router", "classroom"], scope_id: int, request: Request,
                         authorization: str | None = Header(default=None)):
        await check_key_admin(scope, scope_id, request, authorization)
        return (await service_call("DELETE", f"/internal/keys/{scope}/{scope_id}")).json()

    @app.get("/api/devices/{device_id}/veyon/frame")
    async def device_frame(device_id: int, request: Request, authorization: str | None = Header(default=None)):
        target = await authorized_target(device_id, request, authorization)
        response = await service_call("POST", "/internal/device/frame", target)
        content_type = response.headers.get("content-type", "")
        if not content_type.lower().startswith("image/"):
            raise HTTPException(502, "Veyon не вернул изображение")
        return gateway.Response(response.content, media_type=content_type, headers={"Cache-Control": "no-store"})

    @app.post("/api/devices/{device_id}/veyon/control/{action}")
    async def device_control(device_id: int, action: Literal["start", "input", "stop"], payload: ControlInput,
                             request: Request, authorization: str | None = Header(default=None)):
        principal = await gateway.get_current_principal(request, authorization)
        target = await authorized_target(device_id, request, authorization, principal)
        owner = f"{principal.principal_type}:{principal.id}"
        return (await service_call("POST", f"/internal/device/control/{action}",
                {**target, **payload.model_dump(), "owner": owner})).json()

    @app.post("/api/devices/{device_id}/veyon/{action}")
    async def device_power(device_id: int, action: Literal["power-down", "reboot"], request: Request,
                           authorization: str | None = Header(default=None)):
        target = await authorized_target(device_id, request, authorization)
        return (await service_call("POST", "/internal/device/power", {**target, "action": action})).json()

    @app.post("/api/classrooms/{classroom_id}/veyon/power-down-all")
    async def classroom_power_down(classroom_id: int, payload: Confirmation, request: Request,
                                   authorization: str | None = Header(default=None)):
        layout = await authorized_layout(classroom_id, request, authorization)
        semaphore = asyncio.Semaphore(4)

        async def send(device):
            try:
                # Bound queueing + request time; no retries of power commands.
                async with asyncio.timeout(45):
                    async with semaphore:
                        target = device_target(layout, device)
                        await service_call("POST", "/internal/device/power", {**target, "action": "power-down"})
                return {"device_id": device["id"], "accepted": True, "error": None}
            except HTTPException as exc:
                return {"device_id": device["id"], "accepted": False, "error": str(exc.detail)}
            except TimeoutError:
                return {"device_id": device["id"], "accepted": False, "error": "Veyon: превышено время ожидания"}

        targets = bulk_veyon_devices(layout)
        results = await asyncio.gather(*(send(device) for device in targets))
        return {"accepted_count": sum(item["accepted"] for item in results),
                "failed_count": sum(not item["accepted"] for item in results),
                "skipped_count": len(layout["devices"]) - len(targets), "results": results}
