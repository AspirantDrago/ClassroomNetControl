import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from cmnc_veyon_service import main as veyon_main
from cmnc_veyon_service.key_store import KeyStore
from cmnc_veyon_service.main import AUTH_KEYS, FEATURES, Target, VeyonBridge
from cmnc_api_gateway import main as gateway
from cmnc_api_gateway import veyon_routes
from cmnc_api_gateway.schemas import PrincipalResponse


@pytest.fixture
def pem():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def test_key_storage_priority_validation_and_no_plaintext(tmp_path, pem):
    store = KeyStore(tmp_path)
    with pytest.raises(HTTPException):
        store.resolve(1, 2)
    store.save('classroom', 2, 'classroom', pem)
    assert store.resolve(1, 2)[0] == 'classroom'
    store.save('router', 1, 'router', pem)
    assert store.resolve(1, 2)[0] == 'router'
    assert store.metadata('router', 1) == {'configured': True, 'key_name': 'router'}
    assert pem not in json.dumps(store.metadata('router', 1))
    assert pem.encode() not in store.database.read_bytes()
    assert b'BEGIN PRIVATE KEY' not in store.database.read_bytes()
    reopened = KeyStore(tmp_path)
    assert reopened.resolve(1, 2) == ('router', pem)
    reopened.delete('router', 1)
    assert reopened.resolve(1, 2)[0] == 'classroom'
    with pytest.raises(HTTPException):
        store.save('router', 1, 'invalid', 'not a private key')


