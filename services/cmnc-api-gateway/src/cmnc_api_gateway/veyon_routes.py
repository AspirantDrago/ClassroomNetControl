import asyncio
import ipaddress
import time
from typing import Literal, Any

import httpx
from fastapi import Header, HTTPException, Request, Query
from pydantic import BaseModel, Field

from cmnc_api_gateway import main as gateway
from cmnc_contracts.veyon_actions import DeviceAction, ADMIN_ACTIONS


class KeyInput(BaseModel):
    key_name: str = Field(default="CMNC", min_length=1, max_length=128, pattern=r"^[\w.-]+$")
    private_key: str = Field(min_length=1, max_length=65536, repr=False)


class ControlInput(BaseModel):
    token: str | None = Field(default=None, max_length=128)
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=64)


class ClassroomDeviceAction(DeviceAction):
    confirmed: Literal[True]


class Confirmation(BaseModel):
    confirmed: Literal[True]


async def service_call(method, path, payload=None):
    try:
        client = getattr(gateway.app.state, "veyon_http", None)
        if client is not None:
            response = await client.request(method, gateway.settings.veyon_service_url.rstrip("/") + path, json=payload)
        else:
            async with httpx.AsyncClient(timeout=35, trust_env=False) as client:
                response = await client.request(method, gateway.settings.veyon_service_url.rstrip("/") + path, json=payload)
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Veyon: превышено время ожидания") from exc
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
        raise HTTPException(response.status_code if response.status_code in {409, 422, 503, 504} else 502, detail)
    return response


async def authorized_layout(classroom_id, request, authorization, principal=None):
    if principal is None:
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


async def dispatch_classroom_action(layout, operation: str, action_payload: DeviceAction | None = None):
    semaphore = asyncio.Semaphore(gateway.settings.veyon_bulk_concurrency)
    async def send(device):
        try:
            # Queueing and dispatch are bounded. Never retry remote actions.
            async with asyncio.timeout(45):
                async with semaphore:
                    target = device_target(layout, device)
                    path = "/internal/device/action" if action_payload is not None else "/internal/device/power"
                    payload = action_payload.wire() if action_payload is not None else {"action": operation}
                    await service_call("POST", path, {**target, **payload})
            return {"device_id": device["id"], "accepted": True, "error": None}
        except HTTPException as exc:
            return {"device_id": device["id"], "accepted": False, "error": str(exc.detail), **({"timed_out": True} if exc.status_code == 504 else {})}
        except TimeoutError:
            return {"device_id": device["id"], "accepted": False, "error": "Veyon: превышено время ожидания", "timed_out": True}
    targets = bulk_veyon_devices(layout)
    results = await asyncio.gather(*(send(device) for device in targets))
    timeout_count = sum(item.get("timed_out", False) for item in results)
    return {**({"timeout_count": timeout_count} if timeout_count else {}),
            "accepted_count": sum(item["accepted"] for item in results),
            "failed_count": sum(not item["accepted"] for item in results),
            "skipped_count": len(layout["devices"]) - len(targets), "results": results}


# Only configuration metadata is cached, never user permissions or private keys.
_CONFIGURATION_TTL = 3600
_configuration_cache: dict[tuple[int, int], tuple[float, bool]] = {}
_configuration_locks: dict[tuple[int, int], asyncio.Lock] = {}
_configuration_generation = 0


def invalidate_veyon_configuration():
    global _configuration_generation
    _configuration_generation += 1
    _configuration_cache.clear()


def cached_veyon_configuration(classroom):
    identity = (gateway.get_classroom_router_id(classroom), classroom["id"])
    cached = _configuration_cache.get(identity)
    return {"veyon_configured": cached[1] if cached else False,
            "veyon_configuration_stale": not cached or cached[0] <= time.monotonic()}


async def classroom_veyon_configured(classroom):
    router_id = gateway.get_classroom_router_id(classroom)
    classroom_id = classroom["id"]
    identity = (router_id, classroom_id)
    async with _configuration_locks.setdefault(identity, asyncio.Lock()):
        cached = _configuration_cache.get(identity)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        generation = _configuration_generation
        router_key = await service_call("GET", f"/internal/keys/router/{router_id}")
        configured = router_key.json().get("configured") is True
        if not configured:
            classroom_key = await service_call("GET", f"/internal/keys/classroom/{classroom_id}")
            configured = classroom_key.json().get("configured") is True
        # A key may have changed while metadata requests were in flight.
        if generation != _configuration_generation:
            return False
        now = time.monotonic()
        for key in [key for key, entry in _configuration_cache.items() if entry[0] <= now]:
            del _configuration_cache[key]
        _configuration_cache[identity] = (now + _CONFIGURATION_TTL, configured)
        return configured


