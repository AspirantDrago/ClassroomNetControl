import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from cmnc_classroom_service import api
from cmnc_classroom_service.db import Base
from cmnc_classroom_service.models import Classroom
from cmnc_classroom_service.schemas import ClassroomUpdate


def test_inactive_classrooms_can_be_listed_and_reactivated():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                session.add_all([Classroom(id=1, name="Active", subnet_cidr="192.168.1.0/24", is_active=True),
                    Classroom(id=2, name="Inactive", subnet_cidr="192.168.2.0/24", is_active=False)])
                await session.commit()
                assert [room.id for room in await api.get_classrooms(session)] == [1]
                assert [room.id for room in await api.get_classrooms(session, True)] == [1, 2]
                restored = await api.update_classroom(2, ClassroomUpdate(is_active=True), session)
                assert restored.is_active
                assert [room.id for room in await api.get_classrooms(session)] == [1, 2]
        finally:
            await engine.dispose()
    asyncio.run(run())
