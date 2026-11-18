import asyncio
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from cmnc_veyon_service.main import Target, VeyonBridge
from cmnc_contracts.demo_endpoint import DemoEndpoint
from pydantic import ValidationError
from cmnc_veyon_service.demo_relay import DemoRelay, compact_length, validate_frame, variant_int, message, jpeg_size
from cmnc_veyon_service.demonstrations import Demonstrations


def target(device_id=1):
    return dict(device_id=device_id, classroom_id=1, router_id=1, host=f'192.168.1.{device_id}')


def jpeg(width=1920, height=1080):
    return b'\xff\xd8\xff\xc0\x00\x08\x08' + struct.pack('!HH', height, width) + b'\x03\xff\xd9'


def bridge():
    return SimpleNamespace(operate=AsyncMock(), demo_frame=AsyncMock(return_value=(jpeg(), 'image/jpeg')),
                           identity=lambda t: (t.host, 'key', 'pem'), demo_hosts=set())


def test_pc_demo_uses_one_server_producer_for_many_recipients():
    async def run():
        b = bridge(); service = Demonstrations(b, Target, 11400)
        result = await service.create('user:1', 1, [target(n) for n in range(1, 17)], target(), 'demo-window', endpoint=DemoEndpoint(relay_host='192.168.10.11', relay_port=11400))
        session = service.get(result['id']); await session.worker
        calls = b.operate.await_args_list
        assert len(calls) == 15
        assert all(c.args[0].device_id != 1 and c.args[1] == 'demo-window' for c in calls)
        assert all(c.kwargs['arguments']['demoServerHost'] == '192.168.10.11' for c in calls)
        assert all(c.kwargs['arguments']['demoServerPort'] == 11400 for c in calls)
        assert b.demo_frame.await_count == 1
        b.demo_frame.assert_awaited_once_with(session.source, 100)
        assert session.frame == jpeg() and session.frame_size == (1920, 1080)
        assert 'token' not in session.public()
        assert len(b.demo_hosts) == 16
        with pytest.raises(HTTPException) as error:
            await service.create('user:2', 1, [target(2)], None, 'demo-window', endpoint=DemoEndpoint(relay_host='192.168.10.11', relay_port=11400))
        assert error.value.status_code == 409
        await service.stop(session)
        assert not b.demo_hosts and not service.sessions and session.frame is None
        assert session.source_worker.done()
        assert len(b.operate.await_args_list) == 30
        assert all(c.kwargs['active'] is False for c in b.operate.await_args_list[15:])
    asyncio.run(run())


def test_browser_demo_needs_reachable_host_and_refuses_invalid_frames():
    async def run():
        service = Demonstrations(bridge(), Target, 0)
        result = await service.create('user:1', 1, [target()], None, 'demo-fullscreen', endpoint=DemoEndpoint(relay_host='192.168.10.11', relay_port=11400))
        session = service.get(result['id']); await session.worker
        with pytest.raises(HTTPException): await service.upload(session, b'not jpeg')
        assert session.frame is None
        await service.stop(session)
    asyncio.run(run())


def test_source_is_not_a_recipient_and_needs_other_receivers():
    async def run():
        service = Demonstrations(bridge(), Target, 0)
        with pytest.raises(HTTPException):
            await service.create('user:1', 1, [target()], target(), 'demo-window', endpoint=DemoEndpoint(relay_host='192.168.10.11', relay_port=11400))
        assert not service.sessions
    asyncio.run(run())


