import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace
from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import AsyncSession,create_async_engine
from cmnc_classroom_service.db import Base
from cmnc_classroom_service import api,user_history,device_statistics
from cmnc_classroom_service.models import Classroom,Device
from cmnc_classroom_service.schemas import DeviceCreate,DeviceUpdate


def test_non_pc_is_persisted_forces_protection_and_is_excluded_from_user_and_bulk_wan():
    async def run():
        engine=create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as c:await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(engine,expire_on_commit=False) as s:
                s.add(Classroom(id=1,name="Room",subnet_cidr="192.168.1.0/24"));await s.commit()
                device=await api.create_device(DeviceCreate(classroom_id=1,inventory_name="TV",mac_address="00:11:22:33:44:55",static_ip="192.168.1.10",is_non_pc=True),s)
                assert device.is_non_pc and device.veyon_bulk_protected
                updated=await api.update_device(device.id,DeviceUpdate(veyon_bulk_protected=False),SimpleNamespace(),s)
                assert updated.is_non_pc and updated.veyon_bulk_protected
                assert await user_history.user_targets(s)==[]
                result=await api.set_classroom_wan_state(session=s,rabbitmq_client=SimpleNamespace(publish_event=AsyncMock()),classroom_id=1,wan_allowed=False)
                assert result.affected_count==0
                assert (await s.get(Device,device.id)).wan_allowed
                stats=await device_statistics.get_classroom_statistics(1,40,s)
                assert stats.devices[0].is_non_pc and stats.devices[0].users==[]
                await api.update_device(device.id,DeviceUpdate(is_non_pc=False),SimpleNamespace(),s)
                assert not (await s.get(Device,device.id)).is_non_pc
        finally:await engine.dispose()
    asyncio.run(run())


def test_non_pc_migration_defaults_existing_devices_to_false():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine,text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).parents[1]/"migrations/versions/20261115_0012_add_non_pc.py"
    spec=importlib.util.spec_from_file_location("non_pc_migration",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as c:
            c.execute(text("CREATE TABLE devices (id INTEGER PRIMARY KEY)"))
            c.execute(text("INSERT INTO devices VALUES (1)"))
            with Operations.context(MigrationContext.configure(c)):
                migration.upgrade()
                assert c.execute(text("SELECT is_non_pc FROM devices WHERE id=1")).scalar()==0
                c.execute(text("INSERT INTO devices(id) VALUES (2)"))
                assert c.execute(text("SELECT is_non_pc FROM devices WHERE id=2")).scalar()==0
                migration.downgrade()
            assert c.execute(text("SELECT count(*) FROM devices")).scalar()==2
    finally:engine.dispose()


def test_dhcp_statistics_event_accepts_devices_with_non_pc_flag():
    from datetime import datetime,timezone
    from cmnc_classroom_service.device_statistics import record_device_statistics_state
    from cmnc_classroom_service.models import DeviceStatisticsEvent
    from sqlalchemy import select
    async def run():
        engine=create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as c:await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(engine,expire_on_commit=False) as s:
                s.add(Classroom(id=1,name="Room",subnet_cidr="192.168.1.0/24"));await s.flush()
                d=Device(classroom_id=1,inventory_name="PC",mac_address="00:11:22:33:44:55")
                s.add(d);await s.flush()
                assert await record_device_statistics_state(s,d,occurred_at=datetime.now(timezone.utc),online=True)
                await s.commit()
                assert (await s.execute(select(DeviceStatisticsEvent))).scalar_one().online
        finally:await engine.dispose()
    asyncio.run(run())
