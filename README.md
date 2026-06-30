# Reliability Lab — Arabic Event Processing Pipeline

A reliability-first event processing pipeline demonstrating production-grade patterns:
idempotency, durable messaging, source-of-truth persistence, rebuildable search indexes,
bounded retries, dead-letter queues, and Prometheus observability.

## Architecture

```
POST /api/v1/messages
        │
        ▼
┌───────────────┐     SET NX      ┌─────────┐
│   FastAPI      │───▶───────────▶│  Redis   │
│   (api/)       │◀───was_set?────│          │
│  :8000 /metrics│                └─────────┘
└───────┬───────┘
        │ publish
        ▼
┌───────────────┐                 ┌──────────────┐
│   RabbitMQ     │────consume────▶│   Worker      │
│ events.exchange│                │  (worker/)    │
│ events.queue   │                │  :9100/metrics│
│ retry.15s/30s  │◀───retry──────│               │
│ retry.60s      │                │               │
│ events.dlq     │◀───exhausted──│               │
└───────────────┘                └───┬───────┬───┘
                                    │       │
                              INSERT │       │ index
                                    ▼       ▼
                            ┌──────────┐ ┌──────────────┐
                            │PostgreSQL│ │Elasticsearch  │
                            │(source   │ │(derived,      │
                            │ of truth)│ │ rebuildable)  │
                            └──────────┘ └──────────────┘

┌───────────┐
│Prometheus │──scrape──▶ api:8000/metrics
│  :9090    │──scrape──▶ worker:9100/metrics
└───────────┘
```

**Data flow:** API → Redis (idempotency) → RabbitMQ (decoupling) → Worker → PostgreSQL (source of truth) → Elasticsearch (derived index)

**Retry flow:** PG failure → retry.15s (15s TTL) → retry.30s (30s TTL) → retry.60s (60s TTL) → DLQ (after 3 attempts)

**Observability:** Prometheus scrapes API and Worker metrics every 15s

## Quick Start

```bash
# 1. Start all services (7 containers)
docker compose up -d --build

# 2. Run schema migration
make migrate

# 3. Run the test suite
make test
```

**Expected output:** 20 passed in ~100s

### Manual verification

```bash
# Publish a message (message_id must be a valid UUID)
curl -s -X POST http://localhost:8000/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{"message_id":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","customer_id":"cust-001","text":"مرحبا بالعالم","channel":"web"}'

# Check PostgreSQL
docker exec reliability-lab-postgres-1 psql -U reliability -d reliability_lab \
  -c "SELECT message_id, status, index_status FROM messages WHERE message_id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'"

# Check Elasticsearch
curl -s http://localhost:9200/messages-v1/_doc/a1b2c3d4-e5f6-7890-abcd-ef1234567890 | jq ._source

# Check API metrics
curl -s http://localhost:8000/metrics | grep api_publish_total

# Check Worker metrics
curl -s http://localhost:9100/metrics | grep worker_messages_processed_total

# Prometheus UI
open http://localhost:9090

# Seed with test data
make seed ARGS="--count 100"

# Verify SLOs
make verify-slos

# Inspect Dead Letter Queue
make inspect-dlq
```

## Services

| Service | Image | Port | Purpose |
|---|---|---|---|
| **api** | python:3.12-slim (FastAPI) | 8000 | Accepts messages, enforces idempotency, publishes to RabbitMQ, exposes /metrics |
| **worker** | python:3.12-slim (aio-pika) | 9100 | Consumes messages, persists to PostgreSQL, indexes to Elasticsearch, bounded retry/DLQ, exposes /metrics |
| **rabbitmq** | rabbitmq:3.13-management-alpine | 5672, 15672 | Durable message broker with TTL-based retry queues and DLQ |
| **postgres** | postgres:16-alpine | 5432 | Source of truth — all messages persisted with ON CONFLICT DO NOTHING |
| **redis** | redis:7-alpine | 6379 | Idempotency key store — SET NX with 24h TTL |
| **elasticsearch** | elasticsearch:8.15.1 | 9200 | Derived search index with Arabic-friendly analyzer |
| **prometheus** | prom/prometheus:v2.54.1 | 9090 | Metrics collection and querying |

## Metrics

### API Metrics (port 8000, /metrics)

| Metric | Type | Description |
|---|---|---|
| `api_requests_total` | Counter | Total API requests by endpoint and status |
| `api_publish_total` | Counter | Total messages published to RabbitMQ |
| `api_duplicate_total` | Counter | Total duplicate messages rejected |
| `api_publish_failures_total` | Counter | Total publish failures (RabbitMQ unavailable) |
| `api_request_duration_seconds` | Histogram | API request duration in seconds |

### Worker Metrics (port 9100, /metrics)