@pytest.mark.parametrize('source', [None, object()])
@pytest.mark.parametrize('advertised', [(7,), (16, 6, 0)])
def test_relay_veyon_token_handshake_and_tight_jpeg_frame(source, advertised):
    async def run():
        # SOF contains the required dimensions; protocol round trip preserves bytes.
        jpeg = b'\xff\xd8\xff\xc0\x00\x08\x08' + struct.pack('!HH', 720, 1280) + b'\x03\xff\xd9'
        validate_frame(jpeg)
        session = SimpleNamespace(id='id', source=source, token='a' * 64, stopping=False,
            frame=jpeg, version=1, changed=asyncio.Condition())
        relay = DemoRelay({'id': session}); await relay.start(0)
        port = relay.server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        assert await reader.readexactly(12) == b'RFB 003.008\n'
        writer.write(b'RFB 003.008\n'); await writer.drain()
        assert await reader.readexactly(2) == b'\x01\x28'
        writer.write(b'\x28'); await writer.drain()
        assert await message(reader) == variant_int(1) + variant_int(5)
        reply = variant_int(5) + struct.pack('!IBI', 10, 0, 0)
        writer.write(struct.pack('!I', len(reply)) + reply); await writer.drain()
        assert await message(reader) == b''
        token = struct.pack('!IBI', 12, 0, 64) + b'a' * 64
        writer.write(struct.pack('!I', len(token)) + token); await writer.drain()
        assert await reader.readexactly(4) == b'\0' * 4
        writer.write(b'\x01'); await writer.drain()
        init = await reader.readexactly(24)
        assert struct.unpack('!HH', init[:4]) == (1280, 720)
        await reader.readexactly(int.from_bytes(init[-4:], 'big'))
        # These normal native requests precede the first image request. Their
        # payload is opaque to a read-only demo server, like upstream Veyon.
        feature = b'veyon-version-request'
        writer.write(b'\x29' + struct.pack('!I', len(feature)) + feature)
        writer.write(struct.pack('!BBH', 2, 0, len(advertised)) + struct.pack('!' + 'i' * len(advertised), *advertised))
        writer.write(struct.pack('!BBHHHH', 3, 0, 0, 0, 1280, 720)); await writer.drain()
        update = await reader.readexactly(16)
        assert update[:4] == b'\x00\x00\x00\x01'
        assert struct.unpack('!HHHHi', update[4:]) == (0, 0, 1280, 720, 7)
        assert await reader.readexactly(1) == b'\x90'
        assert await reader.readexactly(1) == compact_length(len(jpeg))
        assert await reader.readexactly(len(jpeg)) == jpeg
        writer.close(); await writer.wait_closed(); await relay.close()
    asyncio.run(run())


@pytest.mark.parametrize('frame', [b'', b'\xff\xd8bad\xff\xd9', b'x' * (2 * 1024 * 1024 + 1)])
def test_relay_rejects_malformed_or_oversized_jpeg(frame):
    with pytest.raises(ValueError): validate_frame(frame)


def test_stopping_caller_cancellation_does_not_interrupt_remote_cleanup():
    async def run():
        b = bridge(); service = Demonstrations(b, Target, 11400)
        result = await service.create('user:1', 1, [target()], None, 'demo-window', endpoint=DemoEndpoint(relay_host='192.168.10.11', relay_port=11400))
        session = service.get(result['id']); await session.worker
        entered, release = asyncio.Event(), asyncio.Event()
        async def remote_stop(*args, **kwargs):
            entered.set(); await release.wait()
        b.operate.side_effect = remote_stop
        stopping = asyncio.create_task(service.stop(session))
        await entered.wait(); stopping.cancel()
        with pytest.raises(asyncio.CancelledError): await stopping
        assert session.stopping and service.stop_tasks
        release.set(); await service.close()
        assert not service.sessions and not b.demo_hosts
    asyncio.run(run())


def test_failed_native_source_never_starts_recipients():
    async def run():
        b = bridge(); b.demo_frame.side_effect = HTTPException(504, 'Source offline')
        service = Demonstrations(b, Target, 11400)
        result = await service.create('user:1', 1, [target(2)], target(), 'demo-fullscreen', endpoint=DemoEndpoint(relay_host='192.168.10.11', relay_port=11400))
        session = service.get(result['id']); await session.worker
        assert session.ready and len(session.results) == 1
        assert session.results[0]['accepted'] is False
        assert session.results[0]['timed_out'] is True
        assert b.operate.await_count == 0
        await service.stop(session)
        assert not service.sessions and not b.demo_hosts
    asyncio.run(run())


