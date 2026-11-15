import asyncio
from unittest.mock import AsyncMock,Mock
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from cmnc_auth_service import main


@pytest.mark.parametrize("kind",["users","workstations"])
@pytest.mark.parametrize("active",[True,False])
@pytest.mark.parametrize("actor",["admin","superadmin"])
@pytest.mark.parametrize("target_role",["teacher","admin","superadmin"])
def test_delete_requires_inactive_and_respects_role(kind,active,actor,target_role):
    async def run():
        account=SimpleNamespace(id=1,is_active=active,role=SimpleNamespace(name=target_role))
        result=Mock();result.scalar_one_or_none.return_value=account
        session=AsyncMock();session.execute.return_value=result
        forbidden=kind=="users" and target_role in {"admin","superadmin"} and actor!="superadmin"
        if active or forbidden:
            with pytest.raises(HTTPException) as error:
                await main.delete_inactive_account(kind,1,main.AccountDeletionActor(role=actor),session)
            assert error.value.status_code==(403 if forbidden else 409)
            session.commit.assert_not_awaited()
            assert session.execute.await_count==1
        else:
            assert await main.delete_inactive_account(kind,1,main.AccountDeletionActor(role=actor),session)=={"deleted":True}
            session.commit.assert_awaited_once()
            assert session.execute.await_count==2
    asyncio.run(run())
