from fastapi import Header, HTTPException, Request, Response
from pydantic import BaseModel, SecretStr
from fastapi.responses import JSONResponse
from typing import Literal
from cmnc_api_gateway import main as gateway
from cmnc_api_gateway.veyon_routes import authorized_layout, authorized_target, bulk_veyon_devices, device_target, service_call


class OutputCommand(BaseModel):
    command: SecretStr
    confirmed: Literal[True]


async def administrator(request, authorization):
    principal = await gateway.get_current_principal(request, authorization)
    if principal.role not in {"admin", "superadmin"}:
        raise HTTPException(403, "Команды с выводом доступны только администраторам")
    return principal


def owner(principal):
    return f"{principal.principal_type}:{principal.id}"


def token_from_header(authorization):
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not 20 <= len(token) <= 128:
        raise HTTPException(403, "Требуется токен результата")
    return token


async def start_job(layout, devices, principal, command, skipped_count=0):
    if not command.strip() or len(command) > 16000:
        raise HTTPException(422, "Введите команду длиной не более 16000 символов")
    router_id = gateway.get_classroom_router_id(layout["classroom"])
    router = await gateway.get_router_connection_from_inventory(router_id)
    callback_url = router.get("veyon_callback_url")
    if not callback_url:
        raise HTTPException(409, "В настройках MikroTik укажите адрес обратного подключения CMNC (Loopback)")
    targets = [{**device_target(layout, device), "name": device.get("inventory_name") or device.get("hostname") or device.get("mac_address") or str(device["id"])} for device in devices]
    response = await service_call("POST", "/internal/command-jobs", {"owner": owner(principal),
        "classroom_id": layout["classroom"]["id"], "router_id": router_id, "command": command,
        "callback_url": callback_url, "targets": targets, "skipped_count": skipped_count})
    job = response.json()
    job.pop("owner", None)
    return JSONResponse(job, headers={"Cache-Control": "no-store"})


def register_command_routes(app):
    @app.post("/api/devices/{device_id}/veyon/command-with-output")
    async def device_command(device_id: int, payload: OutputCommand, request: Request,
                             authorization: str | None = Header(default=None)):
        principal = await administrator(request, authorization)
        target = await authorized_target(device_id, request, authorization, principal)
        layout = await authorized_layout(target["classroom_id"], request, authorization, principal)
        device = next(d for d in layout["devices"] if d["id"] == device_id)
        return await start_job(layout, [device], principal, payload.command.get_secret_value())

    @app.post("/api/classrooms/{classroom_id}/veyon/command-with-output")
    async def classroom_command(classroom_id: int, payload: OutputCommand, request: Request,
                                authorization: str | None = Header(default=None)):
        principal = await administrator(request, authorization)
        layout = await authorized_layout(classroom_id, request, authorization, principal)
        devices = bulk_veyon_devices(layout)
        return await start_job(layout, devices, principal, payload.command.get_secret_value(), len(layout["devices"]) - len(devices))

    @app.get("/api/veyon/command-jobs/{job_id}")
    async def command_results(job_id: str, request: Request, authorization: str | None = Header(default=None)):
        principal = await administrator(request, authorization)
        response = await service_call("GET", f"/internal/command-jobs/{job_id}")
        job = response.json()
        if job.get("owner") != owner(principal):
            raise HTTPException(403, "Результат принадлежит другой учётной записи")
        await gateway.ensure_classroom_access(principal, job["classroom_id"])
        job.pop("owner", None)
        return JSONResponse(job, headers={"Cache-Control": "no-store"})

    @app.get("/api/veyon/command-scripts/{job_id}/{device_id}")
    async def command_script(job_id: str, device_id: int, authorization: str | None = Header(default=None)):
        response = await service_call("POST", "/internal/command-job-script", {"job_id": job_id,
            "device_id": device_id, "token": token_from_header(authorization)})
        return Response(response.json()["script"], media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})

    @app.post("/api/veyon/command-results/{job_id}/{device_id}")
    async def command_callback(job_id: str, device_id: int, request: Request,
                               authorization: str | None = Header(default=None)):
        token = token_from_header(authorization)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1048576:
                raise HTTPException(413, "Результат команды слишком большой")
        try:
            import json
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "Некорректный результат команды")
        response = await service_call("POST", "/internal/command-job-result",
            {**payload, "job_id": job_id, "device_id": device_id, "token": token})
        return response.json()
