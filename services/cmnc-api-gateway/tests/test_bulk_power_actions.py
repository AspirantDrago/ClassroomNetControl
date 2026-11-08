import asyncio
from unittest.mock import AsyncMock
import pytest
import httpx
from cmnc_api_gateway import main as gateway, veyon_routes
from cmnc_api_gateway.schemas import PrincipalResponse


@pytest.mark.parametrize('role',['teacher','workstation','moderator','admin','superadmin'])
@pytest.mark.parametrize('action',['power-down','reboot','install-updates-and-power-down'])
def test_bulk_power_roles_confirmation_access_and_protection(monkeypatch,role,action):
    async def run():
        principal=PrincipalResponse(principal_type='user',id=1,role=role,display_name='Test',classroom_ids=[7],permissions=[])
        classroom={'id':7,'router_id':1,'subnet_cidr':'192.168.1.0/24'}
        devices=[{'id':10,'static_ip':'192.168.1.10','veyon_bulk_protected':True},{'id':11,'static_ip':'192.168.1.11','wan_protected':True,'wol_protected':True}]
        layout={'classroom':classroom,'devices':devices}
        monkeypatch.setattr(gateway,'get_current_principal',AsyncMock(return_value=principal))
        monkeypatch.setattr(gateway,'get_classroom_or_404',AsyncMock(return_value=classroom))
        monkeypatch.setattr(gateway,'get_wol_classroom_layout',AsyncMock(return_value=layout))
        calls=[]
        async def service(method,path,payload):
            calls.append(payload)
            return httpx.Response(200,json={'accepted':True})
        monkeypatch.setattr(veyon_routes,'service_call',service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://test') as client:
            path=f'/api/classrooms/7/veyon/{action}-all'
            assert (await client.post(path,json={'confirmed':False})).status_code==422
            assert calls==[]
            response=await client.post(path,json={'confirmed':True})
            if action=='install-updates-and-power-down' and role not in {'admin','superadmin'}:
                assert response.status_code==403
                assert calls==[]
                return
            assert response.status_code==200,response.text
            assert response.json()['accepted_count']==1
            assert response.json()['skipped_count']==1
            assert [item['device_id'] for item in calls]==[11]
            assert calls[0]['action']==action
            calls.clear()
            layout['devices']=devices[:1]
            assert (await client.post(path,json={'confirmed':True})).json()['accepted_count']==0
            assert calls==[]
            principal.classroom_ids=[]
            assert (await client.post(path,json={'confirmed':True})).status_code==403
            assert calls==[]
            assert (await client.post('/api/devices/10/veyon/install-updates-and-power-down')).status_code==422
            assert calls==[]
    asyncio.run(run())
