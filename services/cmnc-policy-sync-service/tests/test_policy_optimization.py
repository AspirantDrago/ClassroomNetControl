import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from cmnc_policy_sync_service import main
from cmnc_policy_sync_service.mikrotik_client import MikroTikClient, PolicyApplyResult
from cmnc_policy_sync_service.schemas import DesiredBlocklistResponse, DesiredBlocklistItem
from cmnc_policy_sync_service.settings import settings


def client_for(handler):
    client = MikroTikClient('http://router/rest', 'user', SecretStr('test-password'), False, 1, 'managed-by=cmnc;')
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client

def desired(ips=('192.168.1.1',)):
    return DesiredBlocklistResponse(router_id=1, policy_generation=1, device_generations={i:1 for i in range(len(ips))}, address_list_name='cmnc', blocked=[
        DesiredBlocklistItem(device_id=i,mac_address='00:11:22:33:44:55',ip_address=ip,comment='managed-by=cmnc;desired') for i,ip in enumerate(ips)])

def entry(id, disabled=False, comment='managed-by=cmnc;desired', dynamic=False):
    return {'.id':id,'list':'cmnc','address':'192.168.1.1','disabled':str(disabled).lower(),'dynamic':str(dynamic).lower(),'comment':comment}

def test_disabled_entry_enabled_and_duplicate_managed_records_removed():
    async def run():
        writes=[]
        def handle(request):
            if request.method=='GET': return httpx.Response(200,json=[entry('*1',True),entry('*2',True),entry('*3',False,'foreign'),entry('*4',False,dynamic=True)])
            writes.append((request.method,request.url.path,json.loads(request.content) if request.content else None))
            return httpx.Response(200,json={})
        client=client_for(handle)
        try:
            result=await client.apply_desired_blocklist(desired(),False)
            assert result.updated==1 and result.removed==1 and not result.errors
            assert writes==[('PATCH','/rest/ip/firewall/address-list/*1',{'comment':'managed-by=cmnc;desired','disabled':'false'}),('DELETE','/rest/ip/firewall/address-list/*2',None)]
        finally: await client.close()
    asyncio.run(run())

def test_unblock_deletes_all_managed_duplicates_but_not_foreign_or_dynamic():
    async def run():
        removed=[]
        def handle(request):
            if request.method=='GET': return httpx.Response(200,json=[entry('*1'),entry('*2'),entry('*3',comment='foreign'),entry('*4',dynamic=True)])
            removed.append(request.url.path.rsplit('/',1)[1]);return httpx.Response(200,json={})
        client=client_for(handle)
        try:
            result=await client.apply_desired_blocklist(desired(()),False)
            assert removed==['*1','*2'] and result.removed==2 and not result.errors
        finally: await client.close()
    asyncio.run(run())

@pytest.mark.parametrize('record',[entry('*1',comment='foreign'),entry('*1',True),entry('*1',comment='managed-by=cmnc;old'),entry('*1',dynamic=True)])
def test_ambiguous_write_does_not_accept_wrong_fallback(record):
    async def run():
        reads=0
        def handle(request):
            nonlocal reads
            if request.method=='GET':
                reads+=1;return httpx.Response(200,json=[] if reads==1 else [record])
            raise httpx.ReadTimeout('write result unknown',request=request)
        client=client_for(handle)
        try:
            result=await client.apply_desired_blocklist(desired(),False)
            assert result.added==0 and len(result.errors)==1
        finally: await client.close()
    asyncio.run(run())

def test_ambiguous_write_can_confirm_exact_enabled_managed_record():
    async def run():
        reads=0
        def handle(request):
            nonlocal reads
            if request.method=='GET':
                reads+=1;return httpx.Response(200,json=[] if reads==1 else [entry('*1')])
            raise httpx.ReadTimeout('unknown',request=request)
        client=client_for(handle)
        try:
            result=await client.apply_desired_blocklist(desired(),False)
            assert result.added==1 and not result.errors
        finally: await client.close()
    asyncio.run(run())

