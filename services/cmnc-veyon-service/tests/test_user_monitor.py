import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from cmnc_veyon_service import main
from cmnc_veyon_service.user_monitor import UserMonitor


def target():
    return dict(device_id=1,router_id=1,classroom_id=1,host="192.168.1.10")


@pytest.mark.parametrize("login", ["ivanov_an", "", None, 0])
@pytest.mark.parametrize("existing", [True, False])
def test_user_query_uses_authenticated_session_and_releases_only_monitor_connections(monkeypatch,login,existing):
    async def run():
        bridge=main.VeyonBridge(SimpleNamespace(resolve=lambda *args:("name","pem")),None)
        t=main.Target(**target());identity=bridge.identity(t)[0]
        session=SimpleNamespace(uid="uid")
        if existing: bridge.sessions[identity]=session
        bridge.connection=AsyncMock(return_value=session)
        bridge.checked=AsyncMock(side_effect=lambda method,path,**kwargs:httpx.Response(200,json={"sessionId":1} if path.endswith("/session") else {"login":login}))
        bridge.close=AsyncMock()
        monkeypatch.setattr(main.asyncio,"sleep",AsyncMock())
        if isinstance(login,str):
            assert await bridge.read_user(t)=={"username":login or None}
        else:
            with pytest.raises(HTTPException): await bridge.read_user(t)
        assert bridge.checked.await_args.kwargs["headers"]=={"Connection-Uid":"uid"}
        assert bridge.close.await_count == int(not existing)
    asyncio.run(run())


@pytest.mark.parametrize("state", ["logged_in","logged_out","offline","missing_key","timeout"])
def test_monitor_distinguishes_missing_user_from_unknown(state):
    async def run():
        bridge=SimpleNamespace(read_user=AsyncMock(return_value={"username":"ivanov_an" if state=="logged_in" else None}))
        if state in ("missing_key","timeout"): bridge.read_user.side_effect=HTTPException(409 if state=="missing_key" else 504,"Unavailable")
        monitor=UserMonitor(bridge,main.Target,None)
        result=await monitor.observe({**target(),"online":state!="offline"})
        assert result["known"] == (state in ("logged_in","logged_out"))
        assert result["username"] == ("ivanov_an" if state=="logged_in" else None)
        assert bridge.read_user.await_count==int(state!="offline")
    asyncio.run(run())


def test_poll_concurrency_is_bounded_and_observations_are_published(monkeypatch):
    async def run():
        active=peak=0
        async def read(t):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            await asyncio.sleep(.005)
            active-=1
            return {"username":f"user-{t.device_id}"}
        monkeypatch.setenv("CMNC_VEYON_USER_POLL_CONCURRENCY","2")
        rows=[{**target(),"device_id":i,"online":True} for i in range(1,9)]
        def handle(request):
            assert request.url.path.endswith("/user-targets")
            return httpx.Response(200,json=rows)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monitor=UserMonitor(SimpleNamespace(read_user=read),main.Target,client)
            monitor.publish=AsyncMock()
            await monitor.poll_once()
            assert peak==2
            observations=[item for call in monitor.publish.await_args_list for item in call.args[0]]
            assert {item["device_id"] for item in observations}==set(range(1,9))
            assert all(item["known"] for item in observations)
    asyncio.run(run())


@pytest.mark.parametrize("session_id", [-1,None,"0",False])
def test_initializing_session_is_not_reported_as_logged_out(session_id):
    async def run():
        bridge=main.VeyonBridge(SimpleNamespace(resolve=lambda *args:("name","pem")),None)
        t=main.Target(**target());identity=bridge.identity(t)[0]
        session=SimpleNamespace(uid="uid")
        bridge.sessions[identity]=session
        bridge.connection=AsyncMock(return_value=session)
        bridge.checked=AsyncMock(side_effect=lambda method,path,**kwargs:httpx.Response(200,json={"sessionId":session_id} if path.endswith("/session") else {"login":""}))
        with pytest.raises(HTTPException): await bridge.read_user(t)
    asyncio.run(run())


