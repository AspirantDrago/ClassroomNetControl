import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from cmnc_classroom_service import api
from cmnc_classroom_service.db import Base
from cmnc_classroom_service.models import Classroom, ClassroomCamera, Device


@pytest.mark.parametrize("dependency", [None, "pinned", "unpinned", "camera", "disabled_camera", "active", "missing", "stale_token", "auth_unavailable"])
def test_delete_only_empty_inactive_classrooms(monkeypatch, dependency):
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        verify = AsyncMock()
        if dependency in ("stale_token", "auth_unavailable"):
            verify.side_effect = HTTPException(409 if dependency == "stale_token" else 503, "Denied")
        monkeypatch.setattr(api, "verify_deletion_token", verify)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                if dependency != "missing":
                    session.add(Classroom(id=1, name="Empty", subnet_cidr="192.168.1.0/24", is_active=dependency == "active"))
                    await session.commit()
                if dependency in ("pinned", "unpinned"):
                    session.add(Device(classroom_id=1, mac_address="00:11:22:33:44:55", inventory_name="PC-01", is_pinned=dependency == "pinned"))
                if dependency in ("camera", "disabled_camera"):
                    session.add(ClassroomCamera(classroom_id=1, name="Camera", is_enabled=dependency == "camera"))
                await session.commit()
                if dependency is None:
                    assert await api.delete_classroom(1, api.ClassroomDeletionRequest(token="test-token"), session) == {"deleted": True}
                    assert (await session.execute(select(Classroom.id))).first() is None
                    verify.assert_awaited_once_with(1, "test-token")
                else:
                    with pytest.raises(HTTPException) as error:
                        await api.delete_classroom(1, api.ClassroomDeletionRequest(token="test-token"), session)
                    assert error.value.status_code == (404 if dependency == "missing" else 503 if dependency == "auth_unavailable" else 409)
                    assert bool((await session.execute(select(Classroom.id))).first()) == (dependency != "missing")
                    if dependency not in ("stale_token", "auth_unavailable"):
                        verify.assert_not_awaited()
                    if dependency in ("pinned", "unpinned"):
                        assert (await session.execute(select(Device.id))).first()
                    if dependency in ("camera", "disabled_camera"):
                        assert (await session.execute(select(ClassroomCamera.id))).first()
        finally:
            await engine.dispose()
    asyncio.run(run())