def test_batch_connection_cleanup_reduces_32_queries_to_one_and_filters_exact_ips():
    async def run():
        calls=[]
        ips=[f'192.168.1.{i}' for i in range(1,33)]
        def handle(request):
            calls.append((request.method,request.url.path))
            if request.method=='GET': return httpx.Response(200,json=[])
            if request.method=='POST':
                payload=json.loads(request.content)
                assert payload['.proplist']==['.id','src-address']
                return httpx.Response(200,json=[{'.id':f'*c{i}','src-address':ip+':5000'} for i,ip in enumerate(ips)]+[{'.id':'foreign','src-address':'192.168.1.100:80'}])
            return httpx.Response(200,json={})
        client=client_for(handle)
        try:
            result=await client.apply_desired_blocklist(desired(ips),True)
            assert result.added==32 and result.connections_killed==32 and not result.errors
            assert len(calls)==66  # Before: 1 list + 32 add + 32 print + 32 delete = 97.
            assert sum(method=='POST' for method,path in calls)==1
            assert not any(path.endswith('/foreign') for method,path in calls)
        finally: await client.close()
    asyncio.run(run())

@pytest.mark.parametrize('failure',['network','rate-limit'])
def test_thousand_connections_stop_on_network_error_or_429(failure):
    async def run():
        deletes=0
        async def handle(request):
            nonlocal deletes
            if request.method=='POST': return httpx.Response(200,json=[{'.id':str(i),'src-address':'192.168.1.1:123'} for i in range(1000)])
            deletes+=1
            await asyncio.sleep(0)
            if failure=='network': raise httpx.ReadTimeout('router offline',request=request)
            return httpx.Response(429,json={})
        client=client_for(handle)
        try:
            assert await client.remove_connections_by_src_ips(['192.168.1.1'])==0
            assert deletes<=settings.connection_delete_concurrency
        finally: await client.close()
    asyncio.run(run())

def test_disappearing_connection_404_does_not_abort_remaining_cleanup():
    async def run():
        def handle(request):
            if request.method=='POST': return httpx.Response(200,json=[{'.id':'gone','src-address':'192.168.1.1:123'},{'.id':'live','src-address':'192.168.1.1'}])
            return httpx.Response(404 if request.url.path.endswith('/gone') else 200,json={})
        client=client_for(handle)
        try: assert await client.remove_connections_by_src_ips(['192.168.1.1'])==1
        finally: await client.close()
    asyncio.run(run())

def test_unchanged_policy_reads_once_without_mutations_or_conntrack():
    async def run():
        calls=[]
        def handle(request):
            calls.append(request.method)
            assert request.url.params['.proplist']=='.id,list,address,comment,disabled,dynamic'
            return httpx.Response(200,json=[entry('*1')])
        client=client_for(handle)
        pool=client._client
        try:
            result=await client.apply_desired_blocklist(desired(),True)
            assert result==PolicyApplyResult(0,0,0,0,[])
            assert calls==['GET'] and client._http() is pool
        finally: await client.close()
        assert pool.is_closed
    asyncio.run(run())

def test_same_router_serializes_snapshot_reads_but_different_router_runs_parallel(monkeypatch):
    async def run():
        entered=[];first=asyncio.Event();release=asyncio.Event()
        async def sync(**kwargs):
            entered.append(kwargs['router'].id)
            if len(entered)==1: first.set();await release.wait()
            return {}
        monkeypatch.setattr(main,'_sync_router_policy_locked',sync)
        kwargs={'classroom_client':None,'mikrotik_client':None,'rabbitmq':None}
        one=asyncio.create_task(main.sync_router_policy(router=SimpleNamespace(id=1),**kwargs))
        await first.wait()
        two=asyncio.create_task(main.sync_router_policy(router=SimpleNamespace(id=1),**kwargs))
        three=asyncio.create_task(main.sync_router_policy(router=SimpleNamespace(id=2),**kwargs))
        await asyncio.sleep(0)
        assert entered==[1,2]
        release.set();await asyncio.gather(one,two,three)
        assert entered==[1,2,1]
    asyncio.run(run())

def test_completion_publication_error_is_not_false_apply_failure():
    async def run():
        room=SimpleNamespace(get_desired_blocklist=AsyncMock(return_value=desired()))
        device=SimpleNamespace(apply_desired_blocklist=AsyncMock(return_value=PolicyApplyResult(1,0,0,0,[])))
        rabbit=SimpleNamespace(publish_event=AsyncMock(side_effect=TimeoutError('broker unavailable')))
        router=SimpleNamespace(id=1,api_host='test',api_port=80,api_use_ssl=False,api_verify_tls=False)
        with pytest.raises(main.SyncResultDeliveryError):
            await main.sync_router_policy(router=router,classroom_client=room,mikrotik_client=device,rabbitmq=rabbit)
        device.apply_desired_blocklist.assert_awaited_once()
        rabbit.publish_event.assert_awaited_once()
        assert rabbit.publish_event.call_args.kwargs['event'].event_type=='policy.sync.completed'
    asyncio.run(run())

