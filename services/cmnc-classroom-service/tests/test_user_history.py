import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from cmnc_classroom_service.db import Base
from cmnc_classroom_service.models import Classroom, Device, DeviceStatisticsState, DeviceUserInterval, DeviceUserState
from cmnc_classroom_service import user_history as history, device_statistics as statistics, api


async def setup_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine


async def seed(session):
    session.add(Classroom(id=1, router_id=1, name="Room", subnet_cidr="192.168.1.0/24", is_active=True))
    await session.flush()
    session.add(Device(id=1, classroom_id=1, inventory_name="PC", mac_address="00:11:22:33:44:55", static_ip="192.168.1.10", is_pinned=True))
    await session.flush()
    session.add(DeviceStatisticsState(device_id=1, online=True, wan_state="allowed", observed_at=datetime.now(timezone.utc)))
    await session.commit()


def observation(at, known=True, username="ivanov_an", **changes):
    return history.UserObservation(**{**dict(device_id=1, classroom_id=1, router_id=1, host="192.168.1.10", known=known, username=username, observed_at=at), **changes})


def test_user_history_tracks_changes_logout_unknown_gaps_and_monotonicity():
    async def run():
        engine = await setup_database()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await seed(session)
                base = datetime.now(timezone.utc) - timedelta(minutes=10)
                for offset, known, username in [(0,True,"ivanov_an"),(30,True,"ivanov_an"),(60,True,"petrov"),(90,True,None),(100,False,None),(200,True,"ivanov_an")]:
                    await history.record_user(session, observation(base+timedelta(seconds=offset),known,username),90)
                    await session.flush()
                await history.record_user(session, observation(base+timedelta(seconds=170),True,"out-of-order"),90)
                await session.commit()
                intervals = (await session.execute(select(DeviceUserInterval).order_by(DeviceUserInterval.id))).scalars().all()
                assert [(i.username, round((history.utc(i.start_at)-base).total_seconds()),round((history.utc(i.end_at)-base).total_seconds())) for i in intervals] == [
                    ("ivanov_an",0,60),("petrov",60,90),(None,90,100),("ivanov_an",200,290)]
                result = await statistics.get_classroom_statistics(1,40,session)
                assert [i.state for i in result.devices[0].users] == ["user_present","user_present","user_absent","user_present"]
                assert result.devices[0].users[0].username == "ivanov_an"
                assert (await history.current_users(session,[1]))[1] == {"current_user_known":False,"current_user":None}
                # Expiry creates a gap even when the same username is observed again.
                await history.record_user(session, observation(base+timedelta(seconds=400)),90)
                await session.flush()
                assert len((await session.execute(select(DeviceUserInterval))).scalars().all()) == 5
        finally:
            await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("username", ["ivanov_an", "", None])
def test_current_user_distinguishes_logged_out_from_unknown_and_is_in_layout(username):
    async def run():
        engine = await setup_database()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await seed(session)
                await history.record_user(session, observation(datetime.now(timezone.utc),True,username),90)
                await session.commit()
                user = (await api.get_classroom_layout(1,session)).device_users[1]
                assert user.current_user_known is True
                assert user.current_user == (username or None)
        finally: await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("reason", ["offline", "stale_online", "wrong_host", "wrong_classroom", "wrong_router", "unpinned", "inactive", "future", "error"])
def test_missing_or_inapplicable_data_does_not_become_logged_out(reason):
    async def run():
        engine = await setup_database()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await seed(session)
                now=datetime.now(timezone.utc)
                changes={}
                if reason == "offline": (await session.get(DeviceStatisticsState,1)).online=False
                elif reason == "stale_online": (await session.get(DeviceStatisticsState,1)).observed_at=now-timedelta(minutes=5)
                elif reason == "wrong_host": changes["host"]="192.168.1.20"
                elif reason == "wrong_classroom": changes["classroom_id"]=2
                elif reason == "wrong_router": changes["router_id"]=2
                elif reason == "unpinned": (await session.get(Device,1)).is_pinned=False
                elif reason == "inactive": (await session.get(Classroom,1)).is_active=False
                elif reason == "future": now += timedelta(minutes=1)
                await history.record_user(session,observation(now,reason != "error",None,**changes),90)
                await session.commit()
                assert (await session.execute(select(DeviceUserInterval.id))).first() is None
                assert not (await history.current_users(session,[1])).get(1,{}).get("current_user_known",False)
        finally: await engine.dispose()
    asyncio.run(run())


def test_target_selection_uses_online_freshness_but_returns_offline_to_clear_cache():
    async def run():
        engine=await setup_database()
        try:
            async with AsyncSession(engine,expire_on_commit=False) as session:
                await seed(session)
                assert (await history.user_targets(session))[0]["online"] is True
                (await session.get(DeviceStatisticsState,1)).observed_at=datetime.now(timezone.utc)-timedelta(minutes=5)
                await session.flush()
                assert (await history.user_targets(session))[0]["online"] is False
                (await session.get(Classroom,1)).is_active=False
                await session.flush()
                assert await history.user_targets(session) == []
        finally: await engine.dispose()
    asyncio.run(run())


def test_user_history_migration_preserves_devices_and_cascades():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine,text
    path=Path(__file__).parents[1]/"migrations/versions/20261115_0011_add_device_user_history.py"
    spec=importlib.util.spec_from_file_location("user_history_migration",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.execute(text("CREATE TABLE devices(id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO devices VALUES(1)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                connection.execute(text("INSERT INTO device_user_intervals(device_id,start_at,end_at,username) VALUES(1,'2026-11-15','2026-11-16','user')"))
                connection.execute(text("DELETE FROM devices WHERE id=1"))
                assert connection.execute(text("SELECT count(*) FROM device_user_intervals")).scalar()==0
                migration.downgrade()
    finally: engine.dispose()


def test_background_monitor_persists_history_through_internal_http_api(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from cmnc_classroom_service.main import app
    from cmnc_classroom_service.db import get_session
    from cmnc_veyon_service.main import Target
    from cmnc_veyon_service.user_monitor import UserMonitor
    async def run():
        engine=await setup_database()
        factory=async_sessionmaker(engine,expire_on_commit=False)
        async def sessions():
            async with factory() as session: yield session
        app.dependency_overrides[get_session]=sessions
        try:
            async with factory() as session: await seed(session)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://classrooms") as client:
                monitor=UserMonitor(SimpleNamespace(read_user=AsyncMock(return_value={"username":"ivanov_an"})),Target,client)
                monitor.base_url="http://classrooms"
                await monitor.poll_once()
                layout=(await client.get("/internal/classrooms/1/layout")).json()
                assert layout["device_users"]["1"]=={"current_user_known":True,"current_user":"ivanov_an"}
            async with factory() as session:
                result=await statistics.get_classroom_statistics(1,40,session)
                assert result.devices[0].users[0].username=="ivanov_an"
        finally:
            app.dependency_overrides.pop(get_session,None)
            await engine.dispose()
    asyncio.run(run())
