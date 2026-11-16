import asyncio
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass, field

from fastapi import HTTPException
from cmnc_contracts.demo_endpoint import DemoEndpoint
from cmnc_veyon_service.demo_relay import DemoRelay, validate_frame, jpeg_size
from cmnc_veyon_service.demo_probe import probe_recipients

FEATURES = {
    'demo-server': 'e4b6e743-1f5b-491d-9364-e091086200f4',
    'demo-fullscreen': '7b6231bd-eb89-45d3-af32-f70663b2f878',
    'demo-window': 'ae45c3db-dc2e-4204-ae8b-374cdab8c62c',
}


@dataclass
class Demonstration:
    id: str
    owner: str
    classroom_id: int
    targets: list
    source: object
    mode: str
    endpoint: DemoEndpoint
    direct_probe_callback_url: str | None = field(default=None, repr=False)
    source_token: str = field(default_factory=lambda: secrets.token_hex(32), repr=False)
    native_started: bool = False
    direct_targets: set[int] = field(default_factory=set)
    probe_tokens: dict[int, str] = field(default_factory=dict, repr=False)
    probe_results: dict[int, bool] = field(default_factory=dict, repr=False)
    token: str = field(default_factory=lambda: secrets.token_hex(32), repr=False)
    touched: float = field(default_factory=time.monotonic)
    created: float = field(default_factory=time.monotonic)
    stopping: bool = False
    ready: bool = False
    results: list = field(default_factory=list)
    frame: bytes | None = field(default=None, repr=False)
    version: int = 0
    changed: asyncio.Condition = field(default_factory=asyncio.Condition, repr=False)
    worker: asyncio.Task | None = field(default=None, repr=False)
    pins: list[str] = field(default_factory=list, repr=False)
    frame_size: tuple[int, int] = (1280, 720)
    source_worker: asyncio.Task | None = field(default=None, repr=False)
    source_ready: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    source_error: HTTPException | None = field(default=None, repr=False)

    def public(self):
        return {'id': self.id, 'owner': self.owner, 'classroom_id': self.classroom_id,
                'ready': self.ready, 'results': self.results, 'active': not self.stopping,
                'error': str(self.source_error.detail) if self.source_error else None,
                'direct_count': len(self.direct_targets), 'relay_count': len(self.targets) - len(self.direct_targets),
                'source_device_id': self.source.device_id if self.source else None,
                'source_classroom_id': self.source.classroom_id if self.source else None}


