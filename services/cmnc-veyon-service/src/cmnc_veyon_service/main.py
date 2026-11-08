import asyncio
import hashlib
import ipaddress
import logging
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
from cmnc_veyon_service.control import RemoteControl, InputEvent


class HealthCheckAccessFilter(logging.Filter):
    """Omit GET /health probes from Uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        _, method, path, _, _ = args
        return not (
            method == "GET"
            and isinstance(path, str)
            and path.partition("?")[0] == "/health"
        )


logging.getLogger("uvicorn.access").addFilter(HealthCheckAccessFilter())

logger = logging.getLogger("uvicorn.error.veyon")


AUTH_KEYS = "0c69b301-81b4-42d6-8fae-128cdd113314"
FEATURES = {"power-down": "6f5a27a0-0e2f-496e-afcc-7aae62eede10", "reboot": "4f7d98f0-395a-4fff-b968-e49b8d0f748c", "install-updates-and-power-down": "09bcb3a1-fc11-4d03-8cf1-efd26be8655b"}
WEBAPI = os.environ.get("CMNC_VEYON_WEBAPI_URL", "http://cmnc-veyon-proxy:11080").rstrip("/")
TARGET_PORT = int(os.environ.get("CMNC_VEYON_TARGET_PORT", "11100"))
# Veyon waits up to 15 seconds for authentication methods on the target.
AUTHENTICATION_TIMEOUT_SECONDS = 20
FRAME_CACHE_SECONDS = 0.1
FRAMEBUFFER_ATTEMPTS = 12
FRAMEBUFFER_RETRY_DELAY = 0.35


class VeyonError(HTTPException):
    def __init__(self, status_code: int, detail: str, error_code: int | None = None):
        super().__init__(status_code, detail)
        self.error_code = error_code


class KeyInput(BaseModel):
    key_name: str = Field(default="CMNC", min_length=1, max_length=128, pattern=r"^[\w.-]+$")
    private_key: str = Field(min_length=1, max_length=65536, repr=False)


class Target(BaseModel):
    device_id: int = Field(gt=0)
    router_id: int = Field(gt=0)
    classroom_id: int = Field(gt=0)
    host: str
    width: int = Field(default=1280, ge=160, le=1920)
    quality: int = Field(default=75, ge=1, le=100)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value):
        address = ipaddress.ip_address(value)
        if address.version != 4 or address.is_unspecified or address.is_multicast or address.is_loopback:
            raise ValueError("Недопустимый адрес устройства")
        return str(address)


class PowerInput(Target):
    action: Literal["power-down", "reboot", "install-updates-and-power-down"]


@dataclass
class Connection:
    uid: str
    host: str
    last_used: float
    created: float
    last_frame_warning: float = 0
    frame: tuple[bytes, str] | None = None
    frame_width: int = 0
    frame_quality: int = 0
    frame_at: float = 0


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
            error_code = None
            try:
                error = response.json().get("error", {})
                error_code = error.get("code")
                if error.get("code") in (4, 5, 6):
                    message = "Veyon отклонил ключ: проверьте имя, приватный ключ и соответствующий публичный ключ на устройстве"
                elif error.get("code") == 10:
                    message = "Veyon ещё не подготовил изображение экрана"
                elif isinstance(error.get("message"), str):
                    message = "Veyon: " + error["message"][:200]
            except (ValueError, AttributeError):
                pass
            raise VeyonError(503 if response.status_code in (408, 429, 503) else 502, message, error_code)
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
        response = await self.checked("POST", f"/api/v1/authentication/{host}", timeout=AUTHENTICATION_TIMEOUT_SECONDS, json={"method": AUTH_KEYS, "credentials": {"keyname": name, "keydata": pem}})
        uid = response.json().get("connection-uid")
        if not isinstance(uid, str) or not uid:
            raise HTTPException(502, "Veyon вернул некорректный идентификатор подключения")
        session = Connection(uid, host, time.monotonic(), time.monotonic())
        self.sessions[identity] = session
        logger.info("Veyon authenticated device_id=%s host=%s", target.device_id, target.host)
        return session

    async def operate(self, target: Target, action: str | None = None, *, snapshot: bool = False):
        identity, name, pem = self.identity(target)
        lock = self.locks.setdefault(identity, asyncio.Lock())
        async with self.capacity, lock:
            session = await self.connection(identity, name, pem, target)
            try:
                headers = {"Connection-Uid": session.uid}
                if action:
                    await self.checked("PUT", "/api/v1/feature/" + FEATURES[action], headers=headers, json={"active": True, "arguments": {}})
                    return {"accepted": True, "device_id": target.device_id}
                # A short shared cache coalesces concurrent viewers on this
                # authenticated target without persisting screenshots to disk.
                if (not snapshot and session.frame is not None and session.frame_width == target.width
                        and session.frame_quality == target.quality
                        and time.monotonic() - session.frame_at < FRAME_CACHE_SECONDS):
                    return session.frame
                # PNG without width/height returns the native framebuffer without
                # JPEG loss or resizing. Never reuse the monitoring JPEG cache.
                params = {"format": "png", "compression": 5} if snapshot else {"format": "jpeg", "quality": target.quality, "width": target.width}
                # Authentication can finish before the first framebuffer arrives.
                # Keep this connection alive while waiting; never reauthenticate
                # just because the initial screen image is not ready yet.
                try:
                    async with asyncio.timeout(8):
                        for attempt in range(FRAMEBUFFER_ATTEMPTS):
                            try:
                                response = await self.checked("GET", "/api/v1/framebuffer", headers=headers, params=params)
                                break
                            except VeyonError as exc:
                                if exc.error_code != 10 or attempt == FRAMEBUFFER_ATTEMPTS - 1:
                                    raise
                                await asyncio.sleep(FRAMEBUFFER_RETRY_DELAY)
                except TimeoutError as exc:
                    raise VeyonError(503, "Veyon ещё не подготовил изображение экрана", 10) from exc
                if not response.headers.get("content-type", "").lower().startswith("image/"):
                    raise HTTPException(502, "Veyon не вернул изображение экрана")
                if snapshot:
                    if response.headers["content-type"].split(";", 1)[0].lower() != "image/png":
                        raise HTTPException(502, "Veyon не вернул снимок в формате PNG")
                    return response.content, response.headers["content-type"]
                session.frame = (response.content, response.headers["content-type"])
                session.frame_width = target.width
                session.frame_quality = target.quality
                session.frame_at = time.monotonic()
                return session.frame
            except HTTPException as exc:
                # A missing first frame is temporary, not an invalid connection.
                # Power commands are never retried automatically.
                if action is None and isinstance(exc, VeyonError) and exc.error_code == 10:
                    await self.log_missing_frame(target, session)
                else:
                    await self.close(identity)
                raise
            finally:
                session.last_used = time.monotonic()

    async def log_missing_frame(self, target: Target, session: Connection):
        now = time.monotonic()
        if session.last_frame_warning and now - session.last_frame_warning < 60:
            return
        session.last_frame_warning = now
        metadata = {}
        # Read only diagnostics. Never enable WebAPI debug logging: it can include
        # authentication request bodies containing private keys.
        for resource in ("session", "user"):
            try:
                response = await self.client.get(
                    WEBAPI + "/api/v1/" + resource,
                    headers={"Connection-Uid": session.uid}, timeout=2,
                )
                if response.is_success:
                    data = response.json()
                    if isinstance(data, dict):
                        if resource == "session":
                            metadata["session_id"] = data.get("sessionId")
                            metadata["session_uptime"] = data.get("sessionUptime")
                        else:
                            metadata["user_logged_in"] = bool(data.get("login"))
                else:
                    metadata[resource + "_http_status"] = response.status_code
            except (httpx.HTTPError, ValueError):
                metadata[resource + "_unavailable"] = True
        logger.warning(
            "Veyon framebuffer unavailable device_id=%s host=%s connection_age_seconds=%s diagnostics=%s",
            target.device_id, target.host, round(now - session.created), metadata,
        )

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
        application.state.control = RemoteControl(bridge)
        control_cleaner = asyncio.create_task(application.state.control.cleanup())
        try:
            yield
        finally:
            control_cleaner.cancel()
            with suppress(asyncio.CancelledError):
                await control_cleaner
            for identity, lease in list(application.state.control.leases.items()):
                with suppress(HTTPException):
                    await application.state.control.release(identity, lease)
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


@app.post("/internal/device/snapshot")
async def device_snapshot(payload: Target):
    content, media_type = await app.state.bridge.operate(payload, snapshot=True)
    return Response(content, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.post("/internal/device/power")
async def device_power(payload: PowerInput):
    return await app.state.bridge.operate(payload, payload.action)


class ControlInput(Target):
    owner: str = Field(min_length=1, max_length=128)
    token: str | None = Field(default=None, max_length=128)
    events: list[InputEvent] = Field(default_factory=list, max_length=64)


@app.post("/internal/device/control/{action}")
async def device_control(action: Literal["start", "input", "stop"], payload: ControlInput):
    return await app.state.control.operate(payload, payload.owner, action, payload.token, payload.events)
