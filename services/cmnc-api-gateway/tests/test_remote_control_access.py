import asyncio
from unittest.mock import AsyncMock
import httpx
from cmnc_api_gateway import main as gateway, veyon_routes
from cmnc_api_gateway.schemas import PrincipalResponse


def test_remote_control_checks_access_and_uses_server_owned_target(monkeypatch):
    async def run():
        principal=PrincipalResponse(principal_type='user',id=1,role='teacher',display_name='Teacher',classroom_ids=[7],permissions=[])
        classroom={'id':7,'router_id':1,'subnet_cidr':'192.168.1.0/24'}
        monkeypatch.setattr(gateway,'get_current_principal',AsyncMock(return_value=principal))
        monkeypatch.setattr(gateway,'get_device_classroom_id',AsyncMock(return_value=7))
        monkeypatch.setattr(gateway,'get_classroom_or_404',AsyncMock(return_value=classroom))
        monkeypatch.setattr(gateway,'get_wol_classroom_layout',AsyncMock(return_value={'classroom':classroom,'devices':[{'id':10,'static_ip':'192.168.1.10','veyon_bulk_protected':True}]}))
        calls=[]
        async def call(method,path,payload):
            calls.append((path,payload))
            return httpx.Response(200,json={'token':'test-token','accepted':True})
        monkeypatch.setattr(veyon_routes,'service_call',call)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://test') as client:
            for action in ['start','input','stop']:
                response=await client.post('/api/devices/10/veyon/control/'+action,json={'token':'test-token','host':'192.168.1.99','owner':'user:999','device_id':99})
                assert response.status_code==200
                assert calls[-1][1]['host']=='192.168.1.10'
                assert calls[-1][1]['owner']=='user:1'
                assert calls[-1][1]['device_id']==10
            principal.classroom_ids=[]
            calls.clear()
            for action in ['start','input','stop']:
                assert (await client.post('/api/devices/10/veyon/control/'+action,json={})).status_code==403
            assert calls==[]
    asyncio.run(run())