| Metric | Type | Description |
|---|---|---|
| `worker_messages_processed_total` | Counter | Total messages successfully processed |
| `worker_messages_failed_total` | Counter | Total messages that failed processing |
| `worker_messages_retried_total` | Counter | Total messages sent to retry queues |
| `worker_messages_dlq_total` | Counter | Total messages sent to Dead Letter Queue |
| `worker_pg_insert_total` | Counter | Total PostgreSQL inserts |
| `worker_es_index_total` | Counter | Total Elasticsearch index operations |
| `worker_es_index_failed_total` | Counter | Total Elasticsearch index failures |
| `worker_processing_duration_seconds` | Histogram | Worker message processing duration |

## Current Completed Stages

### Day 1: RabbitMQ Publish/Consume
- FastAPI endpoint `POST /api/v1/messages` publishes to `events.exchange`
- Worker consumes from `events.queue` with `events.created.#` routing key
- App-declared topology, persistent messages, durable exchange and queue

### Day 2: Redis Idempotency + PostgreSQL Persistence
- Redis `SET NX` with 24h TTL, `INSERT ... ON CONFLICT DO NOTHING`
- Arabic text normalization, asyncpg connection pool

### Day 2.1: Explicit Requeue on PostgreSQL Failure
- `message.process(requeue=True)` — PG failure returns message to queue

### Day 3: Elasticsearch Derived Indexing + Reindex Path
- Arabic-friendly analyzer, `index_status` tracking, reindex script
- ES failure does NOT requeue

### Day 4: Bounded Retries + Dead Letter Queue
- TTL-based retry queues: 15s → 30s → 60s → DLQ (3 attempts)
- Invalid payloads → DLQ immediately, ES failure never retries/DLQs
- `scripts/inspect_dlq.py` for DLQ inspection

### Day 5: Observability + Portfolio Polish
- Prometheus metrics on API (:8000/metrics) and Worker (:9100/metrics)
- Prometheus server (:9090) scraping both services every 15s
- `scripts/seed_messages.py` — load generator with Arabic sample data
- `scripts/verify_slos.py` — SLO verification from Prometheus metrics

## Reliability Principles

### PostgreSQL is the Source of Truth
Every message is persisted to PostgreSQL with `INSERT ... ON CONFLICT DO NOTHING`. Transient failures trigger bounded retries (15s/30s/60s). Persistent failures route to DLQ. No message is lost.

### Elasticsearch is Derived and Rebuildable
ES failures never cause message loss, retries, or DLQ routing. The reindex script rebuilds ES from PostgreSQL at any time.

### Redis Prevents Duplicate Publishes
`SET NX` with 24h TTL at the API layer. PostgreSQL `ON CONFLICT DO NOTHING` is the safety net.

### RabbitMQ Decouples Ingestion from Processing
API returns `202 Accepted` immediately. Worker consumes at its own pace. Neither is a bottleneck for the other.

### Bounded Retries Prevent Infinite Loops
Max 3 attempts with exponential backoff. Poison messages skip retries entirely. Worker capacity is protected.

## Failure Mode Table

| Scenario | Behavior | Data Loss? |
|---|---|---|
| **Duplicate POST** | Redis SETNX fails → `duplicate=true`, no publish | No |
| **Publish fails after SETNX** | Redis key deleted → client can retry | No |
| **PostgreSQL transient failure** | Retry with backoff: 15s → 30s → 60s | No |
| **PostgreSQL persistent failure** (3 attempts) | Message routed to `events.dlq` with error metadata | No |
| **PostgreSQL duplicate row** | `ON CONFLICT DO NOTHING` → ACK | No |
| **Elasticsearch failure** | `index_status='failed'`, ACK, reindex later | No |
| **Invalid payload** | Routed to `events.dlq` immediately, no retries | No |
| **Worker crash mid-process** | No ACK → RabbitMQ redelivers | No |
| **Redis unavailable** | API returns 503 | No |
| **RabbitMQ unavailable** | API returns 503, idempotency key removed | No |

## Test Summary

