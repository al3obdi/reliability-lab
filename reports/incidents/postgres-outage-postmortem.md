# Incident Postmortem: PostgreSQL Outage → Retry + DLQ Recovery

**Incident ID:** INC-001
**Date:** 2026-06-30 (simulated)
**Severity:** High
**Duration:** ~105 seconds (3 retry cycles)
**Status:** Resolved — messages recovered via DLQ inspection

## Summary

PostgreSQL became unavailable while the worker was processing messages. The system's bounded retry mechanism engaged: messages were routed through three TTL-based retry queues (15s → 30s → 60s). After exhausting all retry attempts, messages were delivered to the Dead Letter Queue (DLQ) with full error metadata. Once PostgreSQL was restored, DLQ messages were available for operator inspection and manual replay.

No messages were lost. The API continued accepting publishes (202 Accepted) because RabbitMQ remained available. The worker correctly detected PG failures and followed the retry escalation path.

## Impact

- **User-facing:** None — API continued accepting messages (202 Accepted)
- **Data integrity:** Zero data loss — all messages either persisted after PG recovery or captured in DLQ
- **Processing delay:** Messages delayed by up to 105 seconds (3 retry cycles) before DLQ routing
- **DLQ backlog:** Messages accumulated in `events.dlq` awaiting operator action

## Detection

- **Prometheus alert:** `worker_messages_dlq_total` counter incremented
- **Queue monitoring:** `events.dlq` message count > 0
- **Worker logs:** "PostgreSQL insert failed after 3 attempts, routing to DLQ"
- **Health check:** PostgreSQL `/ready` endpoint returning 503

## Timeline

| Time | Event |
|------|-------|
| T+0s | PostgreSQL container stopped (simulated outage) |
| T+0s | Worker attempts PG insert → failure → routes to `events.retry.15s` |
| T+15s | Message expires from retry.15s → worker retries → failure → routes to `events.retry.30s` |
| T+45s | Message expires from retry.30s → worker retries → failure → routes to `events.retry.60s` |
| T+105s | Message expires from retry.60s → worker retries → failure → routes to `events.dlq` |
| T+120s | PostgreSQL restored |
| T+125s | Operator inspects DLQ, replays messages |

## Root Cause

PostgreSQL was unavailable (simulated container stop). The worker's retry logic correctly identified persistent failures and escalated through the retry chain. This is **expected behavior** — the system is designed to handle this scenario.

## Mitigation

1. **Immediate:** Restart PostgreSQL (`docker compose start postgres`)
2. **Recovery:** Inspect DLQ messages (`make inspect-dlq`), verify error metadata, replay valid messages
3. **Verification:** Confirm `worker_messages_processed_total` resumes incrementing

## Prevention

- **PostgreSQL replication:** Add streaming replica for automatic failover (production)
- **Connection pooling:** PgBouncer to handle connection storms during recovery
- **Health-aware routing:** Worker could pause consumption when PG health check fails (reduces retry churn)
- **Alerting threshold:** Alert when `events.retry.60s` queue depth exceeds N messages

## Metrics to Watch

| Metric | Normal | Warning | Critical |
|--------|--------|---------|----------|
| `events.retry.15s` depth | 0 | > 10 | > 100 |
| `events.retry.30s` depth | 0 | > 5 | > 50 |
| `events.retry.60s` depth | 0 | > 2 | > 20 |
| `events.dlq` depth | 0 | > 0 | > 10 |
| `worker_messages_dlq_total` rate | 0 | > 0 | > 5/min |

## Runbook Commands

```bash
# Check DLQ depth
make inspect-dlq

# Peek at DLQ messages (first 5)
make inspect-dlq ARGS="--peek 5"

# Purge DLQ (after reviewing all messages)
make inspect-dlq ARGS="--purge"

# Check PostgreSQL health
docker exec reliability-lab-postgres-1 pg_isready -U reliability -d reliability_lab

# Check retry queue depths
docker exec reliability-lab-rabbitmq-1 rabbitmqctl list_queues name messages | grep retry

# Verify worker is processing again
curl -s http://localhost:9100/metrics | grep worker_messages_processed_total
```

## What This Project Proves

1. **Bounded retries work:** The system does not retry infinitely — it escalates through 3 TTL-based queues then dead-letters
2. **No data loss:** Messages are never silently dropped; they end up in DLQ with full error context
3. **Decoupling works:** API availability is independent of PostgreSQL availability
4. **Observability matters:** Every state transition (retry, DLQ) is tracked by Prometheus counters
5. **Operator tooling exists:** `inspect_dlq.py` provides visibility into poisoned/dead-lettered messages
