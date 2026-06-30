# ADR-003: Redis SETNX for Idempotency

**Status:** Accepted
**Date:** 2026-06-30

## Context

The API accepts messages via `POST /api/v1/messages`. Network retries, client bugs, or load balancer replays can cause duplicate submissions. We need to ensure that publishing the same `message_id` twice does not create duplicate processing.

## Decision

**Redis `SET NX` (SET if Not eXists) with 24-hour TTL** at the API layer. Before publishing to RabbitMQ, the API attempts `SET message:{message_id} 1 NX EX 86400`. If the key already exists, the API returns `{"duplicate": true}` without publishing.

PostgreSQL `INSERT ... ON CONFLICT (message_id) DO NOTHING` serves as a safety net at the persistence layer.

## Consequences

- **Positive:** O(1) duplicate detection. Redis handles this at memory speed.
- **Positive:** Defense in depth — two independent mechanisms (Redis + PostgreSQL) prevent duplicates.
- **Positive:** 24-hour TTL prevents unbounded Redis memory growth.
- **Negative:** If Redis is unavailable, the API returns 503. No graceful degradation.
- **Negative:** If the API crashes after SETNX but before RabbitMQ publish, the idempotency key is set but the message is lost. The client must retry (and will get `duplicate=true`, so it should generate a new `message_id`).

## Alternatives Considered

1. **PostgreSQL-only idempotency** — Rejected. Requires a round-trip to PG for every publish, adding latency. Redis is faster for this check.
2. **No idempotency, rely on PG ON CONFLICT** — Rejected. The message would still be published to RabbitMQ and consumed by the worker before being rejected at PG. Wastes worker capacity.
3. **DynamoDB/Cassandra for idempotency** — Rejected. Overengineered for a single-node pipeline. Redis is simpler and sufficient.
4. **Shorter TTL (1 hour)** — Considered. 24 hours gives more safety margin for long-running retry cycles without meaningfully increasing memory usage.