def test_pc_demonstration_requires_valid_endpoint():
    with pytest.raises(ValidationError):
        DemoEndpoint(relay_host='', relay_port=11400)


def test_source_capture_can_be_cancelled_during_first_frame():
    async def run():
        b = bridge(); entered, cancelled = asyncio.Event(), asyncio.Event()
        async def frame(*args):
            entered.set()
            try: await asyncio.Event().wait()
            finally: cancelled.set()
        b.demo_frame.side_effect = frame
        service = Demonstrations(b, Target, 11400)
        result = await service.create('user:1', 1, [target(2)], target(), 'demo-window', endpoint=DemoEndpoint(relay_host='192.168.10.11', relay_port=11400))
        session = service.get(result['id']); await entered.wait()
        await service.stop(session)
        assert cancelled.is_set() and not service.sessions and not b.demo_hosts
        assert session.worker.done() and session.source_worker.done()
    asyncio.run(run())


def test_native_dimensions_are_not_resized_and_browser_dimensions_stay_fixed():
    assert jpeg_size(jpeg(3840, 2160)) == (3840, 2160)
    with pytest.raises(ValueError): validate_frame(jpeg(3840, 2160))
    with pytest.raises(ValueError): jpeg_size(jpeg(8192, 8192))
    with pytest.raises(ValueError): jpeg_size(b'\xff\xd8' + b'x' * (1 << 22) + b'\xff\xd9')


def test_native_frame_requests_original_size_quality_and_reuses_connection():
    import httpx
    async def run():
        b = VeyonBridge(SimpleNamespace(resolve=lambda *args: ('key', 'pem')), None)
        t = Target(**target()); identity = b.identity(t)[0]
        b.connection = AsyncMock(return_value=SimpleNamespace(uid='uid', frame=None, frame_at=0))
        b.checked = AsyncMock(return_value=httpx.Response(200, content=jpeg(), headers={'content-type': 'image/jpeg'}))
        assert await b.demo_frame(t) == (jpeg(), 'image/jpeg')
        assert b.checked.await_args.kwargs['params'] == {'format': 'jpeg', 'quality': 100}
        assert b.connection.await_count == 1
        # A second consumer shares the encoded JPEG cache, without another encoding request.
        result = await b.demo_frame(t)
        assert result[0] == jpeg() and b.checked.await_count == 1
    asyncio.run(run())


async def relay_client(port, token, expected_size):
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    assert await reader.readexactly(12) == b'RFB 003.008\n'
    writer.write(b'RFB 003.008\n'); await writer.drain()
    assert await reader.readexactly(2) == b'\x01\x28'
    writer.write(b'\x28'); await writer.drain()
    assert await message(reader) == variant_int(1) + variant_int(5)
    reply = variant_int(5) + struct.pack('!IBI', 10, 0, 0)
    writer.write(struct.pack('!I', len(reply)) + reply); await writer.drain()
    assert await message(reader) == b''
    token = token.encode()
    payload = struct.pack('!IBI', 12, 0, len(token)) + token
    writer.write(struct.pack('!I', len(payload)) + payload); await writer.drain()
    assert await reader.readexactly(4) == b'\0' * 4
    writer.write(b'\x01'); await writer.drain()
    init = await reader.readexactly(24)
    assert struct.unpack('!HH', init[:4]) == expected_size
    await reader.readexactly(int.from_bytes(init[-4:], 'big'))
    writer.write(struct.pack('!BBHii', 2, 0, 2, 7, -223)); await writer.drain()
    return reader, writer


