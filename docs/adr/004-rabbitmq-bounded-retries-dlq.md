# ADR-004: RabbitMQ Bounded Retries with Dead Letter Queue

**Status:** Accepted
**Date:** 2026-06-30

## Context

The Worker writes messages to PostgreSQL. PostgreSQL can experience transient failures (connection timeout, deadlock, restart). The original Day 2.1 implementation used `message.process(requeue=True)`, which requeues the message to the same queue with no backoff and no limit — an infinite retry loop.

We need retries with backoff and a termination condition.

## Decision

**TTL-based retry queues with Dead Letter Queue.** Three retry queues with increasing TTLs:

| Queue | TTL | Attempt |
|---|---|---|
| `events.retry.15s` | 15 seconds | 1st retry |
| `events.retry.30s` | 30 seconds | 2nd retry |
| `events.retry.60s` | 60 seconds | 3rd retry |

Each retry queue has `x-dead-letter-exchange: events.exchange` and `x-dead-letter-routing-key: events.created.retry`. When TTL expires, RabbitMQ automatically routes the message back to `events.exchange`, which delivers it to `events.queue` for the next attempt.

After 3 failed attempts, the message is published to `events.dlq` with full error metadata (error_type, error_message, retry_count, failed_at timestamp).

**No TTL on the main `events.queue`** — only retry queues have TTL. This prevents premature expiration of messages waiting in the main queue.

**Invalid payloads go directly to DLQ** — no retries for unparseable messages.

**Elasticsearch failures never retry, never DLQ** — ES is derived. The message is ACKed after PG confirms the write.

## Consequences

- **Positive:** Bounded retries prevent infinite loops. Worker capacity is protected.
- **Positive:** RabbitMQ handles the timing — no custom scheduler or sleep in application code.
- **Positive:** DLQ preserves full error context for operator inspection (`scripts/inspect_dlq.py`).
- **Positive:** Exponential backoff (15s → 30s → 60s) gives PostgreSQL time to recover.
- **Negative:** Maximum recovery time is ~105 seconds (15+30+60). If PG is down longer, messages go to DLQ and need manual replay.
- **Negative:** Retry queues consume RabbitMQ memory while waiting for TTL. With many concurrent failures, this could pressure the broker.

## Alternatives Considered

1. **Infinite requeue (Day 2.1 approach)** — Rejected. A persistent PG failure would fill the queue and consume all worker capacity.
2. **Application-level retry with `asyncio.sleep`** — Rejected. Blocks the worker coroutine. RabbitMQ TTL is more robust — it survives worker restarts.
3. **Exponential backoff in a single retry queue** — Rejected. RabbitMQ TTL is per-queue, not per-message. Multiple queues with different TTLs is the standard pattern.
4. **No retries, immediate DLQ** — Rejected. Most PG failures are transient (restart, connection blip). Immediate DLQ would create unnecessary operator toil.
