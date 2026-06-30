import aio_pika
from config import settings
from processor import process_message


async def start_consumer():
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)

    # ── Main exchange and queue ──────────────────────────────────
    exchange = await channel.declare_exchange(
        "events.exchange",
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )
    queue = await channel.declare_queue("events.queue", durable=True)
    await queue.bind(exchange, routing_key="events.created.#")

    # ── TTL-based retry queues ───────────────────────────────────
    # Each retry queue has a TTL. When TTL expires, RabbitMQ dead-letters
    # the message back to events.exchange, where it routes to events.queue.
    retry_args_template = {
        "x-dead-letter-exchange": "events.exchange",
        "x-dead-letter-routing-key": "events.created.retry",
    }

    await channel.declare_queue(
        "events.retry.15s",
        durable=True,
        arguments={**retry_args_template, "x-message-ttl": 15000},
    )
    await channel.declare_queue(
        "events.retry.30s",
        durable=True,
        arguments={**retry_args_template, "x-message-ttl": 30000},
    )
    await channel.declare_queue(
        "events.retry.60s",
        durable=True,
        arguments={**retry_args_template, "x-message-ttl": 60000},
    )

    # ── Dead Letter Queue ────────────────────────────────────────
    await channel.declare_queue("events.dlq", durable=True)

    # ── Consume with channel passed to processor ─────────────────
    async def on_message(message: aio_pika.IncomingMessage):
        await process_message(message, channel)

    await queue.consume(on_message)
    print("[WORKER] Consuming from events.queue (routing: events.created.#)", flush=True)
    print("[WORKER] Retry queues: 15s / 30s / 60s → DLQ after 3 attempts", flush=True)
    return connection
