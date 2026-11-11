import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from cmnc_api_gateway import main as gateway, veyon_routes
from cmnc_api_gateway.schemas import PrincipalResponse


def setup(monkeypatch, role='teacher'):
    principal = PrincipalResponse(principal_type='user', id=1, role=role,
        display_name='Test', classroom_ids=[7], permissions=[])
    layout = {'classroom': {'id': 7, 'router_id': 1, 'subnet_cidr': '192.168.1.0/24'}, 'devices': [
        {'id': 10, 'static_ip': '192.168.1.10', 'veyon_bulk_protected': True},
        {'id': 11, 'static_ip': '192.168.1.11', 'wan_protected': True, 'wol_protected': True},
    ]}
    monkeypatch.setattr(gateway, 'get_current_principal', AsyncMock(return_value=principal))
    monkeypatch.setattr(gateway, 'get_classroom_or_404', AsyncMock(return_value=layout['classroom']))
    monkeypatch.setattr(gateway, 'get_wol_classroom_layout', AsyncMock(return_value=layout))
    return principal, layout


CASES = [
    ('power-down-confirmed', {}), ('power-down-delayed', {'seconds': 3661}),
    ('login', {'username': 'ITTOP\\test', 'password': 'example-only'}), ('logout', {}),
    ('screen-off', {}), ('screen-on', {}), ('message', {'text': 'First\nSecond'}),
    ('website', {'text': 'https://example.com'}), ('command', {'text': 'Get-Date'}),
    ('install-updates-and-power-down', {}),
]


@pytest.mark.parametrize('role', ['teacher', 'moderator', 'workstation', 'admin', 'superadmin'])
@pytest.mark.parametrize('action,extra', CASES)
def test_bulk_actions_permissions_protection_and_confirmation(monkeypatch, role, action, extra):
    async def run():
        principal, layout = setup(monkeypatch, role)
        service = AsyncMock(return_value=httpx.Response(200, json={'accepted': True}))
        monkeypatch.setattr(veyon_routes, 'service_call', service)
        payload = {'action': action, **extra, 'confirmed': True}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://test') as client:
            endpoint = '/api/classrooms/7/veyon/action'
            for unconfirmed in ({k: v for k, v in payload.items() if k != 'confirmed'}, {**payload, 'confirmed': False}):
                assert (await client.post(endpoint, json=unconfirmed)).status_code == 422
            service.assert_not_awaited()
            response = await client.post(endpoint, json=payload)
            if action in {'command', 'install-updates-and-power-down'} and role not in {'admin', 'superadmin'}:
                assert response.status_code == 403
                service.assert_not_awaited()
                return
            assert response.status_code == 200, response.text
            assert response.json() == {'accepted_count': 1, 'failed_count': 0, 'skipped_count': 1,
                'results': [{'device_id': 11, 'accepted': True, 'error': None}]}
            service.assert_awaited_once()
            method, path, forwarded = service.call_args.args
            assert (method, path) == ('POST', '/internal/device/action')
            assert forwarded['device_id'] == 11 and forwarded['action'] == action
            for field, value in extra.items():
                assert forwarded[field] == value
            service.reset_mock()
            layout['devices'] = layout['devices'][:1]
            assert (await client.post(endpoint, json=payload)).json()['accepted_count'] == 0
            service.assert_not_awaited()
            principal.classroom_ids = []
            assert (await client.post(endpoint, json=payload)).status_code == 403
            service.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('extra', [
    {'action': 'message', 'text': ' '}, {'action': 'command', 'text': ''},
    {'action': 'website', 'text': 'file:///C:/test'},
    {'action': 'login', 'username': 'u'}, {'action': 'power-down-delayed', 'seconds': 0},
])
def test_bulk_invalid_input_never_dispatches(monkeypatch, extra):
    async def run():
        setup(monkeypatch, 'admin')
        service = AsyncMock()
        monkeypatch.setattr(veyon_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://test') as client:
            response = await client.post('/api/classrooms/7/veyon/action', json={**extra, 'confirmed': True})
            assert response.status_code == 422
        service.assert_not_awaited()
    asyncio.run(run())


def test_bulk_partial_failure_stays_bounded_and_does_not_retry(monkeypatch):
    async def run():
        _, layout = setup(monkeypatch)
        layout['devices'] += [{'id': i, 'static_ip': f'192.168.1.{i}'} for i in range(12, 24)]
        layout['devices'].append({'id': 99, 'static_ip': '192.168.2.99'})
        active = peak = 0
        calls = []
        async def service(method, path, payload):
            nonlocal active, peak
            calls.append(payload['device_id'])
            active += 1
            peak = max(active, peak)
            try:
                await asyncio.sleep(.005)
                if payload['device_id'] == 12:
                    raise TimeoutError()
                if payload['device_id'] == 13:
                    raise gateway.HTTPException(503, 'Veyon unavailable')
                return httpx.Response(200, json={'accepted': True})
            finally:
                active -= 1
        monkeypatch.setattr(veyon_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://test') as client:
            response = await client.post('/api/classrooms/7/veyon/action', json={'action': 'screen-on', 'confirmed': True})
        assert response.status_code == 200
        result = response.json()
        assert result['accepted_count'] == 11
        assert result['failed_count'] == 3
        assert result['skipped_count'] == 1
        assert peak == 4
        assert len(calls) == len(set(calls)) == 13
        assert not {10, 99} & set(calls)
    asyncio.run(run())
