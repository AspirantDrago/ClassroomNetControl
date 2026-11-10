import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from cmnc_contracts.events import DhcpLeaseObserved
from cmnc_mikrotik_poller_service import main
from cmnc_mikrotik_poller_service.inventory_client import InventoryClient, RouterConnection
from cmnc_mikrotik_poller_service.mikrotik_client import MikroTikClient


def router():
    return RouterConnection(1,'test','127.0.0.1',80,False,False,'test','test',True,True,True,10)


def test_concurrent_worker_and_manual_polls_share_one_read_and_publish():
    async def run():
        main._poll_flights.clear()
        ready=asyncio.Event(); release=asyncio.Event()
        async def read(): ready.set();await release.wait();return []
        clients=[SimpleNamespace(get_dhcp_leases=AsyncMock(side_effect=read)) for _ in range(12)]
        rabbit=SimpleNamespace(publish_event=AsyncMock())
        tasks=[asyncio.create_task(main.poll_once(router=router(),mikrotik_client=client,rabbitmq_client=rabbit)) for client in clients]
        await ready.wait();await asyncio.sleep(0)
        assert sum(client.get_dhcp_leases.await_count for client in clients)==1
        release.set();results=await asyncio.gather(*tasks)
        assert all(result['snapshot_published'] for result in results)
        rabbit.publish_event.assert_awaited_once()
        assert rabbit.publish_event.call_args.kwargs['event'].leases==[]
        assert not main._poll_flights
    asyncio.run(run())


def test_cancelled_caller_does_not_abort_other_snapshot_waiters():
    async def run():
        main._poll_flights.clear();ready=asyncio.Event();release=asyncio.Event()
        async def read(): ready.set();await release.wait();return []
        client=SimpleNamespace(get_dhcp_leases=AsyncMock(side_effect=read));rabbit=SimpleNamespace(publish_event=AsyncMock())
        first=asyncio.create_task(main.poll_once(router=router(),mikrotik_client=client,rabbitmq_client=rabbit))
        await ready.wait()
        second=asyncio.create_task(main.poll_once(router=router(),mikrotik_client=client,rabbitmq_client=rabbit))
        await asyncio.sleep(0);first.cancel();await asyncio.sleep(0)
        assert not first.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await first
        assert (await second)['snapshot_published']
        rabbit.publish_event.assert_awaited_once()
    asyncio.run(run())


def test_changed_credentials_wait_for_previous_snapshot_publication():
    async def run():
        main._poll_flights.clear();old_ready=asyncio.Event();release=asyncio.Event();order=[]
        def lease(name): return DhcpLeaseObserved(mac='00:11:22:33:44:55',active_ip='192.168.1.2',hostname=name,dynamic=False,active=True,raw={})
        async def old_read(): order.append('old-read');old_ready.set();await release.wait();return [lease('old')]
        async def new_read(): order.append('new-read');return [lease('new')]
        async def publish(**kwargs): order.append(kwargs['event'].leases[0].hostname+'-publish')
        rabbit=SimpleNamespace(publish_event=AsyncMock(side_effect=publish))
        first=asyncio.create_task(main.poll_once(router=router(),mikrotik_client=SimpleNamespace(get_dhcp_leases=old_read),rabbitmq_client=rabbit))
        await old_ready.wait()
        second=asyncio.create_task(main.poll_once(router=replace(router(),api_password='changed'),mikrotik_client=SimpleNamespace(get_dhcp_leases=new_read),rabbitmq_client=rabbit))
        await asyncio.sleep(0);assert order==['old-read']
        release.set();await asyncio.gather(first,second)
        assert order==['old-read','old-publish','new-read','new-publish']
    asyncio.run(run())


def test_router_fingerprint_ignores_name_and_sync_but_not_poll_settings():
    item=router()
    assert not main.router_config_changed(item,replace(item,name='renamed',sync_enabled=False))
    for changed in [replace(item,api_password='changed'),replace(item,api_verify_tls=True),replace(item,poll_interval_seconds=30),replace(item,poll_enabled=False)]:
        assert main.router_config_changed(item,changed)


def test_backoff_preserves_normal_frequency_and_never_shortens_long_intervals(monkeypatch):
    monkeypatch.setattr(main.random,'uniform',lambda *_:1)
    assert [main.retry_delay_seconds(10,n) for n in range(5)]==[10,20,40,80,120]
    assert main.retry_delay_seconds(300,8)==300
    assert main.retry_delay_seconds(10,0)==10


def test_supervisor_keeps_workers_on_inventory_failure_and_cleans_up_on_cancel(monkeypatch):
    async def run():
        shutdown=asyncio.Event();monkeypatch.setattr(main,'_shutdown_event',shutdown)
        monkeypatch.setattr(main.settings,'supervisor_interval_seconds',.001)
        reads=0;failure_seen=asyncio.Event();worker_started=asyncio.Event();worker_stopped=asyncio.Event();released=asyncio.Event()
        async def get_routers():
            nonlocal reads
            reads+=1
            if reads==1:return [router()]
            if reads==2: failure_seen.set();raise httpx.ConnectError('temporary inventory outage')
            await released.wait();return [router()]
        async def worker(**_):
            worker_started.set()
            try: await asyncio.Future()
            finally: worker_stopped.set()
        monkeypatch.setattr(main,'poll_router_worker',worker)
        task=asyncio.create_task(main.supervisor(inventory_client=SimpleNamespace(get_active_routers=get_routers),rabbitmq_client=object()))
        await worker_started.wait();await failure_seen.wait();await asyncio.sleep(.01)
        assert not worker_stopped.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert worker_stopped.is_set()
    asyncio.run(run())


