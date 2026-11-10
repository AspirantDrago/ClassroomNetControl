import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from cmnc_inventory_service.models import Router, ObservedDevice
from cmnc_inventory_service import dhcp_handlers
from cmnc_contracts.events import DhcpLeasesObservedEvent,DhcpLeaseObserved

@compiles(JSONB,'sqlite')
def jsonb_sqlite(type_,compiler,**kw): return 'JSON'

class Message:
    def __init__(self,event):self.body=event.model_dump_json().encode()
    @asynccontextmanager
    async def process(self,**kwargs):yield

def test_empty_and_old_snapshots_use_persistent_router_watermark(monkeypatch):
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///:memory:');maker=async_sessionmaker(engine,expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(lambda sync:Router.metadata.create_all(sync,tables=[Router.__table__,ObservedDevice.__table__]))
            async with maker() as session:
                for id in (1,2):session.add(Router(id=id,name=f'Router{id}',api_host='test',api_port=443,api_username='test',api_password='fixture'))
                await session.commit()
            monkeypatch.setattr(dhcp_handlers,'async_session_maker',maker)
            start=datetime(2026,11,10,tzinfo=timezone.utc)
            def event(router,seconds,leases):return Message(DhcpLeasesObservedEvent(router_id=router,occurred_at=start+timedelta(seconds=seconds),leases=leases))
            lease=DhcpLeaseObserved(mac='00:11:22:33:44:55',active_ip='192.168.1.2',hostname='PC',active=True,dynamic=False,raw={})
            await dhcp_handlers.handle_dhcp_leases_observed(event(1,0,[lease]))
            await dhcp_handlers.handle_dhcp_leases_observed(event(2,0,[lease]))
            await dhcp_handlers.handle_dhcp_leases_observed(event(1,10,[]))
            # Empty snapshot must deactivate router1 only; older/equal messages cannot revive it.
            await dhcp_handlers.handle_dhcp_leases_observed(event(1,5,[lease]))
            await dhcp_handlers.handle_dhcp_leases_observed(event(1,10,[lease]))
            from sqlalchemy import select
            async with maker() as session:
                devices=(await session.execute(select(ObservedDevice).order_by(ObservedDevice.router_id))).scalars().all()
                assert [device.active for device in devices]==[False,True]
                router=await session.get(Router,1)
                assert router.dhcp_snapshot_at.replace(tzinfo=timezone.utc)==start+timedelta(seconds=10)
            # Later observations refresh state and remain protected after a new DB session.
            await dhcp_handlers.handle_dhcp_leases_observed(event(1,20,[lease]))
            async with maker() as session:
                device=(await session.execute(select(ObservedDevice).where(ObservedDevice.router_id==1))).scalar_one()
                assert device.active
                assert device.last_seen_at.replace(tzinfo=timezone.utc)==start+timedelta(seconds=20)
        finally: await engine.dispose()
    asyncio.run(run())

def test_watermark_migration_preserves_rows():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine,text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).parents[1]/'migrations/versions/20261110_0005_add_dhcp_snapshot_watermark.py'
    spec=importlib.util.spec_from_file_location('watermark_migration',path);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE routers (id INTEGER PRIMARY KEY)'))
        connection.execute(text('INSERT INTO routers(id) VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text('SELECT dhcp_snapshot_at FROM routers WHERE id=1')).scalar() is None
            migration.downgrade()
        assert connection.execute(text('SELECT count(*) FROM routers')).scalar()==1