def register_veyon_routes(app):
    @app.get("/api/classrooms/{classroom_id}/veyon/status")
    async def classroom_veyon_status(classroom_id: int, request: Request,
                                     authorization: str | None = Header(default=None)):
        layout = await authorized_layout(classroom_id, request, authorization)
        return {"configured": await classroom_veyon_configured(layout["classroom"])}

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
        invalidate_veyon_configuration()
        return response.json()

    @app.delete("/api/admin/veyon/keys/{scope}/{scope_id}")
    async def delete_key(scope: Literal["router", "classroom"], scope_id: int, request: Request,
                         authorization: str | None = Header(default=None)):
        await check_key_admin(scope, scope_id, request, authorization)
        response = await service_call("DELETE", f"/internal/keys/{scope}/{scope_id}")
        invalidate_veyon_configuration()
        return response.json()

    @app.post("/api/devices/{device_id}/veyon/action")
    async def device_action(device_id: int, payload: DeviceAction, request: Request,
                            authorization: str | None = Header(default=None)):
        principal = await gateway.get_current_principal(request, authorization)
        if payload.action in ADMIN_ACTIONS and principal.role not in {"admin", "superadmin"}:
            raise HTTPException(403, "Действие доступно только администраторам")
        target = await authorized_target(device_id, request, authorization, principal)
        return (await service_call("POST", "/internal/device/action", {**target, **payload.wire()})).json()

    @app.post("/api/devices/{device_id}/veyon/refresh")
    async def refresh_device_framebuffer(device_id: int, request: Request,
                                         authorization: str | None = Header(default=None)):
        target = await authorized_target(device_id, request, authorization)
        return (await service_call("POST", "/internal/device/refresh", target)).json()

    @app.get("/api/devices/{device_id}/veyon/frame")
    async def device_frame(device_id: int, request: Request, authorization: str | None = Header(default=None),
                           width: int = Query(default=1280, ge=160, le=1920),
                           quality: int = Query(default=75, ge=1, le=100)):
        target = await authorized_target(device_id, request, authorization)
        target["width"] = width
        target["quality"] = quality
        response = await service_call("POST", "/internal/device/frame", target)
        content_type = response.headers.get("content-type", "")
        if not content_type.lower().startswith("image/"):
            raise HTTPException(502, "Veyon не вернул изображение")
        return gateway.Response(response.content, media_type=content_type, headers={"Cache-Control": "no-store"})

    @app.get("/api/devices/{device_id}/veyon/snapshot")
    async def device_snapshot(device_id: int, request: Request, authorization: str | None = Header(default=None)):
        target = await authorized_target(device_id, request, authorization)
        response = await service_call("POST", "/internal/device/snapshot", target)
        if response.headers.get("content-type", "").split(";", 1)[0].lower() != "image/png":
            raise HTTPException(502, "Veyon не вернул снимок в формате PNG")
        return gateway.Response(response.content, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/devices/{device_id}/veyon/shortcut/{shortcut}")
    async def device_shortcut(device_id: int, shortcut: Literal["escape", "ctrl-alt-delete"], payload: ControlInput,
                              request: Request, authorization: str | None = Header(default=None)):
        principal = await gateway.get_current_principal(request, authorization)
        if shortcut == "ctrl-alt-delete" and principal.role not in {"admin", "superadmin"}:
            raise HTTPException(403, "Комбинация доступна только администраторам")
        target = await authorized_target(device_id, request, authorization, principal)
        keys = [0xff1b] if shortcut == "escape" else [0xffe3, 0xffe9, 0xffff]
        events = [{"type": "key", "key": key, "pressed": True} for key in keys]
        events += [{"type": "key", "key": key, "pressed": False} for key in reversed(keys)]
        return (await service_call("POST", "/internal/device/control/input", {
            **target, "owner": f"{principal.principal_type}:{principal.id}", "token": payload.token, "events": events})).json()

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

    @app.post("/api/classrooms/{classroom_id}/veyon/action")
    async def classroom_action(classroom_id: int, payload: ClassroomDeviceAction, request: Request,
                               authorization: str | None = Header(default=None)):
        principal = await gateway.get_current_principal(request, authorization)
        if payload.action in ADMIN_ACTIONS and principal.role not in {"admin", "superadmin"}:
            raise HTTPException(403, "Действие доступно только администраторам")
        layout = await authorized_layout(classroom_id, request, authorization, principal)
        return await dispatch_classroom_action(layout, payload.action, payload)

    @app.post("/api/classrooms/{classroom_id}/veyon/{action}")
    async def classroom_power(classroom_id: int,
                              action: Literal["power-down-all", "reboot-all", "install-updates-and-power-down-all"],
                              payload: Confirmation, request: Request,
                              authorization: str | None = Header(default=None)):
        principal = await gateway.get_current_principal(request, authorization)
        if action == "install-updates-and-power-down-all" and principal.role not in {"admin", "superadmin"}:
            raise HTTPException(403, "Установка обновлений с выключением доступна только администраторам")
        layout = await authorized_layout(classroom_id, request, authorization, principal)
        operation = action.removesuffix("-all")
        return await dispatch_classroom_action(layout, operation)
