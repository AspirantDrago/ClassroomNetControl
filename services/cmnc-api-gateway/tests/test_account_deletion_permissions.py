import asyncio
from unittest.mock import AsyncMock
import pytest,httpx
from cmnc_api_gateway import main
from cmnc_api_gateway.schemas import PrincipalResponse
from cmnc_contracts.permissions import get_permissions_for_role


@pytest.mark.parametrize("role",["workstation","teacher","moderator","admin","superadmin"])
@pytest.mark.parametrize("kind",["users","workstations"])
def test_account_deletion_is_admin_only(monkeypatch,role,kind):
    async def run():
        p=PrincipalResponse(principal_type="workstation" if role=="workstation" else "user",id=1,role=role,display_name="Actor",classroom_ids=[],permissions=get_permissions_for_role(role))
        monkeypatch.setattr(main,"get_current_principal",AsyncMock(return_value=p))
        upstream=AsyncMock(return_value={"deleted":True});monkeypatch.setattr(main.auth_client,"post_json",upstream)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url="http://test") as c:
            response=await c.request("DELETE",f"/api/admin/{kind}/2",json={"confirmed":True,"role":"superadmin"})
        assert response.status_code==(200 if role in {"admin","superadmin"} else 403)
        if role in {"admin","superadmin"}:upstream.assert_awaited_once_with(f"/internal/admin/{kind}/2/delete",json={"role":role})
        else:upstream.assert_not_awaited()
    asyncio.run(run())


def test_admin_cannot_manage_other_admin_even_with_extra_permissions():
    p=PrincipalResponse(principal_type="user",id=1,role="admin",display_name="Actor",classroom_ids=[],permissions=get_permissions_for_role("superadmin"))
    for role in ("admin","superadmin"):
        with pytest.raises(main.HTTPException): main.require_user_role_management(p,role)
