import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from cmnc_policy_sync_service import main
from cmnc_policy_sync_service.schemas import DesiredBlocklistResponse

def test_worker_preserves_device_versions_on_success_and_failure():
    async def run():
        desired=DesiredBlocklistResponse(router_id=1,policy_generation=100,device_generations={1:100,2:2},address_list_name='test',blocked=[])
        rabbit=SimpleNamespace(publish_event=AsyncMock())
        await main.publish_sync_completed(rabbitmq=rabbit,router_id=1,desired=desired,result=SimpleNamespace(added=0,removed=0,connections_killed=0))
        assert rabbit.publish_event.call_args.kwargs['event'].device_generations=={1:100,2:2}
        await main.publish_sync_failed(rabbitmq=rabbit,router_id=1,policy_generation=100,device_generations=desired.device_generations,error='test')
        assert rabbit.publish_event.call_args.kwargs['event'].device_generations=={1:100,2:2}
        router=SimpleNamespace(id=1,name='test')
        client=SimpleNamespace(get_desired_blocklist=AsyncMock(return_value=desired))
        mikrotik=SimpleNamespace(apply_desired_blocklist=AsyncMock(side_effect=RuntimeError('connection failed')))
        try: await main.sync_router_policy(router=router,classroom_client=client,mikrotik_client=mikrotik,rabbitmq=rabbit)
        except RuntimeError: pass
        else: raise AssertionError('Expected failure')
        event=rabbit.publish_event.call_args.kwargs['event']
        assert event.device_generations=={1:100,2:2}
        assert event.error=='connection failed'
    asyncio.run(run())
