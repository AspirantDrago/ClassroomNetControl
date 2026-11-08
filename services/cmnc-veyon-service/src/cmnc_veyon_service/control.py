import asyncio
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field


class KeyEvent(BaseModel):
    type: Literal['key']
    key: int = Field(ge=1, le=0x1fffffff, strict=True)
    pressed: bool = Field(strict=True)


class PointerEvent(BaseModel):
    type: Literal['pointer']
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    buttons: int = Field(ge=0, le=127, strict=True)


InputEvent = Annotated[KeyEvent | PointerEvent, Field(discriminator='type')]


@dataclass
class Lease:
    token: str
    owner: str
    uid: str
    touched: float
    keys: set[int] = field(default_factory=set)
    x: float = 0
    y: float = 0
    buttons: int = 0


class RemoteControl:
    def __init__(self, bridge):
        self.bridge = bridge
        self.leases: dict[str, Lease] = {}
        self.host_locks: dict[str, asyncio.Lock] = {}

    async def release(self, identity, lease):
        events = [{'type': 'key', 'key': key, 'pressed': False} for key in lease.keys]
        events.append({'type': 'pointer', 'x': lease.x, 'y': lease.y, 'buttons': 0})
        try:
            for offset in range(0, len(events), 64):
                await self.bridge.checked('POST', '/api/v1/input', headers={'Connection-Uid': lease.uid}, json={'events': events[offset:offset+64]})
        finally:
            self.leases.pop(identity, None)

    async def operate(self, target, owner, action, token=None, events=()):
        identity, name, pem = self.bridge.identity(target)
        async with self.host_locks.setdefault(target.host, asyncio.Lock()), self.bridge.locks.setdefault(identity, asyncio.Lock()):
            lease = self.leases.get(target.host)
            if lease and time.monotonic() - lease.touched > 8:
                with suppress(HTTPException):
                    await self.release(target.host, lease)
                lease = None
            if action == 'start':
                if lease:
                    raise HTTPException(409, 'Устройством уже управляют из другого окна')
                session = await self.bridge.connection(identity, name, pem, target)
                try:
                    await self.bridge.checked('POST', '/api/v1/input', headers={'Connection-Uid': session.uid}, json={'events': []})
                except HTTPException as exc:
                    if exc.status_code == 502:
                        raise HTTPException(503, 'Передача ввода недоступна: обновите контейнер Veyon proxy') from exc
                    raise
                lease = Lease(secrets.token_urlsafe(32), owner, session.uid, time.monotonic())
                self.leases[target.host] = lease
                return {'token': lease.token}
            if not lease or lease.owner != owner or not secrets.compare_digest(lease.token, token or ''):
                raise HTTPException(409, 'Управление завершено. Нажмите на экран, чтобы подключиться снова')
            if action == 'stop':
                with suppress(HTTPException):
                    await self.release(target.host, lease)
                return {'accepted': True}
            session = self.bridge.sessions.get(identity)
            if not session or session.uid != lease.uid:
                with suppress(HTTPException):
                    await self.release(target.host, lease)
                raise HTTPException(409, 'Соединение Veyon изменилось. Подключитесь снова')
            if events:
                if len(lease.keys | {event.key for event in events if isinstance(event, KeyEvent) and event.pressed}) > 64:
                    raise HTTPException(422, 'Слишком много одновременно нажатых клавиш')
                # On a timeout the remote side may already have applied a press.
                # Track every possibly pressed key before sending, then release
                # them if delivery fails. Never retry input batches.
                lease.keys.update(event.key for event in events if isinstance(event, KeyEvent) and event.pressed)
                for event in events:
                    if isinstance(event, PointerEvent):
                        lease.x, lease.y = event.x, event.y
                try:
                    await self.bridge.checked('POST', '/api/v1/input', headers={'Connection-Uid': lease.uid}, json={'events': [event.model_dump() for event in events]})
                except HTTPException:
                    with suppress(HTTPException):
                        await self.release(target.host, lease)
                    raise
                for event in events:
                    if isinstance(event, KeyEvent):
                        if event.pressed: lease.keys.add(event.key)
                        else: lease.keys.discard(event.key)
                    else:
                        lease.x, lease.y, lease.buttons = event.x, event.y, event.buttons
            lease.touched = time.monotonic()
            session.last_used = lease.touched
            return {'accepted': True}

    async def cleanup(self):
        while True:
            await asyncio.sleep(1)
            for identity, lease in list(self.leases.items()):
                lock = self.host_locks.setdefault(identity, asyncio.Lock())
                if not lock.locked() and time.monotonic() - lease.touched > 8:
                    async with lock:
                        with suppress(HTTPException):
                            await self.release(identity, lease)
