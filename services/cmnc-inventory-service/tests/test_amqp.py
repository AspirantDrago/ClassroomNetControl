import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cmnc_contracts import amqp

class Queue:
    name = 'test.queue'
    async def consume(self, callback, **kwargs): self.callback = callback; return 'consumer'

def message():
    return SimpleNamespace(body=b'{}',content_type='application/json',message_id='test-id',
        type='test',correlation_id=None,headers={},ack=AsyncMock(),nack=AsyncMock())

def test_retry_recovers_without_acknowledging_failed_attempt(monkeypatch):
    async def run():
        q=Queue(); exchange=SimpleNamespace(publish=AsyncMock()); item=message();calls=0
        async def callback(msg):
            nonlocal calls
            async with msg.process(requeue=False):
                calls+=1
                assert not item.ack.called
                if calls<3: raise RuntimeError('database unavailable')
        monkeypatch.setattr(amqp.asyncio,'sleep',AsyncMock())
        proxy=amqp.RetryingQueue(q,exchange,'test.queue.failed');await proxy.consume(callback)
        await q.callback(item)
        assert calls==3
        item.ack.assert_awaited_once();item.nack.assert_not_called();exchange.publish.assert_not_called()
    asyncio.run(run())

def test_exhaustion_confirms_failure_copy_before_ack(monkeypatch):
    async def run():
        q=Queue();item=message();attempts=0
        async def publish(copy,**kwargs):
            assert not item.ack.called
            assert copy.body==item.body
            assert copy.headers['cmnc-failed-queue']=='test.queue'
        exchange=SimpleNamespace(publish=AsyncMock(side_effect=publish))
        async def callback(msg):
            nonlocal attempts
            async with msg.process(requeue=False): attempts+=1;raise RuntimeError('bad')
        monkeypatch.setattr(amqp.asyncio,'sleep',AsyncMock())
        await amqp.RetryingQueue(q,exchange,'test.queue.failed').consume(callback)
        await q.callback(item)
        assert attempts==3;exchange.publish.assert_awaited_once();item.ack.assert_awaited_once()
    asyncio.run(run())

def test_archive_failure_requeues_only_after_pause(monkeypatch):
    async def run():
        q=Queue();item=message();slept=[]
        async def pause(delay): slept.append(delay)
        async def callback(msg): raise RuntimeError('bad')
        monkeypatch.setattr(amqp.asyncio,'sleep',pause)
        await amqp.RetryingQueue(q,SimpleNamespace(publish=AsyncMock(side_effect=RuntimeError('broker unavailable'))),'failed').consume(callback)
        await q.callback(item)
        assert slept[-1]>=5;item.ack.assert_not_called();item.nack.assert_awaited_once_with(requeue=True)
    asyncio.run(run())

def test_cancelled_delivery_remains_unacknowledged():
    async def run():
        q=Queue();item=message();exchange=SimpleNamespace(publish=AsyncMock())
        async def callback(msg): raise asyncio.CancelledError()
        await amqp.RetryingQueue(q,exchange,'failed').consume(callback)
        try: await q.callback(item)
        except asyncio.CancelledError: pass
        else: raise AssertionError('Cancellation suppressed')
        item.ack.assert_not_called();item.nack.assert_not_called();exchange.publish.assert_not_called()
    asyncio.run(run())

def test_publish_is_bounded_even_during_channel_recovery(monkeypatch):
    async def run():
        async def blocked(*args,**kwargs): await asyncio.Event().wait()
        monkeypatch.setattr(amqp,'PUBLISH_TIMEOUT',.01)
        try: await amqp.publish_bounded(SimpleNamespace(publish=blocked),message(),'key')
        except TimeoutError: pass
        else: raise AssertionError('Unbounded publish')
    asyncio.run(run())

def test_queue_arguments_preserved_and_failed_archive_bounded():
    async def run():
        q=SimpleNamespace(bind=AsyncMock()); consume=SimpleNamespace(declare_queue=AsyncMock(return_value=q))
        publish=SimpleNamespace(declare_queue=AsyncMock(),default_exchange=object())
        await amqp.reliable_queue(consume,publish,'existing',object(),'key')
        consume.declare_queue.assert_awaited_once_with('existing',durable=True)
        args=publish.declare_queue.call_args.kwargs['arguments']
        assert args=={'x-message-ttl':604800000,'x-max-length':10000}
    asyncio.run(run())


def test_validation_failure_is_archived_without_retry(monkeypatch):
    from pydantic import BaseModel
    class Payload(BaseModel): value: int
    async def run():
        q=Queue();item=message();exchange=SimpleNamespace(publish=AsyncMock());calls=0
        async def callback(msg):
            nonlocal calls
            calls+=1
            Payload.model_validate({'value':'invalid'})
        pause=AsyncMock();monkeypatch.setattr(amqp.asyncio,'sleep',pause)
        await amqp.RetryingQueue(q,exchange,'failed').consume(callback)
        await q.callback(item)
        assert calls==1;pause.assert_not_called();exchange.publish.assert_awaited_once();item.ack.assert_awaited_once()
    asyncio.run(run())

def test_broker_channels_are_separated_and_closed(monkeypatch):
    from cmnc_inventory_service.messaging import RabbitMqClient
    import aio_pika
    async def run():
        consumer=SimpleNamespace(set_qos=AsyncMock())
        publisher=SimpleNamespace(declare_exchange=AsyncMock(return_value=object()))
        connection=SimpleNamespace(channel=AsyncMock(side_effect=[consumer,publisher]),close=AsyncMock())
        monkeypatch.setattr(aio_pika,'connect_robust',AsyncMock(return_value=connection))
        client=RabbitMqClient('amqp://fixture.invalid')
        await client.connect()
        assert client._channel is consumer and client._publish_channel is publisher
        assert connection.channel.call_args_list[0].kwargs=={'publisher_confirms':False}
        assert connection.channel.call_args_list[1].kwargs=={'publisher_confirms':True,'on_return_raises':True}
        await client.close()
        connection.close.assert_awaited_once()
        assert client._publish_channel is None and client._channel is None
    asyncio.run(run())

def test_partial_broker_startup_closes_connection(monkeypatch):
    from cmnc_inventory_service.messaging import RabbitMqClient
    import aio_pika
    async def run():
        connection=SimpleNamespace(channel=AsyncMock(side_effect=RuntimeError('channel error')),close=AsyncMock())
        monkeypatch.setattr(aio_pika,'connect_robust',AsyncMock(return_value=connection))
        client=RabbitMqClient('amqp://fixture.invalid')
        try: await client.connect()
        except RuntimeError: pass
        else: raise AssertionError('Expected startup failure')
        connection.close.assert_awaited_once()
        assert client._connection is None
    asyncio.run(run())
