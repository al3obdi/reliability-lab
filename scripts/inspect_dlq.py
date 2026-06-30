"""Inspect the Dead Letter Queue (events.dlq).

Usage:
    python scripts/inspect_dlq.py              # show message count
    python scripts/inspect_dlq.py --peek 5    # peek at up to 5 messages (requeue after)
    python scripts/inspect_dlq.py --purge      # remove all messages from DLQ
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from config import settings
import aio_pika


async def get_queue_info(channel: aio_pika.Channel) -> dict:
    """Return message count and consumer count for events.dlq."""
    queue = await channel.declare_queue("events.dlq", durable=True, passive=True)
    return {
        "name": queue.name,
        "message_count": queue.declaration_result.message_count,
        "consumer_count": queue.declaration_result.consumer_count,
    }


async def peek_messages(channel: aio_pika.Channel, count: int) -> list[dict]:
    """Get up to `count` messages from DLQ, print them, then requeue."""
    messages = []
    for i in range(count):
        msg = await channel.default_exchange.get("events.dlq", no_ack=False)
        if msg is None:
            break
        try:
            body = json.loads(msg.body.decode())
        except Exception:
            body = {"raw": msg.body.decode(errors="replace")[:500]}
        messages.append(body)
        # Requeue — put it back
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=msg.body,
                content_type=msg.content_type,
                delivery_mode=msg.delivery_mode,
            ),
            routing_key="events.dlq",
        )
        await msg.ack()
    return messages


async def purge_dlq(channel: aio_pika.Channel) -> int:
    """Purge all messages from events.dlq. Returns count purged."""
    queue = await channel.declare_queue("events.dlq", durable=True, passive=True)
    purged = await queue.purge()
    return purged


async def main():
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()

        info = await get_queue_info(channel)
        print(f"Queue: {info['name']}")
        print(f"Messages: {info['message_count']}")
        print(f"Consumers: {info['consumer_count']}")

        if "--peek" in sys.argv:
            try:
                idx = sys.argv.index("--peek")
                count = int(sys.argv[idx + 1])
            except (ValueError, IndexError):
                count = 5
            print(f"\n── Peeking at up to {count} messages ──")
            msgs = await peek_messages(channel, count)
            if not msgs:
                print("(queue is empty)")
            else:
                for i, m in enumerate(msgs, 1):
                    print(f"\n── Message {i} ──")
                    print(json.dumps(m, indent=2, ensure_ascii=False, default=str))

        if "--purge" in sys.argv:
            purged = await purge_dlq(channel)
            print(f"\nPurged {purged} messages from DLQ.")


if __name__ == "__main__":
    asyncio.run(main())
