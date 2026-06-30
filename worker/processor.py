import json
import time
import aio_pika
from datetime import datetime, timezone
from services.postgres import insert_message, mark_indexed, mark_index_failed
from services.elasticsearch import index_message
from metrics import (
    worker_messages_processed_total,
    worker_messages_failed_total,
    worker_messages_retried_total,
    worker_messages_dlq_total,
    worker_pg_insert_total,
    worker_es_index_total,
    worker_es_index_failed_total,
    worker_processing_duration_seconds,
)

RETRY_QUEUES = {
    0: "events.retry.15s",
    1: "events.retry.30s",
    2: "events.retry.60s",
}
MAX_RETRIES = 3


async def process_message(message: aio_pika.IncomingMessage, channel: aio_pika.Channel) -> None:
    """Process a single message with bounded retry and DLQ.

    Reliability rules (Day 4):
      - PostgreSQL transient failure → retry with backoff (15s/30s/60s), then DLQ.
      - Poison message / invalid payload → DLQ immediately.
      - Elasticsearch failure → do NOT retry, do NOT DLQ. PG is source of truth.
      - Explicit ACK only after successful processing or after publishing to retry/DLQ.
    """
    start = time.monotonic()

    # ── Parse body ──────────────────────────────────────────────
    try:
        body = json.loads(message.body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        worker_messages_failed_total.inc()
        worker_messages_dlq_total.inc()
        await _send_to_dlq(message, channel, body=None,
                           error_type="InvalidPayload", error_message=str(exc))
        await message.ack()
        worker_processing_duration_seconds.observe(time.monotonic() - start)
        return

    # ── Validate required fields ────────────────────────────────
    msg_id = body.get("message_id")
    customer_id = body.get("customer_id")
    text = body.get("text")

    if not msg_id or not customer_id or not text:
        worker_messages_failed_total.inc()
        worker_messages_dlq_total.inc()
        await _send_to_dlq(message, channel, body=body,
                           error_type="InvalidPayload",
                           error_message="Missing required fields: message_id, customer_id, or text")
        await message.ack()
        worker_processing_duration_seconds.observe(time.monotonic() - start)
        return

    channel_name = body.get("channel", "web")
    retry_count = body.get("retry_count", 0)
    text_normalized = " ".join(text.split())

    # ── 1. Write to PostgreSQL (source of truth) ────────────────
    try:
        inserted = await insert_message(msg_id, customer_id, text_normalized, channel_name)
        worker_pg_insert_total.inc()
    except Exception as exc:
        error_str = str(exc)[:500]
        worker_messages_failed_total.inc()
        if retry_count < MAX_RETRIES:
            worker_messages_retried_total.inc()
            await _publish_to_retry(message, channel, body, retry_count, error_str)
        else:
            worker_messages_dlq_total.inc()
            await _send_to_dlq(message, channel, body=body,
                               error_type="PostgreSQLFailure",
                               error_message=error_str,
                               retry_count=retry_count)
        await message.ack()
        worker_processing_duration_seconds.observe(time.monotonic() - start)
        return

    if inserted:
        print(f"[WORKER] Stored: {msg_id} — {text[:60]}", flush=True)
    else:
        print(f"[WORKER] Duplicate (PG): {msg_id}", flush=True)

    # ── 2. Attempt Elasticsearch indexing (derived store) ───────
    try:
        await index_message(
            message_id=msg_id,
            customer_id=customer_id,
            text=text,
            text_normalized=text_normalized,
            channel=channel_name,
            status="completed",
        )
        worker_es_index_total.inc()
        await mark_indexed(msg_id)
        print(f"[WORKER] Indexed: {msg_id}", flush=True)
    except Exception as exc:
        error_str = str(exc)[:500]
        worker_es_index_failed_total.inc()
        await mark_index_failed(msg_id, error_str)
        print(f"[WORKER] ES index failed (PG ok): {msg_id} — {error_str}", flush=True)

    # ── Success — ACK ───────────────────────────────────────────
    worker_messages_processed_total.inc()
    await message.ack()
    worker_processing_duration_seconds.observe(time.monotonic() - start)


# ═══════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════

async def _publish_to_retry(
    message: aio_pika.IncomingMessage,
    channel: aio_pika.Channel,
    body: dict,
    retry_count: int,
    error: str,
) -> None:
    retry_queue_name = RETRY_QUEUES.get(retry_count, "events.dlq")
    body["retry_count"] = retry_count + 1
    body["_last_error"] = error

    retry_msg = aio_pika.Message(
        body=json.dumps(body, default=str).encode(),
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    await channel.default_exchange.publish(retry_msg, routing_key=retry_queue_name)
    print(
        f"[WORKER] Retry {retry_count + 1}/{MAX_RETRIES}: "
        f"{body.get('message_id')} → {retry_queue_name}",
        flush=True,
    )


async def _send_to_dlq(
    message: aio_pika.IncomingMessage,
    channel: aio_pika.Channel,
    body: dict | None,
    error_type: str,
    error_message: str,
    retry_count: int = 0,
) -> None:
    dlq_payload = {
        "original_payload": body,
        "error_type": error_type,
        "error_message": error_message,
        "retry_count": retry_count,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    dlq_msg = aio_pika.Message(
        body=json.dumps(dlq_payload, default=str).encode(),
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    await channel.default_exchange.publish(dlq_msg, routing_key="events.dlq")
    msg_id = body.get("message_id", "?") if body else "?"
    print(f"[WORKER] DLQ: {msg_id} — {error_type}", flush=True)