```
tests/test_health.py::test_health PASSED
tests/test_health.py::test_ready PASSED
tests/test_publish.py::test_publish_accepted PASSED
tests/test_publish.py::test_duplicate_message_returns_idempotent_response PASSED
tests/test_postgres.py::test_worker_writes_to_postgres PASSED
tests/test_postgres.py::test_duplicate_message_id_does_not_create_duplicate_pg_rows PASSED
tests/test_elasticsearch.py::test_worker_writes_to_postgres_and_indexes_es PASSED
tests/test_elasticsearch.py::test_es_document_id_matches_message_id PASSED
tests/test_elasticsearch.py::test_duplicate_message_id_es_upsert_idempotent PASSED
tests/test_elasticsearch.py::test_es_failure_does_not_requeue PASSED
tests/test_retry_dlq.py::test_pg_failure_routes_to_retry_queue PASSED
tests/test_retry_dlq.py::test_max_retries_routes_to_dlq PASSED
tests/test_retry_dlq.py::test_invalid_payload_routes_to_dlq PASSED
tests/test_retry_dlq.py::test_es_failure_does_not_dlq PASSED
tests/test_retry_dlq.py::test_duplicate_still_idempotent PASSED
tests/test_metrics.py::test_api_metrics_endpoint PASSED
tests/test_metrics.py::test_api_metrics_has_custom_counters PASSED
tests/test_metrics.py::test_worker_metrics_endpoint PASSED
tests/test_metrics.py::test_worker_health_endpoint PASSED
tests/test_metrics.py::test_metrics_increment_on_publish PASSED

======================== 20 passed in 100.78s ========================
```

## Production Gaps

- **Grafana dashboard** — no visualization for queue depths, DLQ backlog, processing rates
- **Auth/API keys** — the API is unauthenticated
- **Schema migrations** — raw ALTER TABLE via docker exec; needs Alembic
- **CI pipeline** — no automated test runs on push
- **Load testing** — no throughput benchmarks

## How to Describe This Project in Interviews

**One-liner:** "I built a reliability-first Arabic event processing pipeline that demonstrates production-grade patterns: idempotency, durable messaging, source-of-truth persistence, bounded retries with dead-letter queues, and Prometheus observability."

**Key talking points:**

1. **Source of truth pattern** — PostgreSQL is the authoritative store; Elasticsearch is a derived, rebuildable index. If ES burns down, we rebuild it from PG in minutes.

2. **Defense in depth for idempotency** — Redis SET NX at the API layer (fast, O(1)) + PostgreSQL ON CONFLICT DO NOTHING at the persistence layer (safety net). Two independent mechanisms.

3. **Bounded retries with backoff** — Not just "retry on failure." TTL-based retry queues (15s → 30s → 60s) with RabbitMQ handling the timing, not application code. After 3 attempts, messages go to a Dead Letter Queue with full error metadata for operator inspection.

4. **Derived stores don't block the critical path** — Elasticsearch failures never cause retries or message loss. The worker ACKs the message after PostgreSQL confirms the write. ES indexing is best-effort with a reindex recovery path.

5. **Observability from day one** — Prometheus metrics on both API and Worker. Counters for every state transition (published, duplicate, retried, DLQ'd, indexed, index-failed). Histograms for latency. You can answer "how many messages are in the DLQ right now?" without SSHing into a container.

6. **Decoupled ingestion and processing** — The API returns 202 Accepted immediately after publishing to RabbitMQ. The worker processes at its own pace. If the worker is down, messages queue up. If the API is down, the worker drains the backlog. Neither is a bottleneck.

**Architecture diagram to draw on the whiteboard:**
```
Client → API → Redis (idempotency)
           → RabbitMQ (durable, persistent)
                → Worker → PostgreSQL (source of truth)
                         → Elasticsearch (derived, rebuildable)
                → Retry Queues (15s/30s/60s TTL → DLX back to exchange)
                → DLQ (after 3 failures)
Prometheus ← scrape ← API (:8000/metrics) + Worker (:9100/metrics)
```

## Project Structure

```
reliability-lab/
├── docker-compose.yml
├── prometheus.yml
├── .env
├── Makefile
├── requirements-dev.txt
├── README.md
│
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py
│   ├── main.py
│   ├── metrics.py
│   ├── routes/
│   │   ├── health.py
│   │   └── messages.py
│   ├── services/
│   │   ├── publisher.py
│   │   └── idempotency.py
│   └── schemas/
│       └── message.py
│
├── worker/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py
│   ├── main.py
│   ├── metrics.py
│   ├── consumer.py
│   ├── processor.py
│   └── services/
│       ├── postgres.py
│       └── elasticsearch.py
│
├── db/
│   └── init.sql
│
├── scripts/
│   ├── reindex_failed.py
│   ├── inspect_dlq.py
│   ├── seed_messages.py
│   └── verify_slos.py
│
├── tests/
│   ├── conftest.py
│   ├── test_health.py
│   ├── test_publish.py
│   ├── test_postgres.py
│   ├── test_elasticsearch.py
│   ├── test_retry_dlq.py
│   └── test_metrics.py
│
├── reports/
│   ├── day-2.1-patch-report.txt
│   ├── day-3-patch-report.txt
│   ├── day-3-report.txt
│   ├── day-3-verification-report.txt
│   ├── day-4-report.txt
│   ├── day-4-verification-report.txt
│   └── day-5-verification-report.txt
│
└── docs/
    └── architecture.md
```
