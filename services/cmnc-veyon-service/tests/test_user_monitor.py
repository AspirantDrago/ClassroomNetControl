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