def test_independent_schedule_keeps_fast_target_running_while_slow_target_waits():
    from cmnc_veyon_service.user_monitor import ScheduledTarget
    import time
    async def run():
        monitor=UserMonitor(None,main.Target,None)
        monitor.interval=.02
        monitor.targets_refreshed_at=time.monotonic()
        slow_started=asyncio.Event();release=asyncio.Event();fast_repeated=asyncio.Event()
        fast_calls=0;active={};peak={};published=[]
        async def observe(row):
            nonlocal fast_calls
            id=row["device_id"]
            active[id]=active.get(id,0)+1;peak[id]=max(peak.get(id,0),active[id])
            try:
                if id==2:
                    slow_started.set();await release.wait()
                else:
                    fast_calls+=1
                    if fast_calls>=3:fast_repeated.set()
                return {**row,"known":True,"username":"user"}
            finally:active[id]-=1
        monitor.observe=observe
        monitor.publish=AsyncMock(side_effect=lambda rows:published.extend(rows))
        for id in (1,2):
            monitor.targets[id]=ScheduledTarget({**target(),"device_id":id,"online":True},time.monotonic())
        tasks=[asyncio.create_task(monitor.worker()) for _ in range(2)]
        try:
            await asyncio.wait_for(slow_started.wait(),1)
            await asyncio.wait_for(fast_repeated.wait(),1)
            assert not release.is_set()
            assert len([r for r in published if r["device_id"]==1])>=2
            assert max(peak.values())==1
        finally:
            release.set()
            for t in tasks:t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    asyncio.run(run())


def test_failed_target_backs_off_and_key_change_resets_schedule():
    from cmnc_veyon_service.user_monitor import ScheduledTarget
    import time
    async def run():
        monitor=UserMonitor(None,main.Target,None)
        monitor.targets_refreshed_at=time.monotonic()
        entry=ScheduledTarget({**target(),"online":True},time.monotonic())
        monitor.targets[1]=entry
        monitor.observe=AsyncMock(return_value={**target(),"known":False,"username":None})
        monitor.publish=AsyncMock()
        task=asyncio.create_task(monitor.worker())
        try:
            for _ in range(100):
                if entry.failures:break
                await asyncio.sleep(.001)
            assert entry.failures==1
            assert entry.due-time.monotonic()>50
            await monitor.invalidate_keys("classroom",1)
            assert entry.failures==0 and entry.due<=time.monotonic()
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())


def test_changed_target_discards_inflight_result_and_readded_id_does_not_overlap():
    from cmnc_veyon_service.user_monitor import ScheduledTarget
    import time
    async def run():
        monitor=UserMonitor(None,main.Target,None)
        monitor.targets_refreshed_at=time.monotonic()
        started=asyncio.Event();release=asyncio.Event()
        async def observe(row):
            started.set();await release.wait();return {**row,"known":True}
        monitor.observe=observe;monitor.publish=AsyncMock()
        monitor.targets[1]=ScheduledTarget(target(),time.monotonic())
        tasks=[asyncio.create_task(monitor.worker()) for _ in range(2)]
        try:
            await asyncio.wait_for(started.wait(),1)
            new=ScheduledTarget({**target(),"host":"192.168.1.20"},time.monotonic())
            monitor.targets[1]=new
            async with monitor.changed:monitor.changed.notify_all()
            await asyncio.sleep(.02)
            assert not new.busy
            for t in tasks:t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            monitor.publish.assert_not_awaited()
        finally:
            for t in tasks:t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    asyncio.run(run())


def test_non_pc_removal_cancels_observation_releases_slot_and_readd_starts_immediately():
    async def run():
        rows=[{**target(),"online":True}]
        started=asyncio.Event();released=asyncio.Event();saved=asyncio.Event()
        calls=0
        async def observe(row):
            nonlocal calls
            calls+=1
            if calls==1:
                started.set()
                try:await asyncio.Event().wait()
                finally:released.set()
            return {**row,"known":True,"username":"user"}
        async def publish(rows):saved.set()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=rows))) as client:
            monitor=UserMonitor(None,main.Target,client)
            monitor.observe=observe;monitor.publish=publish
            await monitor.refresh_targets()
            task=asyncio.create_task(monitor.worker())
            try:
                await asyncio.wait_for(started.wait(),1)
                rows=[]
                await monitor.refresh_targets()
                await asyncio.wait_for(released.wait(),1)
                for _ in range(100):
                    if not monitor.running_ids:break
                    await asyncio.sleep(.001)
                assert not monitor.targets and not monitor.running_ids and not monitor.observation_tasks
                assert not task.done()
                rows=[{**target(),"online":True}]
                await monitor.refresh_targets()
                await asyncio.wait_for(saved.wait(),1)
                assert calls==2
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())


def test_proxy_restart_invalidates_cached_uid():
    async def run():
        bridge=main.VeyonBridge(SimpleNamespace(resolve=lambda *args:("name","pem")),None)
        t=main.Target(**target());identity=bridge.identity(t)[0]
        bridge.sessions[identity]=SimpleNamespace(uid="old")
        bridge.connection=AsyncMock(return_value=bridge.sessions[identity])
        bridge.checked=AsyncMock(side_effect=main.VeyonError(502,"Invalid connection",2))
        bridge.close=AsyncMock(side_effect=lambda i:bridge.sessions.pop(i,None))
        with pytest.raises(main.VeyonError):await bridge.read_user(t)
        assert identity not in bridge.sessions
    asyncio.run(run())
