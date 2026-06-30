import json
import aio_pika
from config import settings


class MessagePublisher:
    def __init__(self):
        self._connection = None
        self._channel = None
        self._exchange = None

    async def connect(self):
        self._connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=1)

        self._exchange = await self._channel.declare_exchange(
            "events.exchange",
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        queue = await self._channel.declare_queue("events.queue", durable=True)
        await queue.bind(self._exchange, routing_key="events.created.#")

    async def publish(self, message: dict, routing_key: str = "events.created.web") -> None:
        body = json.dumps(message, default=str).encode()
        msg = aio_pika.Message(
            body=body,
            content_type="application/json",
            message_id=message.get("message_id"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self._exchange.publish(msg, routing_key=routing_key)

    async def close(self):
        if self._channel:
            await self._channel.close()
        if self._connection:
            await self._connection.close()


publisher = MessagePublisher()
