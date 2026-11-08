import asyncio
import pytest
import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from cmnc_veyon_service.control import RemoteControl, KeyEvent, PointerEvent
from cmnc_veyon_service.main import VeyonBridge, Target, ControlInput


class Store:
    def resolve(self, router_id, classroom_id):
        return f'test-{router_id}', 'test-key'


def test_control_is_exclusive_owned_and_releases_pressed_inputs():
    async def run():
        batches = []
        def handle(request):
            if '/authentication/' in request.url.path:
                return httpx.Response(200, json={'connection-uid':'test-connection'})
            batches.append(__import__('json').loads(request.content)['events'])
            return httpx.Response(200, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(Store(), client)
            manager = RemoteControl(bridge)
            target = Target(device_id=1, router_id=1, classroom_id=1, host='192.168.1.2')
            token = (await manager.operate(target,'user:1','start'))['token']
            for owner,action,bad_token in [('user:2','start',None),('user:2','input',token),('user:1','input','wrong')]:
                with pytest.raises(HTTPException) as exc:
                    await manager.operate(target,owner,action,bad_token)
                assert exc.value.status_code == 409
            with pytest.raises(HTTPException):
                await manager.operate(target.model_copy(update={'router_id':2}),'user:2','start')
            await manager.operate(target,'user:1','input',token,[KeyEvent(type='key',key=0xffe3,pressed=True),PointerEvent(type='pointer',x=.5,y=.25,buttons=1)])
            await manager.operate(target,'user:1','stop',token)
            assert {'type':'key','key':0xffe3,'pressed':False} in batches[-1]
            assert batches[-1][-1] == {'type':'pointer','x':.5,'y':.25,'buttons':0}
            token = (await manager.operate(target,'user:1','start'))['token']
            lease = next(iter(manager.leases.values()))
            lease.touched -= 9
            await manager.operate(target,'user:2','start')
            assert next(iter(manager.leases.values())).owner == 'user:2'
            with pytest.raises(HTTPException):
                await manager.operate(target,'user:1','input',token)
    asyncio.run(run())


def test_failed_input_is_not_retried_and_releases_possible_presses():
    async def run():
        batches=[]
        def handle(request):
            if '/authentication/' in request.url.path:
                return httpx.Response(200,json={'connection-uid':'uid'})
            events=__import__('json').loads(request.content)['events'];batches.append(events)
            if len(batches)==2:
                raise httpx.ReadTimeout('timeout')
            return httpx.Response(200,json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            manager=RemoteControl(VeyonBridge(Store(),client))
            target=Target(device_id=1,router_id=1,classroom_id=1,host='192.168.1.2')
            token=(await manager.operate(target,'user:1','start'))['token']
            with pytest.raises(HTTPException):
                await manager.operate(target,'user:1','input',token,[KeyEvent(type='key',key=65,pressed=True)])
            assert len(batches)==3
            assert {'type':'key','key':65,'pressed':False} in batches[-1]
            assert manager.leases=={}
    asyncio.run(run())


@pytest.mark.parametrize('events',[
    [{'type':'pointer','x':2,'y':0,'buttons':0}],
    [{'type':'pointer','x':float('nan'),'y':0,'buttons':0}],
    [{'type':'key','key':0,'pressed':True}],
    [{'type':'key','key':65,'pressed':'false'}],
    [{'type':'pointer','x':0,'y':0,'buttons':128}],
    [{'type':'key','key':65,'pressed':True}]*65,
])
def test_invalid_remote_input_rejected(events):
    with pytest.raises(ValidationError):
        ControlInput(device_id=1,router_id=1,classroom_id=1,host='192.168.1.2',owner='user:1',events=events)
