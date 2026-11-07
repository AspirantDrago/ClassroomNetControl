import asyncio
import hashlib
import ipaddress
import os
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from cmnc_veyon_service.key_store import KeyStore


AUTH_KEYS = "0c69b301-81b4-42d6-8fae-128cdd113314"
FEATURES = {"power-down": "6f5a27a0-0e2f-496e-afcc-7aae62eede10", "reboot": "4f7d98f0-395a-4fff-b968-e49b8d0f748c"}
WEBAPI = os.environ.get("CMNC_VEYON_WEBAPI_URL", "http://cmnc-veyon-proxy:11080").rstrip("/")
TARGET_PORT = int(os.environ.get("CMNC_VEYON_TARGET_PORT", "11100"))


class KeyInput(BaseModel):
    key_name: str = Field(default="CMNC", min_length=1, max_length=128, pattern=r"^[\w.-]+$")
    private_key: str = Field(min_length=1, max_length=65536, repr=False)


class Target(BaseModel):
    device_id: int = Field(gt=0)
    router_id: int = Field(gt=0)
    classroom_id: int = Field(gt=0)
    host: str
    width: int = Field(default=1280, ge=160, le=1920)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value):
        address = ipaddress.ip_address(value)
        if address.version != 4 or address.is_unspecified or address.is_multicast or address.is_loopback:
            raise ValueError("Недопустимый адрес устройства")
        return str(address)


class PowerInput(Target):
    action: Literal["power-down", "reboot"]


@dataclass
class Connection:
    uid: str
    host: str
    last_used: float
    created: float


class VeyonBridge:
    def __init__(self, store: KeyStore, client: httpx.AsyncClient):
        self.store = store
        self.client = client
        self.sessions: dict[str, Connection] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.capacity = asyncio.Semaphore(8)

    def identity(self, target: Target):
        name, pem = self.store.resolve(target.router_id, target.classroom_id)
        fingerprint = hashlib.sha256((name + pem).encode()).hexdigest()
        return f"{target.host}:{fingerprint}", name, pem

    async def checked(self, method, path, **kwargs):
        try:
            response = await self.client.request(method, WEBAPI + path, **kwargs)
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Veyon недоступен: проверьте службу на устройстве и сетевое подключение") from exc
        if not response.is_success:
            message = "Ошибка подключения Veyon"
            try:
                error = response.json().get("error", {})
                if error.get("code") in (4, 5, 6):
                    message = "Veyon отклонил ключ: проверьте имя, приватный ключ и соответствующий публичный ключ на устройстве"
                elif error.get("code") == 10:
                    message = "Veyon ещё не подготовил изображение экрана"
                elif isinstance(error.get("message"), str):
                    message = "Veyon: " + error["message"][:200]
            except (ValueError, AttributeError):
                pass
            raise HTTPException(503 if response.status_code in (408, 429, 503) else 502, message)
        return response

    async def connection(self, identity, name, pem, target):
        session = self.sessions.get(identity)
        if session and time.monotonic() - session.created < 2 * 3600:
            session.last_used = time.monotonic()
            return session
        if session:
            await self.close(identity)
        if len(self.sessions) >= 128:
            raise HTTPException(503, "Достигнут лимит подключений Veyon")
        host = target.host if TARGET_PORT == 11100 else f"{target.host}:{TARGET_PORT}"
        response = await self.checked("POST", f"/api/v1/authentication/{host}", json={"method": AUTH_KEYS, "credentials": {"keyname": name, "keydata": pem}})
        uid = response.json().get("connection-uid")
        if not isinstance(uid, str) or not uid:
            raise HTTPException(502, "Veyon вернул некорректный идентификатор подключения")
        session = Connection(uid, host, time.monotonic(), time.monotonic())
        self.sessions[identity] = session
        return session

    async def operate(self, target: Target, action: str | None = None):
        identity, name, pem = self.identity(target)
        lock = self.locks.setdefault(identity, asyncio.Lock())
        async with self.capacity, lock:
            session = await self.connection(identity, name, pem, target)
            try:
                headers = {"Connection-Uid": session.uid}
                if action:
                    await self.checked("PUT", "/api/v1/feature/" + FEATURES[action], headers=headers, json={"active": True, "arguments": {}})
                    return {"accepted": True, "device_id": target.device_id}
                response = await self.checked("GET", "/api/v1/framebuffer", headers=headers, params={"format": "jpeg", "quality": 75, "width": target.width})
                if not response.headers.get("content-type", "").lower().startswith("image/"):
                    raise HTTPException(502, "Veyon не вернул изображение экрана")
                return response.content, response.headers["content-type"]
            except HTTPException:
                # Reconnect on the next explicit request, without repeating a power command.
                await self.close(identity)
                raise
            finally:
                session.last_used = time.monotonic()

    async def close(self, identity):
        session = self.sessions.pop(identity, None)
        if session:
            with suppress(httpx.HTTPError):
                await self.client.delete(WEBAPI + f"/api/v1/authentication/{session.host}", headers={"Connection-Uid": session.uid}, timeout=2)

    async def cleanup(self):
        while True:
            await asyncio.sleep(10)
            for identity, session in list(self.sessions.items()):
                lock = self.locks.get(identity)
                if time.monotonic() - session.last_used > 40 and lock and not lock.locked():
                    async with lock:
                        await self.close(identity)



@asynccontextmanager
async def lifespan(application):
    application.state.store = KeyStore(Path(os.environ.get("CMNC_VEYON_DATA_DIR", "/data")))
    async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
        bridge = VeyonBridge(application.state.store, client)
        application.state.bridge = bridge
        cleaner = asyncio.create_task(bridge.cleanup())
        try:
            yield
        finally:
            cleaner.cancel()
            with suppress(asyncio.CancelledError):
                await cleaner
            for identity in list(bridge.sessions):
                await bridge.close(identity)



app = FastAPI(title="cmnc-veyon-service", lifespan=lifespan)


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            await client.get(WEBAPI + "/api/v1/feature")
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Veyon WebAPI запускается") from exc
    return {"service": "cmnc-veyon-service", "status": "ok"}


@app.get("/internal/keys/{scope}/{scope_id}")
async def key_info(scope: Literal["router", "classroom"], scope_id: int):
    return app.state.store.metadata(scope, scope_id)


@app.put("/internal/keys/{scope}/{scope_id}")
async def save_key(scope: Literal["router", "classroom"], scope_id: int, payload: KeyInput):
    app.state.store.save(scope, scope_id, payload.key_name, payload.private_key)
    return app.state.store.metadata(scope, scope_id)


@app.delete("/internal/keys/{scope}/{scope_id}")
async def delete_key(scope: Literal["router", "classroom"], scope_id: int):
    app.state.store.delete(scope, scope_id)
    return {"configured": False, "key_name": "CMNC"}


@app.post("/internal/device/frame")
async def device_frame(payload: Target):
    content, media_type = await app.state.bridge.operate(payload)
    return Response(content, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.post("/internal/device/power")
async def device_power(payload: PowerInput):
    return await app.state.bridge.operate(payload, payload.action)
