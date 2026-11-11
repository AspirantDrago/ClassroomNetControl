import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from cmnc_api_gateway import main as gateway, veyon_routes
from cmnc_api_gateway.schemas import PrincipalResponse


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    monkeypatch.setattr(veyon_routes, "_configuration_cache", {})
    monkeypatch.setattr(veyon_routes, "_configuration_locks", {})


@pytest.mark.parametrize("role", ["teacher", "admin", "superadmin", "workstation"])
@pytest.mark.parametrize("router_key,classroom_key", [(False, False), (False, True), (True, False), (True, True)])
def test_effective_configuration_is_visible_without_exposing_keys(monkeypatch, role, router_key, classroom_key):
    async def run():
        principal = PrincipalResponse(principal_type="user", id=1, role=role,
            display_name="Test", classroom_ids=[7], permissions=[])
        monkeypatch.setattr(gateway, "get_current_principal", AsyncMock(return_value=principal))
        monkeypatch.setattr(gateway, "get_classroom_or_404", AsyncMock(return_value={"id": 7}))
        monkeypatch.setattr(gateway, "get_wol_classroom_layout", AsyncMock(return_value={
            "classroom": {"id": 7, "router_id": 2}, "devices": []}))
        async def service(method, path):
            assert method == "GET"
            return httpx.Response(200, json={"configured": router_key if "/router/" in path else classroom_key,
                "key_name": "not-for-viewers"})
        service_mock = AsyncMock(side_effect=service)
        monkeypatch.setattr(veyon_routes, "service_call", service_mock)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            response = await client.get("/api/classrooms/7/veyon/status")
            assert response.status_code == 200
            assert response.json() == {"configured": router_key or classroom_key}
            assert [call.args[1] for call in service_mock.await_args_list] == (
                ["/internal/keys/router/2"] if router_key else ["/internal/keys/router/2", "/internal/keys/classroom/7"])
            service_mock.reset_mock()
            principal.classroom_ids = []
            assert (await client.get("/api/classrooms/7/veyon/status")).status_code == 403
            service_mock.assert_not_awaited()
    asyncio.run(run())


def test_hour_cache_expiry_and_single_flight(monkeypatch):
    from types import SimpleNamespace
    now = [100.0]
    monkeypatch.setattr(veyon_routes, "time", SimpleNamespace(monotonic=lambda: now[0]))
    classroom = {"id": 7, "router_id": 2}
    async def service(*args):
        await asyncio.sleep(0)
        return httpx.Response(200, json={"configured": True})
    service_mock = AsyncMock(side_effect=service)
    monkeypatch.setattr(veyon_routes, "service_call", service_mock)
    async def run():
        assert veyon_routes.cached_veyon_configuration(classroom) == {
            "veyon_configured": False, "veyon_configuration_stale": True}
        assert all(await asyncio.gather(*(veyon_routes.classroom_veyon_configured(classroom) for _ in range(30))))
        assert service_mock.await_count == 1
        assert veyon_routes.cached_veyon_configuration(classroom) == {
            "veyon_configured": True, "veyon_configuration_stale": False}
        now[0] += 3599
        assert await veyon_routes.classroom_veyon_configured(classroom)
        assert service_mock.await_count == 1
        now[0] += 1
        assert veyon_routes.cached_veyon_configuration(classroom)["veyon_configuration_stale"]
        assert await veyon_routes.classroom_veyon_configured(classroom)
        assert service_mock.await_count == 2
    asyncio.run(run())


@pytest.mark.parametrize("scope", ["router", "classroom"])
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_key_changes_invalidate_cached_false_and_true(monkeypatch, scope, method):
    async def run():
        monkeypatch.setattr(veyon_routes, "check_key_admin", AsyncMock())
        service = AsyncMock(return_value=httpx.Response(200, json={"configured": True}))
        monkeypatch.setattr(veyon_routes, "service_call", service)
        classroom = {"id": 7, "router_id": 2}
        await veyon_routes.classroom_veyon_configured(classroom)
        veyon_routes._configuration_cache[(3, 8)] = (float("inf"), False)
        assert len(veyon_routes._configuration_cache) == 2
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            response = await client.request(method, f"/api/admin/veyon/keys/{scope}/7",
                **({"json": {"key_name": "CMNC", "private_key": "test-only"}} if method == "PUT" else {}))
        assert response.status_code == 200
        assert not veyon_routes._configuration_cache
        assert veyon_routes.cached_veyon_configuration(classroom)["veyon_configuration_stale"]
    asyncio.run(run())


def test_failed_check_is_not_cached_as_missing_key(monkeypatch):
    async def run():
        service = AsyncMock(side_effect=gateway.HTTPException(503, "unavailable"))
        monkeypatch.setattr(veyon_routes, "service_call", service)
        classroom = {"id": 7, "router_id": 2}
        with pytest.raises(gateway.HTTPException):
            await veyon_routes.classroom_veyon_configured(classroom)
        assert veyon_routes.cached_veyon_configuration(classroom)["veyon_configuration_stale"]
        assert not veyon_routes._configuration_cache
    asyncio.run(run())
