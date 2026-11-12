import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
from cmnc_api_gateway import main as gateway, command_routes
from cmnc_api_gateway.schemas import PrincipalResponse


def setup(monkeypatch, role="admin"):
    principal = PrincipalResponse(principal_type="user", id=1, role=role, display_name="Test", classroom_ids=[7], permissions=[])
    layout = {"classroom": {"id": 7, "router_id": 2, "subnet_cidr": "192.168.1.0/24"}, "devices": [
        {"id": 10, "static_ip": "192.168.1.10", "inventory_name": "Protected", "veyon_bulk_protected": True},
        {"id": 11, "static_ip": "192.168.1.11", "inventory_name": "PC", "wan_protected": True, "wol_protected": True}]}
    monkeypatch.setattr(gateway, "get_current_principal", AsyncMock(return_value=principal))
    monkeypatch.setattr(gateway, "get_classroom_or_404", AsyncMock(return_value=layout["classroom"]))
    monkeypatch.setattr(gateway, "get_device_classroom_id", AsyncMock(return_value=7))
    monkeypatch.setattr(gateway, "get_wol_classroom_layout", AsyncMock(return_value=layout))
    router = {"veyon_callback_url": "https://cmnc.example.test"}
    monkeypatch.setattr(gateway, "get_router_connection_from_inventory", AsyncMock(return_value=router))
    return principal, router


@pytest.mark.parametrize("role", ["admin", "superadmin", "teacher", "moderator", "workstation"])
@pytest.mark.parametrize("endpoint", ["/api/devices/10", "/api/classrooms/7"])
def test_output_command_is_separate_admin_only_and_respects_bulk_protection(monkeypatch, role, endpoint):
    async def run():
        principal, router = setup(monkeypatch, role)
        service = AsyncMock(return_value=httpx.Response(200, json={"id": "job", "owner": "user:1"}))
        monkeypatch.setattr(command_routes, "service_call", service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            path = endpoint+"/veyon/command-with-output"
            assert (await client.post(path, json={"command": "Get-Date"})).status_code == 422
            result = await client.post(path, json={"command": "Get-Date", "confirmed": True})
            if role not in {"admin", "superadmin"}:
                assert result.status_code == 403
                service.assert_not_awaited(); return
            assert result.status_code == 200 and result.json() == {"id": "job"}
            forwarded = service.call_args.args[2]
            assert forwarded["owner"] == "user:1" and forwarded["callback_url"] == router["veyon_callback_url"]
            assert [t["device_id"] for t in forwarded["targets"]] == ([10] if "devices" in endpoint else [11])
            assert forwarded["skipped_count"] == (0 if "devices" in endpoint else 1)
            service.reset_mock()
            principal.classroom_ids = []
            assert (await client.post(path, json={"command": "Get-Date", "confirmed": True})).status_code == 403
            service.assert_not_awaited()
    asyncio.run(run())


def test_missing_loopback_does_not_dispatch(monkeypatch):
    async def run():
        _, router = setup(monkeypatch)
        router["veyon_callback_url"] = None
        service = AsyncMock()
        monkeypatch.setattr(command_routes, "service_call", service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            assert (await client.post("/api/classrooms/7/veyon/command-with-output", json={"command": "Get-Date", "confirmed": True})).status_code == 409
        service.assert_not_awaited()
    asyncio.run(run())


def test_job_results_require_owner_and_classroom_access(monkeypatch):
    async def run():
        principal, _ = setup(monkeypatch)
        job = {"owner": "user:2", "classroom_id": 7, "id": "job"}
        service = AsyncMock(side_effect=lambda *args: httpx.Response(200, json=job))
        monkeypatch.setattr(command_routes, "service_call", service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            assert (await client.get("/api/veyon/command-jobs/job")).status_code == 403
            job["owner"] = "user:1"
            response = await client.get("/api/veyon/command-jobs/job")
            assert response.status_code == 200 and "owner" not in response.json()
            assert response.headers["cache-control"] == "no-store"
            principal.classroom_ids = []
            assert (await client.get("/api/veyon/command-jobs/job")).status_code == 403
    asyncio.run(run())


def test_public_callbacks_require_token_and_enforce_body_size(monkeypatch):
    async def run():
        service = AsyncMock(return_value=httpx.Response(200, json={"accepted": True}))
        monkeypatch.setattr(command_routes, "service_call", service)
        path = "/api/veyon/command-results/job/10"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            assert (await client.post(path, json={})).status_code == 403
            service.assert_not_awaited()
            headers = {"Authorization": "Bearer "+"test-only-token-"*3}
            assert (await client.post(path, headers=headers, content=b"x"*1048577)).status_code == 413
            service.assert_not_awaited()
            assert (await client.post(path, headers=headers, json=[])).status_code == 422
            assert (await client.post(path, headers=headers, json={"stdout": "Привет", "device_id": 99, "job_id": "other", "token": "other"})).status_code == 200
            payload = service.call_args.args[2]
            assert payload["device_id"] == 10 and payload["job_id"] == "job" and payload["token"] == headers["Authorization"][7:]
    asyncio.run(run())


def test_command_output_round_trip_through_gateway_and_service(monkeypatch, tmp_path):
    import base64
    import re
    from types import SimpleNamespace
    from cryptography.fernet import Fernet
    from cmnc_veyon_service import main as service_main
    from cmnc_veyon_service.command_jobs import CommandJobs
    async def run():
        setup(monkeypatch)
        launched = []
        async def operate(target, action, arguments):
            encoded = arguments["applications"][0].split("-EncodedCommand ", 1)[1]
            script = base64.b64decode(encoded).decode("utf-16-le")
            launched.append((target.device_id, re.search(r"Bearer ([A-Za-z0-9_-]+)", script).group(1)))
        bridge = SimpleNamespace(store=SimpleNamespace(cipher=Fernet(Fernet.generate_key())), operate=operate)
        manager = CommandJobs(tmp_path, bridge, service_main.Target)
        monkeypatch.setattr(service_main.app.state, "command_jobs", manager, raising=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service_main.app)) as internal:
            monkeypatch.setattr(gateway.app.state, "veyon_http", internal, raising=False)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
                started = await client.post("/api/classrooms/7/veyon/command-with-output", json={"command": "Get-Date", "confirmed": True})
                assert started.status_code == 200, started.text
                job = started.json()
                assert job["skipped_count"] == 1 and "owner" not in job
                await asyncio.gather(*list(manager.tasks))
                assert [d for d, token in launched] == [11]
                token = launched[0][1]
                headers = {"Authorization": "Bearer "+token}
                path = f"/api/veyon/command-scripts/{job['id']}/11"
                script = await client.get(path, headers=headers)
                assert script.status_code == 200 and script.headers["cache-control"] == "no-store"
                assert "__COMMAND__" not in script.text and "GetTempPath" in script.text
                callback = f"/api/veyon/command-results/{job['id']}/11"
                response = await client.post(callback, headers=headers, json={"stdout": "Привет", "stderr": "", "exit_code": 0})
                assert response.status_code == 200, response.text
                assert (await client.post(callback, headers=headers, json={"stdout": "forged"})).status_code == 403
                result = await client.get(f"/api/veyon/command-jobs/{job['id']}")
                assert result.status_code == 200 and result.json()["finished"]
                assert result.json()["results"][0]["stdout"] == "Привет"
                assert result.json()["results"][0]["exit_code"] == 0
        await manager.close()
    asyncio.run(run())