async def read_frame(reader, writer, frame, width, height, resize=False):
    writer.write(struct.pack('!BBHHHH', 3, 1, 0, 0, width, height)); await writer.drain()
    assert await reader.readexactly(4) == struct.pack('!BBH', 0, 0, 2 if resize else 1)
    if resize:
        assert await reader.readexactly(12) == struct.pack('!HHHHi', 0, 0, width, height, -223)
    assert await reader.readexactly(12) == struct.pack('!HHHHi', 0, 0, width, height, 7)
    assert await reader.readexactly(1) == b'\x90'
    size = compact_length(len(frame))
    assert await reader.readexactly(len(size)) == size
    assert await reader.readexactly(len(frame)) == frame


def test_shared_source_reaches_two_clients_unchanged_and_resizes_without_restarting_capture():
    async def run():
        b = bridge(); queue = asyncio.Queue()
        await queue.put(jpeg())
        async def frame(*args): return await queue.get(), 'image/jpeg'
        b.demo_frame.side_effect = frame
        service = Demonstrations(b, Target, 0)
        await service.relay.start(0)
        port = service.relay.server.sockets[0].getsockname()[1]
        result = await service.create('user:1', 1, [target(2), target(3)], target(), 'demo-fullscreen', endpoint=DemoEndpoint(relay_host='192.168.10.11', relay_port=11400))
        session = service.get(result['id']); await session.worker
        clients = []
        try:
            for _ in range(2):
                reader, writer = await relay_client(port, session.token, (1920, 1080))
                clients.append((reader, writer))
                await read_frame(reader, writer, jpeg(), 1920, 1080)
            assert b.demo_frame.await_count <= 2  # one capture in progress, never one per recipient
            async with session.changed:
                await queue.put(jpeg(2560, 1440))
                await session.changed.wait_for(lambda: session.frame_size == (2560, 1440))
            for reader, writer in clients:
                await read_frame(reader, writer, jpeg(2560, 1440), 2560, 1440, resize=True)
            source_task = session.source_worker
            await service.stop(session)
            assert source_task.done() and session.frame is None and not b.demo_hosts
        finally:
            for reader, writer in clients:
                writer.close(); await writer.wait_closed()
            await service.close()
    asyncio.run(run())


def test_sessions_keep_separate_immutable_router_endpoints():
    async def run():
        b = bridge(); service = Demonstrations(b, Target, 11400)
        one = DemoEndpoint(relay_host='192.168.10.11', relay_port=11400)
        two = DemoEndpoint(relay_host='cmnc.branch.local', relay_port=21400)
        first = await service.create('user:1', 1, [target(1)], None, 'demo-window', endpoint=one)
        second = await service.create('user:1', 1, [target(2)], None, 'demo-window', endpoint=two)
        one.relay_host = 'changed.local'
        await service.get(first['id']).worker; await service.get(second['id']).worker
        args = {c.args[0].device_id: c.kwargs['arguments'] for c in b.operate.await_args_list}
        assert args[1]['demoServerHost'] == '192.168.10.11' and args[1]['demoServerPort'] == 11400
        assert args[2]['demoServerHost'] == 'cmnc.branch.local' and args[2]['demoServerPort'] == 21400
        await service.close()
    asyncio.run(run())