class Demonstrations:
    def __init__(self, bridge, target_type, listen_port=11400, *, fps=10, quality=100):
        self.bridge, self.target_type = bridge, target_type
        if not 1 <= fps <= 30 or not 1 <= quality <= 100:
            raise ValueError('CMNC_VEYON_DEMO_FPS must be 1..30 and CMNC_VEYON_DEMO_QUALITY 1..100')
        self.listen_port, self.fps, self.quality = listen_port, fps, quality
        self.sessions = {}
        self.relay = DemoRelay(self.sessions)
        self.cleaner = None
        self.stop_tasks = {}

    async def start(self):
        await self.relay.start(self.listen_port)
        self.cleaner = asyncio.create_task(self.cleanup())

    def get(self, session_id):
        session = self.sessions.get(session_id)
        if session is None:
            raise HTTPException(404, 'Демонстрация завершена')
        return session

    async def create(self, owner, classroom_id, targets, source, mode, *, endpoint: DemoEndpoint, direct_probe_callback_url: str | None = None):
        if len(self.sessions) >= 32:
            raise HTTPException(429, 'Достигнут лимит демонстраций')
        targets = [self.target_type(**t) for t in targets]
        source = self.target_type(**source) if source else None
        targets = [t for t in targets if source is None or t.device_id != source.device_id]
        if not targets:
            raise HTTPException(409, 'Нет подходящих получателей демонстрации')
        ids = {t.device_id for t in targets} | ({source.device_id} if source else set())
        for active in self.sessions.values():
            active_ids = {t.device_id for t in active.targets} | ({active.source.device_id} if active.source else set())
            if ids & active_ids:
                raise HTTPException(409, 'На выбранных ПК уже идёт демонстрация. Сначала остановите её')
        session = Demonstration(secrets.token_urlsafe(24), owner, classroom_id, targets, source, mode, endpoint.model_copy(deep=True), direct_probe_callback_url=direct_probe_callback_url)
        # Pin control connections while a feature runs: closing the WebAPI
        # connection can implicitly stop a fullscreen demo on the recipient.
        session.pins = [self.bridge.identity(t)[0] for t in targets + ([source] if source else [])]
        self.bridge.demo_hosts.update(session.pins)
        self.sessions[session.id] = session
        session.worker = asyncio.create_task(self.dispatch(session))
        return session.public()

    async def dispatch(self, session):
        try:
            host, port = session.endpoint.relay_host, session.endpoint.relay_port
            if session.source and session.direct_probe_callback_url:
                await self.select_direct_targets(session)
            if session.source and len(session.direct_targets) < len(session.targets):
                session.source_worker = asyncio.create_task(self.capture_source(session))
                try:
                    async with asyncio.timeout(35):
                        await session.source_ready.wait()
                except TimeoutError as exc:
                    raise HTTPException(504, 'Не удалось получить первый кадр ПК-источника') from exc
                if session.source_error:
                    raise session.source_error
            arguments = {'demoAccessToken': session.token, 'demoServerHost': host, 'demoServerPort': port}
            semaphore = asyncio.Semaphore(30)
            async def send(target):
                try:
                    async with asyncio.timeout(45), semaphore:
                        await self.bridge.operate(target, session.mode, arguments=(
                            {'demoAccessToken': session.source_token, 'demoServerHost': session.source.host, 'demoServerPort': 11400}
                            if target.device_id in session.direct_targets else arguments))
                    session.results.append({'device_id': target.device_id, 'accepted': True,
                                            'transport': 'direct' if target.device_id in session.direct_targets else 'relay'})
                except (HTTPException, TimeoutError) as exc:
                    session.results.append({'device_id': target.device_id, 'accepted': False,
                        'error': str(exc.detail) if isinstance(exc, HTTPException) else 'Превышено время ожидания',
                        'timed_out': isinstance(exc, TimeoutError) or getattr(exc, 'status_code', 0) == 504})
            await asyncio.gather(*(send(t) for t in session.targets))
        except HTTPException as exc:
            session.results.extend({'device_id': t.device_id, 'accepted': False, 'error': str(exc.detail),
                                    'timed_out': exc.status_code == 504} for t in session.targets)
        finally:
            session.ready = True

    async def select_direct_targets(self, session):
        try:
            # Mark before sending: a timeout can occur after remote activation.
            session.native_started = True
            async with asyncio.timeout(30):
                await self.bridge.operate(session.source, 'demo-server', arguments={
                    'demoAccessToken': session.source_token, 'demoServerPort': 11400})
            session.direct_targets = await probe_recipients(self.bridge, session, session.direct_probe_callback_url)
        except (HTTPException, TimeoutError, ValueError):
            session.direct_targets.clear()
        finally:
            session.probe_tokens.clear()
        if not session.direct_targets and session.native_started:
            try:
                async with asyncio.timeout(15):
                    await self.bridge.operate(session.source, 'demo-server', active=False)
                session.native_started = False
            except (HTTPException, TimeoutError):
                pass  # retain the flag so final cleanup retries the source stop

    async def capture_source(self, session):
        last_success = time.monotonic()
        try:
            while not session.stopping:
                started = time.monotonic()
                try:
                    async with asyncio.timeout(35 if session.frame is None else 10):
                        data, content_type = await self.bridge.demo_frame(session.source, self.quality)
                    if content_type.split(';', 1)[0].lower() != 'image/jpeg':
                        raise ValueError('Veyon не вернул кадр JPEG')
                    size = jpeg_size(data)
                    async with session.changed:
                        session.frame, session.frame_size = data, size
                        session.version += 1
                        session.changed.notify_all()
                    last_success = time.monotonic()
                    session.source_ready.set()
                except HTTPException:
                    if session.frame is None or time.monotonic() - last_success >= 10:
                        raise
                    # A brief source hiccup must not leave a permanent frozen frame.
                    await asyncio.sleep(0.5)
                await asyncio.sleep(max(0.001, 1 / self.fps - (time.monotonic() - started)))
        except ValueError as exc:
            session.source_error = HTTPException(502, str(exc))
        except HTTPException as exc:
            session.source_error = exc
        except TimeoutError:
            session.source_error = HTTPException(504, 'Превышено время получения кадра ПК-источника')
        finally:
            session.source_ready.set()
            async with session.changed:
                session.changed.notify_all()

    async def stop(self, session):
        # Shutdown/cancelled HTTP requests must not interrupt remote cleanup.
        task = self.stop_tasks.get(session.id)
        if task is None:
            task = asyncio.create_task(self._stop(session))
            self.stop_tasks[session.id] = task
            task.add_done_callback(lambda _: self.stop_tasks.pop(session.id, None))
        await asyncio.shield(task)

    async def _stop(self, session):
        if self.sessions.get(session.id) is not session:
            return
        session.stopping = True
        async with session.changed:
            session.changed.notify_all()
        # Dispatch may have reached the remote host before cancellation; always stop
        # every attempted recipient, including uncertain/time-out requests.
        if session.worker:
            session.worker.cancel()
            with suppress(asyncio.CancelledError):
                await session.worker
        if session.source_worker:
            session.source_worker.cancel()
            with suppress(asyncio.CancelledError):
                await session.source_worker
        async def stop_target(target, feature):
            with suppress(HTTPException, TimeoutError):
                async with asyncio.timeout(25):
                    await self.bridge.operate(target, feature, active=False)
        await asyncio.gather(*(stop_target(t, session.mode) for t in session.targets))
        session.probe_tokens.clear()
        if session.native_started:
            await stop_target(session.source, 'demo-server')
        self.sessions.pop(session.id, None)
        self.bridge.demo_hosts.difference_update(session.pins)
        session.frame = None

    async def upload(self, session, data):
        if session.source or session.stopping:
            raise HTTPException(409, 'Демонстрация не принимает кадры браузера')
        try:
            validate_frame(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        session.touched = time.monotonic()
        async with session.changed:
            session.frame = data
            session.version += 1
            session.changed.notify_all()

    async def cleanup(self):
        while True:
            await asyncio.sleep(5)
            await asyncio.gather(*(self.stop(s) for s in list(self.sessions.values())
                if not s.stopping and (s.source_error or time.monotonic() - s.touched > 60 or time.monotonic() - s.created > 5400)))
            if int(time.monotonic() / 5) % 4 == 0:
                await self.keepalive()

    async def keepalive(self):
        capacity = asyncio.Semaphore(8)
        async def touch(target):
            with suppress(HTTPException, TimeoutError):
                async with asyncio.timeout(5), capacity:
                    identity, _, _ = self.bridge.identity(target)
                    connection = self.bridge.sessions.get(identity)
                    if connection:
                        await self.bridge.checked('GET', '/api/v1/user', headers={'Connection-Uid': connection.uid})
                        connection.last_used = time.monotonic()
        targets = [t for s in self.sessions.values() if not s.stopping
                   for t in s.targets + ([s.source] if s.source else [])]
        await asyncio.gather(*(touch(t) for t in targets))

    async def close(self):
        if self.cleaner:
            self.cleaner.cancel()
            with suppress(asyncio.CancelledError):
                await self.cleaner
        await asyncio.gather(*(self.stop(s) for s in list(self.sessions.values())))
        await self.relay.close()
