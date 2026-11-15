import asyncio
from unittest.mock import AsyncMock
import pytest,httpx
from cmnc_api_gateway import main,veyon_routes
from cmnc_api_gateway.schemas import PrincipalResponse


def layout():
    base=dict(classroom_id=7,router_id=1,static_ip="192.168.1.10",is_pinned=True)
    return {"classroom":{"id":7,"router_id":1,"subnet_cidr":"192.168.1.0/24"},"devices":[{**base,"id":1},{**base,"id":2,"is_non_pc":True},{**base,"id":3,"veyon_bulk_protected":True}]}


def test_non_pc_not_sent_or_counted_in_bulk_results(monkeypatch):
    async def run():
        service=AsyncMock(return_value=httpx.Response(200,json={"accepted":True}))
        monkeypatch.setattr(veyon_routes,"service_call",service)
        result=await veyon_routes.dispatch_classroom_action(layout(),"power-down")
        assert result["accepted_count"]==1 and result["skipped_count"]==1
        assert [r["device_id"] for r in result["results"]]==[1]
        assert service.await_count==1
    asyncio.run(run())


@pytest.mark.parametrize("method,path,payload",[("GET","frame",None),("GET","snapshot",None),("POST","refresh",None),("POST","power-down",None),("POST","action",{"action":"message","text":"Hello"}),("POST","control/start",{}),("POST","shortcut/escape",{})])
def test_non_pc_rejects_direct_veyon_requests(monkeypatch,method,path,payload):
    async def run():
        actor=PrincipalResponse(principal_type="user",id=1,role="teacher",display_name="Test",classroom_ids=[7],permissions=[])
        monkeypatch.setattr(main,"get_current_principal",AsyncMock(return_value=actor))
        monkeypatch.setattr(main,"get_device_classroom_id",AsyncMock(return_value=7))
        monkeypatch.setattr(main,"ensure_classroom_access",AsyncMock())
        monkeypatch.setattr(main,"get_wol_classroom_layout",AsyncMock(return_value=layout()))
        service=AsyncMock();monkeypatch.setattr(veyon_routes,"service_call",service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url="http://test") as client:
            response=await client.request(method,"/api/devices/2/veyon/"+path,**({"json":payload} if payload is not None else {}))
        assert response.status_code==409,response.text
        service.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("flag",[True,False])
def test_flag_change_notifies_scheduler_after_commit_without_delaying_response(monkeypatch,flag):
    async def run():
        actor=PrincipalResponse(principal_type="user",id=1,role="admin",display_name="Test",classroom_ids=[],permissions=["devices:manage"])
        monkeypatch.setattr(main,"get_current_principal",AsyncMock(return_value=actor))
        update=AsyncMock(return_value={"id":2,"is_non_pc":flag});monkeypatch.setattr(main.classroom_client,"patch_json",update)
        notify=AsyncMock();monkeypatch.setattr(main,"refresh_veyon_user_schedule",notify)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url="http://test") as client:
            response=await client.patch("/api/admin/devices/2",json={"is_non_pc":flag})
        assert response.status_code==200
        update.assert_awaited_once();notify.assert_awaited_once()
    asyncio.run(run())