def test_retry_backoff_is_bounded(monkeypatch):
    monkeypatch.setattr(main.random,'uniform',lambda *_:1)
    assert [main.retry_delay(i) for i in (1,2,3,100)]==[5,10,20,120]

def test_restart_fingerprint_ignores_unrelated_fields():
    base=dict(api_host='router',api_port=443,api_use_ssl=True,api_verify_tls=False,api_username='user',api_password='test',is_enabled=True,sync_enabled=True,name='Name',poll_enabled=True,poll_interval_seconds=10)
    old=SimpleNamespace(**base)
    for change in ({'name':'Other'},{'poll_enabled':False},{'poll_interval_seconds':30}):
        assert not main.router_config_changed(old,SimpleNamespace(**{**base,**change}))
    assert main.router_config_changed(old,SimpleNamespace(**{**base,'api_password':'changed'}))

def test_inventory_error_preserves_worker_until_successful_empty_result(monkeypatch):
    async def run():
        shutdown=asyncio.Event();monkeypatch.setattr(main,'_shutdown_event',shutdown)
        monkeypatch.setattr(settings,'supervisor_interval_seconds',0.001)
        worker=asyncio.create_task(asyncio.sleep(100))
        workers={1:main.SyncWorkerState(SimpleNamespace(id=1),worker,asyncio.Queue())}
        calls=0
        async def routers():
            nonlocal calls
            calls+=1
            if calls==1: raise RuntimeError('temporary inventory outage')
            assert not worker.cancelled() and not worker.done()
            shutdown.set();return []
        await main.supervisor(inventory_client=SimpleNamespace(get_active_routers=routers),classroom_client=None,rabbitmq=None,workers=workers)
        assert worker.cancelled() and not workers and calls==2
    asyncio.run(run())

def test_supervisor_cancellation_stops_children(monkeypatch):
    async def run():
        monkeypatch.setattr(main,'_shutdown_event',asyncio.Event())
        fetching=asyncio.Event()
        async def routers(): fetching.set();await asyncio.Event().wait()
        worker=asyncio.create_task(asyncio.sleep(100))
        workers={1:main.SyncWorkerState(SimpleNamespace(id=1),worker,asyncio.Queue())}
        supervisor=asyncio.create_task(main.supervisor(inventory_client=SimpleNamespace(get_active_routers=routers),classroom_client=None,rabbitmq=None,workers=workers))
        await fetching.wait();supervisor.cancel()
        with pytest.raises(asyncio.CancelledError): await supervisor
        assert worker.cancelled() and not workers
    asyncio.run(run())

def test_worker_initial_sync_is_immediate_and_client_closed(monkeypatch):
    async def run():
        shutdown=asyncio.Event();monkeypatch.setattr(main,'_shutdown_event',shutdown)
        device=SimpleNamespace(close=AsyncMock())
        monkeypatch.setattr(main,'MikroTikClient',lambda **_:device)
        monkeypatch.setattr(main,'update_status_safely',AsyncMock())
        wait=AsyncMock();monkeypatch.setattr(main,'wait_for_trigger_or_timeout',wait)
        async def sync(**kwargs): shutdown.set();return {}
        monkeypatch.setattr(main,'sync_router_policy',sync)
        router=SimpleNamespace(id=1,name='test',api_host='test',api_port=80,api_use_ssl=False,api_verify_tls=False,base_url='http://test/rest',api_username='u',api_password='test')
        await main.sync_router_worker(router=router,trigger_queue=asyncio.Queue(),inventory_client=None,classroom_client=None,rabbitmq=None)
        wait.assert_not_awaited();device.close.assert_awaited_once()
    asyncio.run(run())


def test_retry_cap_cannot_reduce_user_base_delay(monkeypatch):
    monkeypatch.setattr(settings, 'retry_base_seconds', 200)
    monkeypatch.setattr(settings, 'retry_max_seconds', 120)
    monkeypatch.setattr(main.random, 'uniform', lambda *_: 1)
    assert main.retry_delay(1) == 200
    assert main.retry_delay(100) == 200


def test_trigger_debounce_coalesces_burst(monkeypatch):
    async def run():
        monkeypatch.setattr(settings, 'trigger_debounce_seconds', 0.01)
        queue = asyncio.Queue()
        queue.put_nowait('first')
        task = asyncio.create_task(main.wait_for_trigger_or_timeout(queue))
        await asyncio.sleep(0)
        queue.put_nowait('second')
        queue.put_nowait('latest')
        assert await task == 'latest'
        assert queue.empty()
    asyncio.run(run())


