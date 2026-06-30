# Load and Backpressure Verification Report

**Generated:** 2026-06-30T12:01:44Z
**Input:** 100 messages, concurrency=5

## Publish Results

| Metric | Value |
|--------|-------|
| Total attempted | 100 |
| Published (new) | 100 |
| Duplicates | 0 |
| Failures | 0 |
| Publish duration | 0.2s |
| Approximate rate | 596.3 msg/s |

## Persistence Verification

| Metric | Value |
|--------|-------|
| PostgreSQL rows (this run) | 100 |
| Expected rows | 100 |
| Fully persisted | ✅ Yes |
| Indexed in ES | 100 |
| Index failed | 0 |
| Index pending | 0 |
| Wait time for persistence | 2.3s |
| ES total documents | 612 |

## Queue Health

| Queue | Message Count |
|-------|---------------|
| events.queue | 0 |
| events.retry.15s | 0 |
| events.retry.30s | 0 |
| events.retry.60s | 0 |
| events.dlq | 1 |

### Dead Letter Queue Delta

| Metric | Value |
|--------|-------|
| DLQ before load run | 1 |
| DLQ after load run | 1 |
| DLQ delta (this run) | 0 |
| DLQ clean | ✅ Yes |

## Prometheus Metrics Snapshot

### API Metrics

| Metric | Value |
|--------|-------|
| api_publish_total | 743.0 |
| api_duplicate_total | 103.0 |
| api_publish_failures_total | 0.0 |

### Worker Metrics

| Metric | Value |
|--------|-------|
| worker_messages_processed_total | 664.0 |
| worker_messages_failed_total | 90.0 |
| worker_messages_retried_total | 42.0 |
| worker_messages_dlq_total | 48.0 |
| worker_pg_insert_total | 664.0 |
| worker_es_index_total | 629.0 |
| worker_es_index_failed_total | 35.0 |

## Observations

- ✅ All 100 published messages were persisted in PostgreSQL.
- ✅ All persisted messages were indexed in Elasticsearch.
- ✅ DLQ delta = 0 — no new dead-lettered messages from this load run.
- ℹ️ DLQ has 1 pre-existing messages (from prior scenarios, not this run).

## Bottlenecks and Limits

- **Publish throughput:** 596.3 msg/s at concurrency=5
- **Worker processing:** check `worker_messages_processed_total` vs publish rate
- **Queue buildup:** if `events.queue` > 0, workers are not keeping up
- **Retry queues:** non-zero counts indicate transient failures (PG/ES)

## Worker Scaling Comparison

To compare throughput with different worker counts:

```bash
# 1 worker (default)
docker compose up -d --scale worker=1
make load-verify ARGS="--count 500 --concurrency 20"

# 3 workers
docker compose up -d --scale worker=3
make load-verify ARGS="--count 500 --concurrency 20"
```

Compare the `worker_messages_processed_total` rate and queue depths between runs.

## Honest Note

This is a **local Docker lab**, not a production benchmark. Results reflect
single-machine performance with all services on one host. Production throughput
would differ significantly due to network latency, resource contention, and
horizontal scaling. This test validates that the pipeline handles concurrent
load correctly — not that it achieves a specific throughput number.