@pytest.mark.parametrize('direct_ids', [{2, 3}, {2}, set()])
def test_auto_routes_verified_recipients_direct_and_others_via_relay(monkeypatch, direct_ids):
    from cmnc_veyon_service import demonstrations as module
    async def run():
        b = bridge()
        probe = AsyncMock(return_value=direct_ids)
        monkeypatch.setattr(module, 'probe_recipients', probe)
        service = Demonstrations(b, Target, 11400)
        result = await service.create('user:1', 1, [target(2), target(3)], target(1), 'demo-window',
            endpoint=DemoEndpoint(relay_host='cmnc.example.local', relay_port=21400),
            direct_probe_callback_url='https://cmnc.example.local')
        session = service.get(result['id']); await session.worker
        assert probe.await_count == 1
        server_start = next(c for c in b.operate.await_args_list if c.args[1] == 'demo-server')
        assert server_start.kwargs['arguments']['vncServerPortOffset'] == 0
        clients = {c.args[0].device_id: c.kwargs['arguments'] for c in b.operate.await_args_list if c.args[1] == 'demo-window'}
        for device_id in (2, 3):
            if device_id in direct_ids:
                assert clients[device_id] == {'demoServerHost': '192.168.1.1', 'demoServerPort': 11400,
                    'demoAccessToken': session.source_token}
            else:
                assert clients[device_id] == {'demoServerHost': 'cmnc.example.local', 'demoServerPort': 21400,
                    'demoAccessToken': session.token}
        assert (session.source_worker is None) == (direct_ids == {2, 3})
        assert b.demo_frame.await_count == int(direct_ids != {2, 3})
        await service.stop(session)
        assert not service.sessions and not b.demo_hosts
        stops = [c for c in b.operate.await_args_list if c.args[1] == 'demo-server' and c.kwargs.get('active') is False]
        assert len(stops) == 1
    asyncio.run(run())


def test_probe_failure_uses_relay_and_stops_native_source(monkeypatch):
    from cmnc_veyon_service import demonstrations as module
    async def run():
        b = bridge(); monkeypatch.setattr(module, 'probe_recipients', AsyncMock(side_effect=HTTPException(503, 'Unavailable')))
        service = Demonstrations(b, Target, 11400)
        result = await service.create('user:1', 1, [target(2)], target(), 'demo-fullscreen',
            endpoint=DemoEndpoint(relay_host='cmnc.example.local', relay_port=11400),
            direct_probe_callback_url='https://cmnc.example.local')
        session = service.get(result['id']); await session.worker
        assert not session.direct_targets and session.source_worker and not session.native_started
        assert any(c.kwargs.get('active') is False for c in b.operate.await_args_list)
        assert session.results[0]['accepted'] and session.results[0]['transport'] == 'relay'
        await service.close()
    asyncio.run(run())


def test_cancel_during_probe_stops_native_server_and_invalidates_callbacks(monkeypatch):
    from cmnc_veyon_service import demonstrations as module
    async def run():
        entered = asyncio.Event()
        async def probe(bridge, session, callback):
            session.probe_tokens = {2: 'a' * 32}
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(module, 'probe_recipients', probe)
        b = bridge(); service = Demonstrations(b, Target, 11400)
        result = await service.create('user:1', 1, [target(2)], target(), 'demo-window',
            endpoint=DemoEndpoint(relay_host='cmnc.example.local', relay_port=11400),
            direct_probe_callback_url='https://cmnc.example.local')
        session = service.get(result['id']); await entered.wait(); await service.stop(session)
        assert session.worker.done() and not session.probe_tokens and not service.sessions and not b.demo_hosts
        assert b.demo_frame.await_count == 0
        assert any(c.args[1] == 'demo-server' and c.kwargs.get('active') is False for c in b.operate.await_args_list)
    asyncio.run(run())


def test_relay_rejects_oversized_feature_without_allocating_or_losing_other_clients():
    async def run():
        session = SimpleNamespace(id='test', token='a'*64, stopping=False, frame_size=(1920,1080),
            frame=jpeg(),version=1,changed=asyncio.Condition())
        relay=DemoRelay({'test':session});await relay.start(0)
        port=relay.server.sockets[0].getsockname()[1]
        first, first_writer=await relay_client(port,session.token,(1920,1080))
        other, other_writer=await relay_client(port,session.token,(1920,1080))
        try:
            first_writer.write(b'\x29'+struct.pack('!I',8193));await first_writer.drain()
            async with asyncio.timeout(2): assert await first.read() == b''
            await read_frame(other,other_writer,jpeg(),1920,1080)
        finally:
            first_writer.close();other_writer.close()
            await relay.close()
    asyncio.run(run())
