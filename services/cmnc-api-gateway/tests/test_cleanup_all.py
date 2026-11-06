import asyncio
from unittest.mock import AsyncMock

import httpx

from cmnc_api_gateway import main
from cmnc_api_gateway.schemas import PrincipalResponse


def principal(permissions):
    return PrincipalResponse(principal_type='user', id=1, role='admin', display_name='Test', classroom_ids=[], permissions=permissions)


def test_cleanup_all_filters_devices_and_checks_permissions(monkeypatch):
    async def run():
        auth = AsyncMock(return_value=principal(['devices:manage']))
        layout = AsyncMock(return_value=(
            {'id': 7, 'router_id': 42, 'subnet_cidr': '192.168.1.0/24'},
            [{'mac_address': 'AA:BB:CC:DD:EE:FF'}],
            [
                {'id': 1, 'mac_address': 'aa:bb:cc:dd:ee:ff', 'active_ip': '192.168.1.1', 'active': True},
                {'id': 2, 'mac_address': '00:00:00:00:00:02', 'active_ip': '192.168.1.2', 'active': True},
                {'id': 3, 'mac_address': '00:00:00:00:00:03', 'active_ip': '192.168.1.3', 'active': False},
                {'id': 4, 'mac_address': '00:00:00:00:00:04', 'active_ip': '192.168.2.4'},
                {'id': 5, 'mac_address': '00:00:00:00:00:05', 'active_ip': None},
            ],
        ))
        delete = AsyncMock(return_value={'deleted_ids': [2, 3], 'deleted_count': 2})
        monkeypatch.setattr(main, 'get_current_principal', auth)
        monkeypatch.setattr(main, 'get_classroom_layout_and_observed_devices', layout)
        monkeypatch.setattr(main.inventory_client, 'post_json', delete)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            response = await client.post('/api/admin/classrooms/7/observed-devices/cleanup-all')
            assert response.status_code == 200
            assert response.json()['deleted_ids'] == [2, 3]
            layout.assert_awaited_once_with(7)
            delete.assert_awaited_once_with('/internal/routers/42/observed-devices/delete', json={'ids': [2, 3]})

            delete.reset_mock()
            layout.return_value = ({'id': 7, 'router_id': 42, 'subnet_cidr': '192.168.1.0/24'}, [], [])
            response = await client.post('/api/admin/classrooms/7/observed-devices/cleanup-all')
            assert response.json() == {'deleted_ids': [], 'deleted_count': 0}
            delete.assert_not_awaited()

            auth.return_value = principal([])
            layout.reset_mock()
            response = await client.post('/api/admin/classrooms/7/observed-devices/cleanup-all')
            assert response.status_code == 403
            layout.assert_not_awaited()
            delete.assert_not_awaited()
    asyncio.run(run())