def test_veyon_authentication_frame_reuse_and_power(tmp_path, pem):
    async def run():
        store = KeyStore(tmp_path)
        store.save('router', 1, 'CMNC', pem)
        calls = []
        def handle(request):
            calls.append((request.method, request.url.path))
            if request.method == 'POST':
                body = json.loads(request.content)
                assert request.extensions['timeout']['read'] > 15
                assert body['method'] == AUTH_KEYS
                assert body['credentials'] == {'keyname': 'CMNC', 'keydata': pem}
                return httpx.Response(200, json={'connection-uid': 'test-connection'})
            assert request.headers['Connection-Uid'] == 'test-connection'
            if request.method == 'GET':
                assert request.url.params['format'] == 'jpeg'
                return httpx.Response(200, content=b'test-jpeg', headers={'content-type': 'image/jpeg'})
            if request.method == 'PUT':
                assert request.url.path.endswith(FEATURES['power-down'])
                assert json.loads(request.content)['active'] is True
            return httpx.Response(200, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(store, client)
            target = Target(device_id=1, router_id=1, classroom_id=2, host='192.168.1.2')
            assert (await bridge.operate(target))[0] == b'test-jpeg'
            assert (await bridge.operate(target))[0] == b'test-jpeg'
            assert (await bridge.operate(target, 'power-down'))['accepted'] is True
            assert sum(method == 'POST' for method, _ in calls) == 1
            for identity in list(bridge.sessions):
                await bridge.close(identity)
            assert not bridge.sessions
    asyncio.run(run())


def test_router_key_failure_does_not_fall_back_to_classroom_key(tmp_path, pem):
    async def run():
        store = KeyStore(tmp_path)
        store.save('classroom', 2, 'classroom', pem)
        store.save('router', 1, 'router', pem)
        names = []
        def handle(request):
            names.append(json.loads(request.content)['credentials']['keyname'])
            return httpx.Response(401, json={'error': {'code': 6, 'message': 'Authentication failed'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(store, client)
            with pytest.raises(HTTPException) as exc:
                await bridge.operate(Target(device_id=1, router_id=1, classroom_id=2, host='192.168.1.2'))
            assert exc.value.status_code == 502
            assert pem not in str(exc.value.detail)
            assert names == ['router']
    asyncio.run(run())


def test_gateway_access_confirmation_and_image_proxy(monkeypatch):
    async def run():
        principal = PrincipalResponse(principal_type='user', id=1, role='teacher', display_name='Teacher', classroom_ids=[7], permissions=[])
        classroom = {'id': 7, 'router_id': 1, 'subnet_cidr': '192.168.1.0/24'}
        devices = [{'id': 10, 'static_ip': '192.168.1.10'}, {'id': 11, 'static_ip': '192.168.2.11'}]
        monkeypatch.setattr(gateway, 'get_current_principal', AsyncMock(return_value=principal))
        monkeypatch.setattr(gateway, 'get_device_classroom_id', AsyncMock(return_value=7))
        monkeypatch.setattr(gateway, 'get_classroom_or_404', AsyncMock(return_value=classroom))
        monkeypatch.setattr(gateway, 'get_wol_classroom_layout', AsyncMock(return_value={'classroom': classroom, 'devices': devices}))
        calls = []
        async def service(method, path, payload=None):
            calls.append((method, path, payload))
            if path.endswith('/frame'):
                return httpx.Response(200, content=b'image', headers={'content-type': 'image/jpeg'})
            return httpx.Response(200, json={'accepted': True})
        monkeypatch.setattr(veyon_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://test') as client:
            response = await client.get('/api/devices/10/veyon/frame')
            assert response.status_code == 200 and response.content == b'image'
            assert response.headers['cache-control'] == 'no-store'
            assert (await client.post('/api/devices/10/veyon/reboot')).status_code == 200
            before = len(calls)
            assert (await client.post('/api/classrooms/7/veyon/power-down-all', json={'confirmed': False})).status_code == 422
            assert len(calls) == before
            batch = await client.post('/api/classrooms/7/veyon/power-down-all', json={'confirmed': True})
            assert batch.json()['accepted_count'] == 1
            assert batch.json()['failed_count'] == 1
            assert (await client.get('/api/admin/veyon/keys/router/1')).status_code == 403
            principal.classroom_ids = []
            before = len(calls)
            assert (await client.get('/api/devices/10/veyon/frame')).status_code == 403
            assert (await client.post('/api/devices/10/veyon/power-down')).status_code == 403
            assert (await client.post('/api/classrooms/7/veyon/power-down-all', json={'confirmed': True})).status_code == 403
            assert len(calls) == before
    asyncio.run(run())



def test_initial_frame_waits_on_the_same_connection(tmp_path, pem, monkeypatch):
    async def run():
        store = KeyStore(tmp_path)
        store.save('router', 1, 'CMNC', pem)
        calls = []
        frames = 0
        def handle(request):
            nonlocal frames
            calls.append(request.method)
            if request.method == 'POST':
                return httpx.Response(200, json={'connection-uid': 'same-connection'})
            assert request.headers['Connection-Uid'] == 'same-connection'
            if request.method == 'GET':
                frames += 1
                if frames < 3:
                    return httpx.Response(503, json={'error': {'code': 10, 'message': 'Framebuffer not available'}})
                return httpx.Response(200, content=b'ready-frame', headers={'content-type': 'image/jpeg'})
            return httpx.Response(200, json={})
        monkeypatch.setattr(veyon_main, 'FRAMEBUFFER_RETRY_DELAY', 0)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(store, client)
            target = Target(device_id=1, router_id=1, classroom_id=2, host='192.168.1.2')
            assert (await bridge.operate(target))[0] == b'ready-frame'
            assert (await bridge.operate(target))[0] == b'ready-frame'
            assert calls.count('POST') == 1
            assert calls.count('DELETE') == 0
            assert len(bridge.sessions) == 1
    asyncio.run(run())


def test_frame_still_missing_preserves_session_for_next_request(tmp_path, pem, monkeypatch):
    async def run():
        store = KeyStore(tmp_path)
        store.save('router', 1, 'CMNC', pem)
        ready = False
        methods = []
        def handle(request):
            methods.append(request.method)
            if request.method == 'POST':
                return httpx.Response(200, json={'connection-uid': 'persistent'})
            if request.method == 'GET' and not ready:
                return httpx.Response(503, json={'error': {'code': 10, 'message': 'Framebuffer not available'}})
            return httpx.Response(200, content=b'frame', headers={'content-type': 'image/jpeg'})
        monkeypatch.setattr(veyon_main, 'FRAMEBUFFER_ATTEMPTS', 2)
        monkeypatch.setattr(veyon_main, 'FRAMEBUFFER_RETRY_DELAY', 0)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(store, client)
            target = Target(device_id=1, router_id=1, classroom_id=2, host='192.168.1.2')
            with pytest.raises(HTTPException) as exc:
                await bridge.operate(target)
            assert exc.value.status_code == 503
            assert len(bridge.sessions) == 1
            ready = True
            assert (await bridge.operate(target))[0] == b'frame'
            assert methods.count('POST') == 1
            assert methods.count('DELETE') == 0
    asyncio.run(run())


def test_frame_diagnostics_are_throttled_and_do_not_log_credentials(tmp_path, pem, caplog):
    async def run():
        store = KeyStore(tmp_path)
        store.save('router', 1, 'CMNC', pem)
        calls = []
        def handle(request):
            calls.append(request.url.path)
            if request.url.path.endswith('/session'):
                return httpx.Response(200, json={'sessionId': 3, 'sessionUptime': 42, 'sessionHostName': 'private-host'})
            return httpx.Response(200, json={'login': 'private-login', 'fullName': 'private-name'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(store, client)
            session = veyon_main.Connection('private-uid', '192.168.1.2', 0, 0)
            target = Target(device_id=1, router_id=1, classroom_id=2, host='192.168.1.2')
            await bridge.log_missing_frame(target, session)
            await bridge.log_missing_frame(target, session)
        assert len(calls) == 2
        assert 'session_id' in caplog.text and 'user_logged_in' in caplog.text
        for secret in (pem, 'private-uid', 'private-login', 'private-name', 'private-host'):
            assert secret not in caplog.text
    asyncio.run(run())


def test_concurrent_viewers_share_frames_but_not_power_commands(tmp_path, pem):
    async def run():
        store = KeyStore(tmp_path)
        store.save('router', 1, 'CMNC', pem)
        store.save('router', 2, 'other-key', pem)
        frames = 0
        auth = 0
        power = 0
        async def handle(request):
            nonlocal frames, auth, power
            if request.method == 'POST':
                auth += 1
                return httpx.Response(200, json={'connection-uid': f'connection-{auth}'})
            if request.method == 'PUT':
                power += 1
                return httpx.Response(200, json={})
            if request.method == 'DELETE':
                return httpx.Response(200, json={})
            frames += 1
            await asyncio.sleep(0.01)
            return httpx.Response(200, content=f'frame-{frames}'.encode(), headers={'content-type': 'image/jpeg'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(store, client)
            target = Target(device_id=1, router_id=1, classroom_id=2, host='192.168.1.2')
            results = await asyncio.gather(*(bridge.operate(target) for _ in range(5)))
            assert len(set(results)) == 1
            assert frames == 1 and auth == 1
            await bridge.operate(target, 'reboot')
            await bridge.operate(target, 'reboot')
            assert power == 2
            session = next(iter(bridge.sessions.values()))
            session.frame_at -= 1
            assert (await bridge.operate(target))[0] == b'frame-2'
            wider = target.model_copy(update={'width': 1920})
            assert (await bridge.operate(wider))[0] == b'frame-3'
            other_key = wider.model_copy(update={'router_id': 2})
            assert (await bridge.operate(other_key))[0] == b'frame-4'
            assert auth == 2
            await bridge.close(bridge.identity(target)[0])
            assert (await bridge.operate(target))[0] == b'frame-5'
            assert auth == 3
    asyncio.run(run())


@pytest.mark.parametrize('action,feature',[
    ('reboot','4f7d98f0-395a-4fff-b968-e49b8d0f748c'),
    ('install-updates-and-power-down','09bcb3a1-fc11-4d03-8cf1-efd26be8655b'),
])
def test_additional_power_commands_select_native_veyon_feature(tmp_path,pem,action,feature):
    async def run():
        store=KeyStore(tmp_path)
        store.save('router',1,'CMNC',pem)
        puts=[]
        def handle(request):
            if request.method=='POST':
                return httpx.Response(200,json={'connection-uid':'test-session'})
            if request.method=='PUT':
                puts.append(request)
                assert request.url.path=='/api/v1/feature/'+feature
                assert request.headers['Connection-Uid']=='test-session'
                assert json.loads(request.content)=={'active':True,'arguments':{}}
            return httpx.Response(200,json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge=VeyonBridge(store,client)
            result=await bridge.operate(Target(device_id=1,router_id=1,classroom_id=1,host='192.168.1.2'),action)
            assert result['accepted'] is True
            assert len(puts)==1
    asyncio.run(run())


def test_snapshot_uses_native_png_and_never_reuses_monitoring_jpeg(tmp_path, pem):
    async def run():
        store = KeyStore(tmp_path)
        store.save('router', 1, 'CMNC', pem)
        image_requests = []

        def handle(request):
            if request.method == 'POST':
                return httpx.Response(200, json={'connection-uid': 'snapshot-session'})
            assert request.headers['Connection-Uid'] == 'snapshot-session'
            params = dict(request.url.params)
            image_requests.append(params)
            if params['format'] == 'png':
                assert params == {'format': 'png', 'compression': '5'}
                return httpx.Response(200, content=b'native-png', headers={'content-type': 'image/png'})
            assert params['width'] == '320'
            return httpx.Response(200, content=b'thumbnail-jpeg', headers={'content-type': 'image/jpeg'})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(store, client)
            target = Target(device_id=1, router_id=1, classroom_id=2, host='192.168.1.2', width=320)
            await bridge.operate(target)
            identity, _, _ = bridge.identity(target)
            cached = bridge.sessions[identity].frame
            assert await bridge.operate(target, snapshot=True) == (b'native-png', 'image/png')
            assert await bridge.operate(target, snapshot=True) == (b'native-png', 'image/png')
            assert bridge.sessions[identity].frame == cached
            assert [params['format'] for params in image_requests] == ['jpeg', 'png', 'png']
    asyncio.run(run())


def test_snapshot_gateway_checks_device_access_and_png(monkeypatch):
    async def run():
        principal = PrincipalResponse(principal_type='user', id=1, role='teacher', display_name='Teacher', classroom_ids=[7], permissions=[])
        classroom = {'id': 7, 'router_id': 1, 'subnet_cidr': '192.168.1.0/24'}
        monkeypatch.setattr(gateway, 'get_current_principal', AsyncMock(return_value=principal))
        monkeypatch.setattr(gateway, 'get_device_classroom_id', AsyncMock(return_value=7))
        monkeypatch.setattr(gateway, 'get_classroom_or_404', AsyncMock(return_value=classroom))
        monkeypatch.setattr(gateway, 'get_wol_classroom_layout', AsyncMock(return_value={
            'classroom': classroom, 'devices': [{'id': 10, 'static_ip': '192.168.1.10'}]}))
        service = AsyncMock(return_value=httpx.Response(200, content=b'native-png', headers={'content-type': 'image/png'}))
        monkeypatch.setattr(veyon_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://test') as client:
            response = await client.get('/api/devices/10/veyon/snapshot')
            assert response.status_code == 200 and response.content == b'native-png'
            assert response.headers['content-type'] == 'image/png'
            assert response.headers['cache-control'] == 'no-store'
            service.assert_awaited_once_with('POST', '/internal/device/snapshot', {
                'device_id': 10, 'classroom_id': 7, 'router_id': 1, 'host': '192.168.1.10'})
            service.return_value = httpx.Response(200, content=b'jpeg', headers={'content-type': 'image/jpeg'})
            assert (await client.get('/api/devices/10/veyon/snapshot')).status_code == 502
            service.reset_mock()
            principal.classroom_ids = []
            assert (await client.get('/api/devices/10/veyon/snapshot')).status_code == 403
            service.assert_not_awaited()
    asyncio.run(run())
