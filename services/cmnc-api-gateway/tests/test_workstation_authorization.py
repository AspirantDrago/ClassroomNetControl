"""Workstations cannot use account/admin APIs, even with inconsistent role data."""
import asyncio
import re
from unittest.mock import AsyncMock

import httpx
import pytest

from cmnc_api_gateway import main as gateway, veyon_routes, command_routes
from cmnc_api_gateway.schemas import PrincipalResponse
from cmnc_contracts.permissions import ROLE_PERMISSIONS


ADMIN_ROUTES = [(method,route.path) for route in gateway.app.routes
    if getattr(route,"path","").startswith("/api/admin/")
    for method in getattr(route,"methods",set()) if method not in {"HEAD","OPTIONS"}]


def workstation(role="workstation"):
    return PrincipalResponse(principal_type="workstation",id=1,role=role,display_name="Station",
        classroom_ids=[7],permissions=sorted(set().union(*ROLE_PERMISSIONS.values())))


def forbid_upstream(monkeypatch):
    denied=AsyncMock(side_effect=AssertionError("Forbidden request reached an internal service"))
    for name in ("auth_client","classroom_client","inventory_client","maintenance_client","camera_client","poller_client","policy_sync_client"):
        client=getattr(gateway,name)
        for method in ("get_json","post_json","patch_json","delete_json","post_file","get_bytes"):
            monkeypatch.setattr(client,method,denied)
    monkeypatch.setattr(veyon_routes,"service_call",denied)
    monkeypatch.setattr(command_routes,"service_call",denied)
    return denied


@pytest.mark.parametrize("role",["workstation","admin","superadmin"])
@pytest.mark.parametrize("method,path",ADMIN_ROUTES)
def test_every_admin_route_rejects_workstation_before_upstream(monkeypatch,role,method,path):
    async def run():
        monkeypatch.setattr(gateway,"get_current_principal",AsyncMock(return_value=workstation(role)))
        upstream=forbid_upstream(monkeypatch)
        url=re.sub(r"\{([^}]+)\}",lambda match:"classroom" if match[1]=="scope" else "1",path)
        payload=dict(confirmed=True,private_key="test-key",key_name="CMNC",role="teacher",username="probe",password="test-password",display_name="Test",
            name="Test",ip_address="192.168.1.10",router_id=1,subnet_cidr="192.168.1.0/24",mac_address="00:11:22:33:44:55",observed_device_id=1)
        kwargs={"files":{"file":("test.backup",b"test","application/octet-stream")}} if method=="POST" and path.endswith("/backups/database") else {"json":payload} if method not in {"GET","HEAD"} else {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url="http://test") as client:
            response=await client.request(method,url,**kwargs)
        assert response.status_code==403,(method,path,response.text)
        upstream.assert_not_awaited()
    asyncio.run(run())


PRIVILEGED = [
    ("PATCH","/api/me",{"display_name":"User with colliding ID","password":"new-password"}),
    ("GET","/api/classrooms?include_inactive=true",None),
    ("POST","/api/devices/1/veyon/action",{"action":"command","text":"echo test"}),
    ("POST","/api/devices/1/veyon/action",{"action":"install-updates-and-power-down"}),
    ("POST","/api/classrooms/7/veyon/action",{"action":"command","text":"echo test","confirmed":True}),
    ("POST","/api/classrooms/7/veyon/install-updates-and-power-down-all",{"confirmed":True}),
    ("POST","/api/devices/1/veyon/shortcut/ctrl-alt-delete",{}),
    ("POST","/api/devices/1/veyon/command-with-output",{"confirmed":True,"command":"echo test"}),
    ("POST","/api/classrooms/7/veyon/command-with-output",{"confirmed":True,"command":"echo test"}),
    ("GET","/api/veyon/command-jobs/test-job",None),
    ("GET","/api/veyon/command-scripts/test-job/1",None),
    ("POST","/api/veyon/command-results/test-job/1",{}),
]


@pytest.mark.parametrize("role",["workstation","admin","superadmin"])
@pytest.mark.parametrize("method,path,payload",PRIVILEGED)
def test_account_and_privileged_veyon_routes_require_user_identity(monkeypatch,role,method,path,payload):
    async def run():
        monkeypatch.setattr(gateway,"get_current_principal",AsyncMock(return_value=workstation(role)))
        upstream=forbid_upstream(monkeypatch)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url="http://test") as client:
            response=await client.request(method,path,**({"json":payload} if payload is not None else {}))
        assert response.status_code==403,response.text
        upstream.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("role",["workstation","admin","superadmin"])
def test_workstation_is_limited_to_assigned_classrooms_even_with_all_permissions(monkeypatch,role):
    async def run():
        principal=workstation(role)
        monkeypatch.setattr(gateway,"get_current_principal",AsyncMock(return_value=principal))
        rooms=[dict(id=7,router_id=1,name="Assigned",is_active=True,is_service=False),dict(id=8,router_id=1,name="Other",is_active=True,is_service=False),dict(id=9,router_id=1,name="Service",is_active=True,is_service=True)]
        async def get_json(path):
            if path=="/internal/classrooms":return rooms
            return next(r for r in rooms if path.endswith("/"+str(r["id"])))
        monkeypatch.setattr(gateway.classroom_client,"get_json",get_json)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url="http://test") as client:
            response=await client.get("/api/classrooms")
            assert response.status_code==200
            assert [r["id"] for r in response.json()]==[7]
            for path in ("/api/classrooms/8/dashboard","/api/classrooms/8/wan/block-all","/api/classrooms/8/wake-all"):
                response=await client.request("GET" if path.endswith("dashboard") else "POST",path)
                assert response.status_code==403,response.text
            assert (await client.get("/api/classrooms/9/dashboard")).status_code==404
        await gateway.ensure_classroom_access(principal,7)
        gateway.require_wan_control_permission(principal)
    asyncio.run(run())
