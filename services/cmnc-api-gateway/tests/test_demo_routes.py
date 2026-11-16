import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from cmnc_api_gateway.schemas import PrincipalResponse
from cmnc_api_gateway import main, demo_routes


def setup(monkeypatch):
    principal = PrincipalResponse(principal_type='user', id=1, role='teacher', display_name='Test', classroom_ids=[7], permissions=[])
    monkeypatch.setattr(main, 'get_current_principal', AsyncMock(return_value=principal))
    monkeypatch.setattr(main, 'ensure_classroom_access', AsyncMock())
    layout = {'classroom': {'id': 7, 'router_id': 1, 'subnet_cidr': '192.168.1.0/24'}, 'devices': [
        {'id': 1, 'static_ip': '192.168.1.1', 'inventory_name': 'PC', 'mac_address': 'A'},
        {'id': 2, 'static_ip': '192.168.1.2', 'veyon_bulk_protected': True, 'mac_address': 'B'},
        {'id': 3, 'static_ip': '192.168.1.3', 'is_non_pc': True, 'mac_address': 'C'}]}
    monkeypatch.setattr(main, 'get_wol_classroom_layout', AsyncMock(return_value=layout))
    monkeypatch.setattr(main, 'get_device_classroom_id', AsyncMock(return_value=7))
    monkeypatch.setattr(main, 'get_router_connection_from_inventory', AsyncMock(return_value={
        'veyon_demo_host': '192.168.10.11', 'veyon_demo_port': 21400}))
    return layout


def test_classroom_demo_excludes_non_pc_without_counting_as_skipped(monkeypatch):
    async def run():
        setup(monkeypatch)
        service = AsyncMock(return_value=httpx.Response(200, json={'id': 'session', 'owner': 'user:1'}))
        monkeypatch.setattr(demo_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            response = await client.post('/api/classrooms/7/veyon/demonstrations', json={'mode': 'demo-window', 'confirmed': True})
        assert response.status_code == 200, response.text
        assert response.json()['skipped_count'] == 1
        assert 'owner' not in response.json()
        payload = service.await_args.args[2]
        assert [t['device_id'] for t in payload['targets']] == [1]
        assert payload['owner'] == 'user:1'
        assert payload['relay_host'] == '192.168.10.11' and payload['relay_port'] == 21400
        main.get_router_connection_from_inventory.assert_awaited_once_with(1)
    asyncio.run(run())


def test_direct_demo_allows_explicit_protected_receiver(monkeypatch):
    async def run():
        setup(monkeypatch)
        service = AsyncMock(return_value=httpx.Response(200, json={'id': 'session'}))
        monkeypatch.setattr(demo_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            response = await client.post('/api/devices/2/veyon/demonstrations', json={'mode': 'demo-fullscreen', 'confirmed': True})
        assert response.status_code == 200
        assert service.await_args.args[2]['targets'][0]['device_id'] == 2
    asyncio.run(run())


def test_demo_rejects_non_pc_receiver_and_source(monkeypatch):
    async def run():
        setup(monkeypatch)
        service = AsyncMock(); monkeypatch.setattr(demo_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            for device_id, source in [(3, None), (1, 3)]:
                response = await client.post(f'/api/devices/{device_id}/veyon/demonstrations', json={
                    'mode': 'demo-fullscreen', 'confirmed': True, 'source_device_id': source})
                assert response.status_code == 409, response.text
        service.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('method,suffix', [('GET', ''), ('DELETE', ''), ('POST', '/heartbeat'), ('POST', '/frame')])
def test_other_owner_cannot_view_stop_or_upload(monkeypatch, method, suffix):
    async def run():
        setup(monkeypatch)
        service = AsyncMock(return_value=httpx.Response(200, json={'owner': 'user:2', 'classroom_id': 7}))
        monkeypatch.setattr(demo_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            response = await client.request(method, '/api/veyon/demonstrations/session' + suffix)
        assert response.status_code == 403
        assert service.await_count == 1
    asyncio.run(run())


def test_source_requires_independent_classroom_access(monkeypatch):
    async def run():
        setup(monkeypatch)
        monkeypatch.setattr(main, 'get_device_classroom_id', AsyncMock(return_value=8))
        async def access(principal, classroom_id):
            if classroom_id == 8: raise HTTPException(403, 'Access denied')
        monkeypatch.setattr(main, 'ensure_classroom_access', access)
        service = AsyncMock(); monkeypatch.setattr(demo_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            response = await client.post('/api/classrooms/7/veyon/demonstrations', json={
                'mode': 'demo-window', 'confirmed': True, 'source_device_id': 99})
        assert response.status_code == 403
        service.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('scope,target', [('classrooms', 7), ('devices', 2)])
def test_missing_router_demo_address_blocks_dispatch(monkeypatch, scope, target):
    async def run():
        setup(monkeypatch)
        monkeypatch.setattr(main, 'get_router_connection_from_inventory', AsyncMock(return_value={}))
        service = AsyncMock(); monkeypatch.setattr(demo_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            response = await client.post(f'/api/{scope}/{target}/veyon/demonstrations', json={
                'mode': 'demo-window', 'confirmed': True, 'relay_host': 'attacker.local', 'relay_port': 12345})
        assert response.status_code == 409
        service.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('source_host,source_router,expected', [
    ('192.168.1.2', 1, 'https://cmnc.example.local'), ('192.168.2.2', 1, None), ('192.168.1.2', 2, None)])
def test_only_same_router_subnet_uses_direct_probe(monkeypatch, source_host, source_router, expected):
    async def run():
        setup(monkeypatch)
        monkeypatch.setattr(main, 'get_router_connection_from_inventory', AsyncMock(return_value={
            'veyon_demo_host': 'cmnc.example.local', 'veyon_demo_port': 21400, 'veyon_callback_url': 'https://cmnc.example.local'}))
        monkeypatch.setattr(demo_routes, 'authorized_target', AsyncMock(return_value={
            'device_id': 2, 'classroom_id': 8, 'router_id': source_router, 'host': source_host}))
        service = AsyncMock(return_value=httpx.Response(200, json={'id': 'session'}))
        monkeypatch.setattr(demo_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            response = await client.post('/api/classrooms/7/veyon/demonstrations', json={
                'mode': 'demo-window', 'source_device_id': 2, 'confirmed': True})
        assert response.status_code == 200, response.text
        assert service.await_args.args[2]['direct_probe_callback_url'] == expected
    asyncio.run(run())


def test_probe_callback_needs_individual_token_and_strict_boolean(monkeypatch):
    async def run():
        service = AsyncMock(return_value=httpx.Response(200, json={'accepted': True}))
        monkeypatch.setattr(demo_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            path = '/api/veyon/demonstrations/session/probes/2'
            assert (await client.post(path, json={'reachable': True})).status_code == 403
            assert (await client.post(path, headers={'Authorization': 'Bearer ' + 'a' * 32}, json={'reachable': 'yes'})).status_code == 422
            response = await client.post(path, headers={'Authorization': 'Bearer ' + 'a' * 32}, json={'reachable': True})
        assert response.status_code == 200
        assert service.await_count == 1
        assert service.await_args.args[2] == {'device_id': 2, 'token': 'a' * 32, 'reachable': True}
    asyncio.run(run())
