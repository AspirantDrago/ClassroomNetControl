import logging

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from pydantic import BaseModel

from cmnc_contracts.exchanges import CMNC_EVENTS_EXCHANGE
from cmnc_contracts.amqp import publish_bounded, reliable_queue

logger = logging.getLogger(__name__)


class RabbitMqClient:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._publish_channel: aio_pika.abc.AbstractRobustChannel | None = None
        self._channel: aio_pika.abc.AbstractRobustChannel | None = None
        self._exchange: aio_pika.abc.AbstractRobustExchange | None = None

    async def connect(self) -> None:
        try:
            self._connection = await aio_pika.connect_robust(self._url)
            self._publish_channel = await self._connection.channel(publisher_confirms=True, on_return_raises=True)

            self._exchange = await self._publish_channel.declare_exchange(
                CMNC_EVENTS_EXCHANGE,
                ExchangeType.TOPIC,
                durable=True,
            )

            logger.info("RabbitMQ client connected")
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()

        self._connection = None
        self._channel = None
        self._publish_channel = None
        self._exchange = None

        logger.info("RabbitMQ client closed")

    async def publish_event(
            self,
            event: BaseModel,
            routing_key: str,
    ) -> None:
        if self._exchange is None:
            raise RuntimeError("RabbitMQ client is not connected")

        event_json = event.model_dump_json()

        event_id = getattr(event, "event_id", None)
        event_type = getattr(event, "event_type", None)

        message = Message(
            body=event_json.encode("utf-8"),
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(event_id) if event_id is not None else None,
            type=str(event_type) if event_type is not None else None,
        )

        await publish_bounded(self._exchange, message, routing_key)

        logger.info(
            "Published event %s with routing key %s",
            event_type,
            routing_key,
        )
