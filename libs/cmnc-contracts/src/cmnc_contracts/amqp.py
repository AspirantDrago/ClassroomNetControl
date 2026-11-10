"""Bounded AMQP delivery without changing arguments of existing queues."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from pydantic import ValidationError

logger = logging.getLogger(__name__)

def _positive(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
        return value if 0 < value < 3600 else default
    except (ValueError, TypeError):
        return default

PUBLISH_TIMEOUT = _positive("CMNC_AMQP_PUBLISH_TIMEOUT_SECONDS", 10)
CONSUMER_ATTEMPTS = max(1, min(10, int(_positive("CMNC_AMQP_CONSUMER_ATTEMPTS", 3))))
RETRY_DELAY = _positive("CMNC_AMQP_RETRY_DELAY_SECONDS", .25)

async def publish_bounded(exchange: Any, message: Any, routing_key: str):
    # Also bound time spent waiting for a robust channel to reconnect.
    async with asyncio.timeout(PUBLISH_TIMEOUT):
        return await exchange.publish(message, routing_key=routing_key, timeout=PUBLISH_TIMEOUT)

class DeferredMessage:
    """Existing handlers retain their process() syntax; the outer delivery owns ACK."""
    def __init__(self, original): self.original = original
    def __getattr__(self, name): return getattr(self.original, name)

    @asynccontextmanager
    async def process(self, **kwargs):
        yield self

class RetryingQueue:
    def __init__(self, queue, failure_exchange, failure_name):
        self.queue = queue
        self.failure_exchange = failure_exchange
        self.failure_name = failure_name

    def __getattr__(self, name): return getattr(self.queue, name)

    async def consume(self, callback, **kwargs):
        if kwargs.get("no_ack"):
            raise ValueError("Reliable consumers require acknowledgements")

        async def deliver(message):
            failure = None
            for attempt in range(CONSUMER_ATTEMPTS):
                try:
                    await callback(DeferredMessage(message))
                except asyncio.CancelledError:
                    # Channel shutdown returns unacknowledged deliveries to RabbitMQ.
                    raise
                except Exception as exc:
                    failure = exc
                    if isinstance(exc, ValidationError) or attempt + 1 == CONSUMER_ATTEMPTS:
                        break
                    logger.warning("Retrying consumer queue=%s attempt=%s error=%s", self.queue.name, attempt + 1, type(exc).__name__)
                    await asyncio.sleep(RETRY_DELAY * 2 ** attempt)
                else:
                    await message.ack()
                    return

            # New queue only: original durable queues keep their existing arguments.
            from aio_pika import DeliveryMode, Message
            archived = Message(body=message.body, content_type=message.content_type,
                delivery_mode=DeliveryMode.PERSISTENT, message_id=message.message_id,
                type=message.type, correlation_id=message.correlation_id,
                headers={**(message.headers or {}), "cmnc-failed-queue": self.queue.name,
                         "cmnc-error-type": type(failure).__name__})
            try:
                await publish_bounded(self.failure_exchange, archived, self.failure_name)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never discard the original if the failure archive is unavailable.
                # A pause prevents an immediate poison-message requeue loop.
                logger.exception("Could not archive failed delivery queue=%s", self.queue.name)
                await asyncio.sleep(max(5, RETRY_DELAY))
                await message.nack(requeue=True)
            else:
                logger.error("Archived failed delivery queue=%s error=%s", self.queue.name, type(failure).__name__)
                await message.ack()

        return await self.queue.consume(deliver, **kwargs)

async def reliable_queue(channel, publish_channel, name: str, exchange, routing_key: str):
    queue = await channel.declare_queue(name, durable=True)
    await queue.bind(exchange, routing_key=routing_key)
    failed_name = name + ".failed"
    await publish_channel.declare_queue(failed_name, durable=True,
        arguments={"x-message-ttl": 604_800_000, "x-max-length": 10000})
    return RetryingQueue(queue, publish_channel.default_exchange, failed_name)
