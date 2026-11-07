import asyncio
from unittest.mock import AsyncMock

import httpx
from cmnc_api_gateway import main as gateway, veyon_routes
from cmnc_api_gateway.schemas import PrincipalResponse


def test_bulk_protection_skips_only_classroom_veyon_actions(monkeypatch):
    async def run():
        principal = PrincipalResponse(principal_type='user', id=1, role='teacher', display_name='Teacher', classroom_ids=[7], permissions=[])
        layout = {'classroom': {'id': 7, 'router_id': 1, 'subnet_cidr': '192.168.1.0/24'}, 'devices': [
            {'id': 10, 'static_ip': '192.168.1.10', 'veyon_bulk_protected': True},
            {'id': 11, 'static_ip': '192.168.1.11', 'veyon_bulk_protected': False},
            {'id': 12, 'static_ip': '192.168.1.12', 'wan_protected': True},
        ]}
        monkeypatch.setattr(gateway, 'get_current_principal', AsyncMock(return_value=principal))
        monkeypatch.setattr(gateway, 'get_device_classroom_id', AsyncMock(return_value=7))
        monkeypatch.setattr(gateway, 'get_wol_classroom_layout', AsyncMock(return_value=layout))
        monkeypatch.setattr(gateway, 'get_classroom_or_404', AsyncMock(return_value=layout['classroom']))
        calls = []
        async def service(method, path, payload=None):
            calls.append((path, payload))
            if path.endswith('/frame'):
                return httpx.Response(200, content=b'frame', headers={'content-type': 'image/jpeg'})
            return httpx.Response(200, json={'accepted': True})
        monkeypatch.setattr(veyon_routes, 'service_call', service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://test') as client:
            response = await client.post('/api/classrooms/7/veyon/power-down-all', json={'confirmed': True})
            assert response.status_code == 200
            assert response.json()['accepted_count'] == 2
            assert response.json()['skipped_count'] == 1
            assert {payload['device_id'] for _, payload in calls} == {11, 12}
            calls.clear()
            assert (await client.post('/api/devices/10/veyon/power-down')).status_code == 200
            assert (await client.post('/api/devices/10/veyon/reboot')).status_code == 200
            assert (await client.get('/api/devices/10/veyon/frame')).content == b'frame'
            assert all(payload['device_id'] == 10 for _, payload in calls)
            layout['devices'] = layout['devices'][:1]
            calls.clear()
            result = (await client.post('/api/classrooms/7/veyon/power-down-all', json={'confirmed': True})).json()
            assert result == {'accepted_count': 0, 'failed_count': 0, 'skipped_count': 1, 'results': []}
            assert calls == []
    asyncio.run(run())