def test_successful_empty_inventory_response_stops_workers(monkeypatch):
    async def run():
        monkeypatch.setattr(main,'_shutdown_event',asyncio.Event());monkeypatch.setattr(main.settings,'supervisor_interval_seconds',.001)
        stopped=asyncio.Event();started=asyncio.Event();reads=0
        async def get_routers():
            nonlocal reads
            reads+=1
            if reads==1:return [router()]
            await started.wait();return []
        async def worker(**_):
            started.set()
            try:await asyncio.Future()
            finally:stopped.set()
        monkeypatch.setattr(main,'poll_router_worker',worker)
        task=asyncio.create_task(main.supervisor(inventory_client=SimpleNamespace(get_active_routers=get_routers),rabbitmq_client=object()))
        await asyncio.wait_for(stopped.wait(),1);main._shutdown_event.set();task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    asyncio.run(run())


def test_routeros_and_inventory_reuse_actual_tcp_connections():
    async def run():
        connections=0
        async def serve(reader,writer):
            nonlocal connections
            connections+=1
            try:
                while True:
                    header=await reader.readuntil(b'\r\n\r\n')
                    line=header.split(b'\r\n')[0]
                    if b'/lease ' in line:body=b'[]'
                    else:body=b'[]'
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body);await writer.drain()
            except (asyncio.IncompleteReadError,ConnectionError):pass
            finally:writer.close();await writer.wait_closed()
        server=await asyncio.start_server(serve,'127.0.0.1',0)
        url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        mikrotik=MikroTikClient(url,'test',SecretStr('test'),False,2)
        inventory=InventoryClient(url,2)
        try:
            for _ in range(3):assert await mikrotik.get_dhcp_leases_raw()==[]
            assert connections==1
            for _ in range(3):assert await inventory.get_active_routers()==[]
            assert connections==2
            pools=[mikrotik._client,inventory._client]
        finally:
            await mikrotik.close();await inventory.close();server.close();await server.wait_closed()
        assert all(pool.is_closed for pool in pools)
    asyncio.run(run())



def test_waiting_backoff_sends_heartbeats_without_router_requests(monkeypatch):
    async def run():
        stop=asyncio.Event();monkeypatch.setattr(main,'_shutdown_event',stop)
        monkeypatch.setattr(main.settings,'heartbeat_interval_seconds',.01)
        received=asyncio.Event();calls=0
        async def heartbeat():
            nonlocal calls
            calls+=1
            if calls==2:received.set()
        task=asyncio.create_task(main.wait_for_next_poll(120,heartbeat))
        await asyncio.wait_for(received.wait(),1)
        assert calls>=2
        stop.set()
        await asyncio.wait_for(task,.2)
    asyncio.run(run())


def test_worker_closes_http_client_on_shutdown_and_backoff_resets(monkeypatch):
    async def run():
        stop=asyncio.Event();monkeypatch.setattr(main,'_shutdown_event',stop)
        client=SimpleNamespace(close=AsyncMock())
        monkeypatch.setattr(main,'MikroTikClient',lambda **_:client)
        monkeypatch.setattr(main,'update_status_safely',AsyncMock())
        calls=0
        async def poll(**kwargs):
            nonlocal calls
            calls+=1
            if calls==1:raise httpx.ConnectError('temporary router outage')
            return {'leases_count':0,'snapshot_published':True}
        monkeypatch.setattr(main,'poll_once',poll)
        delays=[]
        async def wait(delay,heartbeat):
            delays.append(delay)
            if len(delays)==2:stop.set()
        monkeypatch.setattr(main,'wait_for_next_poll',wait)
        monkeypatch.setattr(main.random,'uniform',lambda *_:1)
        await main.poll_router_worker(router=router(),inventory_client=object(),rabbitmq_client=object())
        assert delays==[20,10]
        client.close.assert_awaited_once()
    asyncio.run(run())


def test_failed_worker_does_not_abort_supervisor_cleanup():
    async def run():
        async def failed(): raise RuntimeError('worker already failed')
        task=asyncio.create_task(failed())
        await asyncio.sleep(0)
        await main.cancel_worker(main.PollerWorkerState(router=router(),task=task))
    asyncio.run(run())


def test_routeros_total_deadline_bounds_stalled_response():
    async def run():
        async def stalled(*_): await asyncio.Future()
        client=MikroTikClient('http://127.0.0.1/rest','test',SecretStr('test'),False,.01)
        session=SimpleNamespace(get=AsyncMock(side_effect=stalled),aclose=AsyncMock())
        client._client=session
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client.get_dhcp_leases_raw(),.5)
        await client.close()
        session.aclose.assert_awaited_once()
    asyncio.run(run())
