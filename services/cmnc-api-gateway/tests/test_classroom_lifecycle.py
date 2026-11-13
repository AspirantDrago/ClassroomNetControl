import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
from cmnc_api_gateway import main as gateway
from cmnc_api_gateway.schemas import PrincipalResponse


@pytest.mark.parametrize("permission", [True, False])
@pytest.mark.parametrize("confirmed", [True, False, None])
def test_delete_requires_permission_and_confirmation(monkeypatch, permission, confirmed):
    async def run():
        principal = PrincipalResponse(principal_type="user", id=1, role="admin" if permission else "teacher",
            display_name="Test", classroom_ids=[], permissions=["classrooms:manage"] if permission else [])
        monkeypatch.setattr(gateway, "get_current_principal", AsyncMock(return_value=principal))
        delete = AsyncMock(return_value={"deleted": True})
        monkeypatch.setattr(gateway.auth_client, "delete_json", delete)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            response = await client.request("DELETE", "/api/admin/classrooms/7", json={} if confirmed is None else {"confirmed": confirmed})
        expected = 422 if confirmed is not True else 200 if permission else 403
        assert response.status_code == expected
        if expected == 200:
            delete.assert_awaited_once_with("/internal/admin/classrooms/7")
        else:
            delete.assert_not_awaited()
    asyncio.run(run())


def test_dependency_error_is_readable(monkeypatch):
    async def run():
        principal = PrincipalResponse(principal_type="user", id=1, role="admin", display_name="Test",
            classroom_ids=[], permissions=["classrooms:manage"])
        monkeypatch.setattr(gateway, "get_current_principal", AsyncMock(return_value=principal))
        request = httpx.Request("DELETE", "http://auth/internal/admin/classrooms/7")
        response = httpx.Response(409, json={"detail": "Сначала удалите назначения доступа"}, request=request)
        monkeypatch.setattr(gateway.auth_client, "delete_json", AsyncMock(side_effect=httpx.HTTPStatusError("Conflict", request=request, response=response)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            result = await client.request("DELETE", "/api/admin/classrooms/7", json={"confirmed": True})
        assert result.status_code == 409
        assert result.json() == {"detail": "Сначала удалите назначения доступа"}
    asyncio.run(run())


@pytest.mark.parametrize("active", [True, False, None])
def test_only_activation_uses_authorization_coordinator(monkeypatch, active):
    async def run():
        principal = PrincipalResponse(principal_type="user", id=1, role="admin", display_name="Test",
            classroom_ids=[], permissions=["classrooms:manage"])
        monkeypatch.setattr(gateway, "get_current_principal", AsyncMock(return_value=principal))
        auth = AsyncMock(return_value={"id": 7})
        classroom = AsyncMock(return_value={"id": 7})
        monkeypatch.setattr(gateway.auth_client, "patch_json", auth)
        monkeypatch.setattr(gateway.classroom_client, "patch_json", classroom)
        payload = {"name": "Updated"} if active is None else {"is_active": active}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            response = await client.patch("/api/admin/classrooms/7", json=payload)
        assert response.status_code == 200
        (auth if active is True else classroom).assert_awaited_once()
        (classroom if active is True else auth).assert_not_awaited()
    asyncio.run(run())
