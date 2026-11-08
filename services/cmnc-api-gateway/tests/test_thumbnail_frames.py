import asyncio
from unittest.mock import AsyncMock
import httpx
from cmnc_api_gateway import main as gateway, veyon_routes
from cmnc_api_gateway.schemas import PrincipalResponse


def test_thumbnail_width_and_access(monkeypatch):
    async def run():
        principal=PrincipalResponse(principal_type='user',id=1,role='teacher',display_name='Teacher',classroom_ids=[7],permissions=[])
        classroom={'id':7,'router_id':1,'subnet_cidr':'192.168.1.0/24'}
        monkeypatch.setattr(gateway,'get_current_principal',AsyncMock(return_value=principal))
        monkeypatch.setattr(gateway,'get_device_classroom_id',AsyncMock(return_value=7))
        monkeypatch.setattr(gateway,'get_classroom_or_404',AsyncMock(return_value=classroom))
        monkeypatch.setattr(gateway,'get_wol_classroom_layout',AsyncMock(return_value={'classroom':classroom,'devices':[{'id':10,'static_ip':'192.168.1.10'}]}))
        calls=[]
        async def service(method,path,payload):
            calls.append(payload)
            return httpx.Response(200,content=b'image',headers={'content-type':'image/jpeg'})
        monkeypatch.setattr(veyon_routes,'service_call',service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://test') as client:
            response=await client.get('/api/devices/10/veyon/frame?width=320')
            assert response.status_code==200
            assert response.headers['cache-control']=='no-store'
            assert calls[-1]['width']==320
            assert calls[-1]['host']=='192.168.1.10'
            assert (await client.get('/api/devices/10/veyon/frame')).status_code==200
            assert calls[-1]['width']==1280
            before=len(calls)
            for width in ['0','-1','100000','NaN']:
                assert (await client.get('/api/devices/10/veyon/frame?width='+width)).status_code==422
            assert len(calls)==before
            principal.classroom_ids=[]
            assert (await client.get('/api/devices/10/veyon/frame?width=320')).status_code==403
            assert len(calls)==before
    asyncio.run(run())
