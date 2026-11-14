import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
from cmnc_api_gateway import main as gateway
from cmnc_api_gateway.schemas import PrincipalResponse


@pytest.mark.parametrize("online,known",[(True,True),(True,False),(False,True)])
def test_current_user_is_returned_with_dashboard_and_hidden_when_unknown_or_offline(monkeypatch,online,known):
    async def run():
        principal=PrincipalResponse(principal_type="user",id=1,role="teacher",display_name="Teacher",classroom_ids=[1],permissions=["classrooms:read:all"])
        monkeypatch.setattr(gateway,"get_current_principal",AsyncMock(return_value=principal))
        room=dict(id=1,router_id=1,name="Room",subnet_cidr="192.168.1.0/24",vlan_id=1,display_order=1,is_active=True,is_service=False)
        device=dict(id=1,classroom_id=1,mac_address="00:11:22:33:44:55",inventory_name="PC",hostname="PC",static_ip="192.168.1.10",row_index=1,column_index=1,is_pinned=True,wan_allowed=True,wan_protected=False,policy_generation=0,sync_status="applied",sync_error=None)
        async def get_json(path):
            if path.endswith("/layout"):return {"classroom":room,"devices":[device],"cameras":[],"device_users":{"1":{"current_user_known":known,"current_user":"ivanov_an"}}}
            return room
        monkeypatch.setattr(gateway.classroom_client,"get_json",get_json)
        monkeypatch.setattr(gateway.inventory_client,"get_json",AsyncMock(return_value={"devices":[{"mac_address":device["mac_address"],"active":online,"active_ip":device["static_ip"],"hostname":"PC","last_seen_at":None}]}))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url="http://test") as client:
            response=await client.get("/api/classrooms/1/dashboard")
        assert response.status_code==200,response.text
        result=response.json()["devices"][0]
        assert result["current_user_known"] == (online and known)
        assert result["current_user"] == ("ivanov_an" if online and known else None)
    asyncio.run(run())
