import logging

import aio_pika
from aio_pika import ExchangeType

from cmnc_contracts.exchanges import CMNC_EVENTS_EXCHANGE

logger = logging.getLogger(__name__)


class RabbitMqClient:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractRobustChannel | None = None
        self._exchange: aio_pika.abc.AbstractRobustExchange | None = None

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=1)

        self._exchange = await self._channel.declare_exchange(
            CMNC_EVENTS_EXCHANGE,
            ExchangeType.TOPIC,
            durable=True,
        )

        logger.info("RabbitMQ client connected")

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()

        self._connection = None
        self._channel = None
        self._exchange = None

        logger.info("RabbitMQ client closed")

    async def declare_queue(
            self,
            queue_name: str,
            routing_key: str,
    ) -> aio_pika.abc.AbstractRobustQueue:
        if self._channel is None or self._exchange is None:
            raise RuntimeError("RabbitMQ client is not connected")

        queue = await self._channel.declare_queue(
            queue_name,
            durable=True,
        )

        await queue.bind(
            self._exchange,
            routing_key=routing_key,
        )

        logger.info(
            "Declared queue %s bound to %s",
            queue_name,
            routing_key,
        )

        return queue