def test_cooldown_has_heartbeats_without_router_calls_and_events_cannot_bypass(monkeypatch):
    async def run():
        clock = [0.0]
        attempts = []
        heartbeats = []
        shutdown = asyncio.Event()
        queue = asyncio.Queue()
        monkeypatch.setattr(main, '_shutdown_event', shutdown)
        monkeypatch.setattr(main, 'perf_counter', lambda: clock[0])
        monkeypatch.setattr(main, 'retry_delay', lambda failures: 25.0 * failures)
        device = SimpleNamespace(close=AsyncMock())
        monkeypatch.setattr(main, 'MikroTikClient', lambda **_: device)
        async def status(*args, **kwargs):
            if kwargs.get('heartbeat_at'):
                heartbeats.append(clock[0])
        monkeypatch.setattr(main, 'update_status_safely', status)
        async def wait_trigger(_):
            # An event immediately following every failure must still wait.
            return 'new-event'
        monkeypatch.setattr(main, 'wait_for_trigger_or_timeout', wait_trigger)
        async def wait_timeout(awaitable, timeout):
            awaitable.close()
            clock[0] += timeout
            queue.put_nowait('newer-event')
            raise TimeoutError
        monkeypatch.setattr(main.asyncio, 'wait_for', wait_timeout)
        async def sync(**kwargs):
            attempts.append(clock[0])
            if len(attempts) < 3:
                raise httpx.ConnectError('router offline')
            shutdown.set()
            return {}
        monkeypatch.setattr(main, 'sync_router_policy', sync)
        router=SimpleNamespace(id=1,name='test',api_host='test',api_port=80,api_use_ssl=False,api_verify_tls=False,base_url='http://test/rest',api_username='u',api_password='test')
        await main.sync_router_worker(router=router,trigger_queue=queue,inventory_client=None,classroom_client=None,rabbitmq=None)
        assert attempts == [0,25,75]
        assert all(t in heartbeats for t in (10,20,25,35,45,55,65,75))
        assert queue.empty()
        device.close.assert_awaited_once()
    asyncio.run(run())


def test_connection_deletion_concurrency_is_bounded(monkeypatch):
    async def run():
        monkeypatch.setattr(settings, 'connection_delete_concurrency', 2)
        active = peak = deleted = 0
        async def handle(request):
            nonlocal active, peak, deleted
            if request.method == 'POST':
                return httpx.Response(200, json=[{'.id':str(i),'src-address':'192.168.1.1:123'} for i in range(32)])
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.001)
            active -= 1
            deleted += 1
            return httpx.Response(200)
        client = client_for(handle)
        try:
            assert await client.remove_connections_by_src_ips(['192.168.1.1']) == 32
            assert peak == 2 and deleted == 32
        finally:
            await client.close()
    asyncio.run(run())


def test_manual_publication_timeout_preserves_apply_metrics_and_closes_client(monkeypatch):
    async def run():
        router=SimpleNamespace(id=1,name='test',is_enabled=True,sync_enabled=True,api_host='test',api_port=80,api_use_ssl=False,api_verify_tls=False,base_url='http://test/rest',api_username='u',api_password='test')
        inventory=SimpleNamespace(get_router_connection=AsyncMock(return_value=router))
        room=SimpleNamespace(get_desired_blocklist=AsyncMock(return_value=desired()))
        device=SimpleNamespace(apply_desired_blocklist=AsyncMock(return_value=PolicyApplyResult(1,0,0,0,[])),close=AsyncMock())
        rabbit=SimpleNamespace(publish_event=AsyncMock(side_effect=TimeoutError('broker unavailable')))
        monkeypatch.setattr(main, 'MikroTikClient', lambda **_: device)
        status=AsyncMock()
        monkeypatch.setattr(main, 'update_status_safely', status)
        result=await main.sync_router_policy_manual(router_id=1,inventory_client=inventory,classroom_client=room,rabbitmq=rabbit)
        assert result['added_count']==1 and result['details']['result_delivery_error']
        assert status.call_args.kwargs['status']=='warning'
        assert status.call_args.kwargs['consecutive_failures']==0
        assert status.call_args.kwargs['last_success_at'] is not None
        device.close.assert_awaited_once()
        device.apply_desired_blocklist.assert_awaited_once()
        rabbit.publish_event.assert_awaited_once()
    asyncio.run(run())
