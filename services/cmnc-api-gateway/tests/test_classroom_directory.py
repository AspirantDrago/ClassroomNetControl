import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
from cmnc_api_gateway import main as gateway
from cmnc_api_gateway.schemas import PrincipalResponse


@pytest.mark.parametrize("permission", ["users:manage:admin", "users:manage:lower", "workstations:manage"])
@pytest.mark.parametrize("all_classrooms", [False, True])
def test_directory_includes_inactive_names_and_only_permitted_metadata(monkeypatch, permission, all_classrooms):
    async def run():
        principal = PrincipalResponse(principal_type="user", id=1, role="moderator", display_name="Test",
            classroom_ids=[4], permissions=[permission]+(["classrooms:read:all"] if all_classrooms else []))
        monkeypatch.setattr(gateway, "get_current_principal", AsyncMock(return_value=principal))
        rooms = [{"id": 4, "name": "РПО", "is_active": False, "subnet_cidr": "192.168.1.0/24", "rtsp_main_stream": "not-public"},
                 {"id": 5, "name": "Photoshop", "is_active": True},
                 {"id": 6, "name": "Service", "is_active": True, "is_service": True}]
        get_json = AsyncMock(return_value=rooms)
        monkeypatch.setattr(gateway.classroom_client, "get_json", get_json)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            response = await client.get("/api/admin/classrooms/directory")
        assert response.status_code == 200
        expected = [{"id": 4, "name": "РПО", "is_active": False}]
        if all_classrooms: expected.append({"id": 5, "name": "Photoshop", "is_active": True})
        assert response.json() == expected
        get_json.assert_awaited_once_with("/internal/classrooms?include_inactive=true")
    asyncio.run(run())


def test_directory_requires_access_management_permission(monkeypatch):
    async def run():
        principal = PrincipalResponse(principal_type="user", id=1, role="teacher", display_name="Test",
            classroom_ids=[4], permissions=["classrooms:read:all"])
        monkeypatch.setattr(gateway, "get_current_principal", AsyncMock(return_value=principal))
        get_json = AsyncMock()
        monkeypatch.setattr(gateway.classroom_client, "get_json", get_json)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            assert (await client.get("/api/admin/classrooms/directory")).status_code == 403
        get_json.assert_not_awaited()
    asyncio.run(run())


def test_administrators_can_resolve_inactive_service_classrooms(monkeypatch):
    async def run():
        principal = PrincipalResponse(principal_type="user", id=1, role="admin", display_name="Test", classroom_ids=[],
            permissions=["classrooms:read:all", "users:manage:admin"])
        monkeypatch.setattr(gateway, "get_current_principal", AsyncMock(return_value=principal))
        monkeypatch.setattr(gateway.classroom_client, "get_json", AsyncMock(return_value=[
            {"id": 1, "name": "Service", "is_active": False, "is_service": True}]))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            assert (await client.get("/api/admin/classrooms/directory")).json() == [{"id": 1, "name": "Service", "is_active": False}]
    asyncio.run(run())
