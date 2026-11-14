import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

import pytest
from pydantic import ValidationError
from cmnc_auth_service import main
from cmnc_auth_service.schemas import WorkstationCreateRequest,WorkstationUpdateRequest
from cmnc_contracts.permissions import get_permissions_for_role


@pytest.mark.parametrize("role",["workstation","admin","superadmin","teacher"])
def test_ip_identity_never_inherits_privileges_from_workstation_role_id(monkeypatch,role):
    async def run():
        station=SimpleNamespace(id=1,name="Station",role=SimpleNamespace(name=role),is_active=True)
        result=Mock();result.scalar_one_or_none.return_value=station
        session=AsyncMock();session.execute.return_value=result
        monkeypatch.setattr(main,"touch_workstation_presence",AsyncMock())
        monkeypatch.setattr(main,"get_workstation_classroom_ids",AsyncMock(return_value=[7]))
        principal=await main.resolve_workstation_by_ip("192.168.1.10",session)
        assert principal.principal_type=="workstation"
        assert principal.role=="workstation"
        assert principal.permissions==get_permissions_for_role("workstation")
        assert principal.classroom_ids==[7]
    asyncio.run(run())


@pytest.mark.parametrize("role",["admin","superadmin","teacher","moderator"])
def test_internal_station_payloads_cannot_assign_a_user_role(role):
    with pytest.raises(ValidationError):WorkstationCreateRequest(name="Station",ip_address="192.168.1.10",role=role)
    with pytest.raises(ValidationError):WorkstationUpdateRequest(role=role)
