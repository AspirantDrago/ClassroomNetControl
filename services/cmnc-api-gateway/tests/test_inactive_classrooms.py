import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
from cmnc_api_gateway import main as gateway
from cmnc_api_gateway.schemas import PrincipalResponse


@pytest.mark.parametrize("role", ["admin", "superadmin", "teacher", "moderator", "workstation"])
def test_inactive_classrooms_are_opt_in_and_admin_only(monkeypatch, role):
    async def run():
        principal = PrincipalResponse(principal_type="user", id=1, role=role, display_name="Test",
            classroom_ids=[7], permissions=["classrooms:read:all"])
        monkeypatch.setattr(gateway, "get_current_principal", AsyncMock(return_value=principal))
        room = {"id": 7, "name": "Room", "router_id": 1, "is_active": False}
        get_json = AsyncMock(return_value=[room])
        monkeypatch.setattr(gateway.classroom_client, "get_json", get_json)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            assert (await client.get("/api/classrooms")).status_code == 200
            get_json.assert_awaited_once_with("/internal/classrooms")
            get_json.reset_mock()
            response = await client.get("/api/classrooms?include_inactive=true")
            if role in {"admin", "superadmin"}:
                assert response.status_code == 200
                assert response.json()[0]["id"] == 7
                get_json.assert_awaited_once_with("/internal/classrooms?include_inactive=true")
            else:
                assert response.status_code == 403
                get_json.assert_not_awaited()
    asyncio.run(run())
