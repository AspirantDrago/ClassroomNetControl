import asyncio
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import pytest
from cmnc_classroom_service.db import Base
from cmnc_classroom_service.models import Classroom, Device
from cmnc_classroom_service import api, policy_sync_handlers as handlers
from cmnc_contracts.events import PolicySyncCompletedEvent, PolicySyncFailedEvent

class Message:
    def __init__(self,event): self.body=event.model_dump_json().encode()
    @asynccontextmanager
    async def process(self, **kwargs): yield

@pytest.mark.parametrize('failed',[False,True])
def test_result_matches_router_and_exact_device_snapshot(monkeypatch,failed):
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        maker=async_sessionmaker(engine,expire_on_commit=False)
        try:
            async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
            async with maker() as session:
                session.add_all([Classroom(id=1,router_id=1,name='A',subnet_cidr='192.168.1.0/24'),Classroom(id=2,router_id=2,name='B',subnet_cidr='192.168.2.0/24')])
                for id,room,generation in [(1,1,100),(2,1,2),(3,2,1),(4,1,1)]:
                    session.add(Device(id=id,classroom_id=room,inventory_name=f'PC-{id}',mac_address=f'00:00:00:00:00:{id:02}',static_ip=f'192.168.{room}.{id}',is_pinned=True,wan_allowed=id==2,policy_generation=generation,sync_status='pending'))
                await session.commit()
                snapshot=await api.get_desired_blocklist(1,session)
                assert snapshot.device_generations=={1:100,2:2,4:1}
                assert {item.device_id for item in snapshot.blocked}=={1,4}
                # A low-counter device changes after a high aggregate was read.
                (await session.get(Device,2)).policy_generation=3
                await session.commit()
            monkeypatch.setattr(handlers,'async_session_maker',maker)
            cls=PolicySyncFailedEvent if failed else PolicySyncCompletedEvent
            fields={'error':'test failure'} if failed else {}
            # An unrelated device and an absent device must not be acknowledged.
            event=cls(router_id=1,policy_generation=1000,device_generations={1:100,2:2,3:1},**fields)
            handler=handlers.handle_policy_sync_failed if failed else handlers.handle_policy_sync_completed
            await handler(Message(event))
            await handler(Message(event))  # redelivery is harmless
            async with maker() as session:
                assert (await session.get(Device,1)).sync_status==('failed' if failed else 'applied')
                for id in (2,3,4): assert (await session.get(Device,id)).sync_status=='pending'
                # A device moving to another router cannot be updated by its old router.
                item=await session.get(Device,4);item.classroom_id=2;await session.commit()
            await handler(Message(cls(router_id=1,policy_generation=1000,device_generations={4:1},**fields)))
            async with maker() as session: assert (await session.get(Device,4)).sync_status=='pending'
        finally: await engine.dispose()
    asyncio.run(run())

def test_legacy_results_cannot_update_status(monkeypatch):
    from unittest.mock import Mock
    maker=Mock(side_effect=AssertionError('Legacy event must not write the database'))
    monkeypatch.setattr(handlers,'async_session_maker',maker)
    async def run():
        await handlers.handle_policy_sync_completed(Message(PolicySyncCompletedEvent(router_id=1,policy_generation=9999)))
        await handlers.handle_policy_sync_failed(Message(PolicySyncFailedEvent(router_id=1,policy_generation=9999,error='old')))
    asyncio.run(run())
    maker.assert_not_called()
