# Architecture — Reliability Lab

## Overview

Reliability Lab is an Arabic event processing pipeline designed to demonstrate
production-grade reliability patterns. Every design decision answers the question:
"What happens when this component fails?"

## System Diagram

```
                        ┌──────────────────────────────────────────┐
                        │              Docker Network               │
                        │                                          │
  POST /api/v1/messages │                                          │
         │              │                                          │
         ▼              │                                          │
┌─────────────┐         │                                          │
│   API       │─────────│──SET NX idempotency:{msg_id}──▶┌──────┐ │
│  (FastAPI)  │◀────────│───────was_set? (bool)──────────│Redis │ │
│  :8000      │         │                                │ :6379│ │
│  /metrics   │         │                                └──────┘ │
└──────┬──────┘         │                                          │
       │                │                                          │
       │ publish        │                                          │
       │ PERSISTENT     │                                          │
       ▼                │                                          │
┌──────────────┐        │                                          │
│  RabbitMQ    │        │                                          │
│  :5672       │        │                                          │
│              │        │                                          │
│ events.      │        │                                          │
│ exchange     │        │                                          │
│   ├─events.  │        │                                          │
│   │ queue    │────consume────────────────────────────┐           │
│   ├─retry.15s│◀──retry 1 (TTL 15s, DLX→exchange)───│           │
│   ├─retry.30s│◀──retry 2 (TTL 30s, DLX→exchange)───│           │
│   ├─retry.60s│◀──retry 3 (TTL 60s, DLX→exchange)───│           │
│   └─dlq      │◀──exhausted / poison─────────────────│           │
└──────────────┘        │                             │           │
                        │                    ┌────────▼────────┐  │
                        │                    │    Worker       │  │
                        │                    │  (aio-pika)     │  │
                        │                    │  :9100/metrics  │  │
                        │                    │                 │  │
                        │                    │ 1. parse JSON   │  │
                        │                    │ 2. validate     │  │
                        │                    │ 3. normalize    │  │
                        │                    │ 4. INSERT PG    │  │
                        │                    │ 5. index ES     │  │
                        │                    │ 6. ACK or retry │  │
                        │                    └───┬─────────┬───┘  │
                        │                        │         │      │
                        │              INSERT    │         │index │
                        │              ON        │         │_id=  │
                        │              CONFLICT  │         │msg_id│
                        │              DO NOTHING│         │      │
                        │                        ▼         ▼      │
                        │               ┌────────────┐ ┌────────┐│
                        │               │ PostgreSQL │ │  ES    ││
                        │               │   :5432    │ │ :9200  ││
                        │               │            │ │        ││
                        │               │ SOURCE OF  │ │DERIVED ││
                        │               │ TRUTH      │ │REBUILD ││
                        │               └────────────┘ └────────┘│
                        │                                          │
                        │  ┌───────────┐                          │
                        │  │Prometheus │──scrape──▶ api:8000       │
                        │  │  :9090    │──scrape──▶ worker:9100    │
                        │  └───────────┘                          │
                        └──────────────────────────────────────────┘
```

## Component Responsibilities

### API (FastAPI, port 8000)

**What it does:**
- Accepts `POST /api/v1/messages` with JSON body
- Checks Redis idempotency key before publishing
- Publishes persistent messages to RabbitMQ `events.exchange`
- Returns `202 Accepted` with status `published` or `duplicate`
- Accepts optional `retry_count` field (default 0) for retry tracking
- Exposes Prometheus metrics at `GET /metrics`

**Metrics exposed:**
- `api_requests_total` — by endpoint and status
- `api_publish_total` — successful publishes
- `api_duplicate_total` — duplicate rejections
- `api_publish_failures_total` — RabbitMQ unavailable
- `api_request_duration_seconds` — latency histogram

### Worker (aio-pika, port 9100)

**What it does:**
- Consumes from `events.queue` with `prefetch_count=10`
- Parses JSON, validates required fields (message_id, customer_id, text)
- Normalizes Arabic text (collapse whitespace)
- Inserts into PostgreSQL with `ON CONFLICT (message_id) DO NOTHING`
- Indexes into Elasticsearch with `_id = message_id`
- Tracks `index_status` in PostgreSQL: `pending` → `indexed` or `failed`
- On PG failure: publishes to retry queue with incremented `retry_count`
- On max retries exhausted: publishes to DLQ with full error metadata
- On invalid payload: publishes to DLQ immediately, no retries
- Exposes Prometheus metrics at `GET /metrics` on port 9100

**Metrics exposed:**
- `worker_messages_processed_total` — successful processing
- `worker_messages_failed_total` — processing failures
- `worker_messages_retried_total` — retry queue publications
- `worker_messages_dlq_total` — DLQ publications
- `worker_pg_insert_total` — PostgreSQL inserts
- `worker_es_index_total` — Elasticsearch index operations
- `worker_es_index_failed_total` — Elasticsearch index failures
- `worker_processing_duration_seconds` — latency histogram

### RabbitMQ (port 5672, management 15672)

**Topology:**
```
events.exchange (topic, durable)
  ├── events.queue        (durable) ← events.created.#
  ├── events.retry.15s    (durable, TTL=15s,  DLX→events.exchange, RK=events.created.retry)
  ├── events.retry.30s    (durable, TTL=30s,  DLX→events.exchange, RK=events.created.retry)
  ├── events.retry.60s    (durable, TTL=60s,  DLX→events.exchange, RK=events.created.retry)
  └── events.dlq          (durable)
```

**No TTL on events.queue** — only retry queues have TTL.

### PostgreSQL (port 5432)

**Role:** Source of truth. All other stores derive from PostgreSQL.

### Redis (port 6379)

**Role:** Fast, atomic duplicate detection. `SET NX` with 24h TTL.

### Elasticsearch (port 9200)

**Role:** Derived search index. Rebuildable from PostgreSQL via `scripts/reindex_failed.py`.

### Prometheus (port 9090)

**Role:** Metrics collection. Scrapes API (:8000/metrics) and Worker (:9100/metrics) every 15s. 7-day retention.

### Grafana (port 3000, optional)

**Role:** Dashboard visualization. Provisioned with the **Reliability Lab** dashboard (11 panels). Queries Prometheus for metrics and Loki for logs. Started via `make observability-up`. Not required for default `make up`.

### Loki + Promtail (port 3100, optional)

**Role:** Log aggregation. Promtail collects Docker container logs via the Docker socket and ships them to Loki. Grafana queries Loki for log exploration. Started via `make observability-up`. Not required for default `make up`.

## Data Flows

### Happy Path
```
1. Client POST → API → Redis SET NX → publish to RabbitMQ → 202
2. Worker consume → parse → normalize → INSERT PG → index ES → mark_indexed → ACK
```

### PostgreSQL Transient Failure (Bounded Retry)
```
1. Worker consume → INSERT PG → ConnectionError
2. retry_count=0 < 3 → publish to events.retry.15s (retry_count=1) → ACK
3. 15s TTL expires → DLX to events.exchange → routes to events.queue
4. Worker consume → INSERT PG → still down
5. retry_count=1 < 3 → publish to events.retry.30s (retry_count=2) → ACK
6. 30s TTL expires → back to events.queue
7. Worker consume → INSERT PG → still down
8. retry_count=2 < 3 → publish to events.retry.60s (retry_count=3) → ACK
9. 60s TTL expires → back to events.queue
10. Worker consume → INSERT PG → still down
11. retry_count=3 >= 3 → publish to events.dlq with error metadata → ACK
```

### Invalid Payload (DLQ Immediately)
```
1. Worker consume → json.loads() → JSONDecodeError
2. Publish to events.dlq: {error_type: "InvalidPayload", ...} → ACK
```

### Elasticsearch Outage
```
1-7. Same as happy path
8. Worker: index to ES → ConnectionError
9. Worker: mark_index_failed, ACK (do NOT retry, do NOT DLQ)
10. Later: ES recovers → reindex_failed.py rebuilds from PG
```

## Design Decisions

### Why PostgreSQL is source of truth (not Elasticsearch)
PostgreSQL provides ACID transactions, constraints, and proven durability.
Elasticsearch is optimized for search, not for being the authoritative record.

### Why Redis idempotency (not PostgreSQL-only)
Redis SET NX is O(1) and happens before the message enters RabbitMQ. Duplicates
are rejected at the API layer — they never consume queue capacity, worker CPU,
or database connections.

### Why app-declared topology (not definitions.json)
Topology is versioned with the code. Startup order doesn't matter. No risk of
definitions.json drift.

### Why ES failure does not retry or DLQ
ES is derived from PG. A persistent ES outage would fill the DLQ with
non-critical failures. Correct behavior: persist to PG, mark ES as failed,
ACK, reindex later.

### Why bounded retries with TTL-based queues (not requeue=True)
Day 2.1's `requeue=True` creates an unbounded loop. Day 4 replaces it with
explicit ACK, TTL-based retry queues (RabbitMQ handles timing), bounded
attempts (max 3), exponential backoff (15s→30s→60s), and poison message
handling (invalid payloads skip retries).

### Why no TTL on events.queue
The main queue must hold messages indefinitely — if the worker is down for
extended periods, messages should accumulate, not expire.

### Why Prometheus (not just logs)
Counters for every state transition let you answer operational questions
without SSHing into containers: "How many messages are in the DLQ right now?"
"How many retries happened in the last hour?" "What's the ES index failure rate?"

## Scaling

- **API:** Stateless. Scale horizontally. Redis idempotency is the only shared state.
- **Worker:** `docker compose up -d --scale worker=3`. `prefetch_count=10` per worker.
- **PostgreSQL:** Single instance. Read replicas for read-heavy workloads.
- **Elasticsearch:** Single node. Multi-node cluster for production.
- **Redis:** Single instance. Sentinel or Cluster for HA.
- **Prometheus:** Single instance. Federation for multi-DC.

## Production Gaps

- **Kubernetes deployment** — no K8s manifests, Helm charts, or readiness probes
- **APISIX gateway** — no API gateway example
- **Rails integration** — no example of consuming this pipeline from Rails
- **Cloud deployment** — no Terraform or multi-region topology docs
- **API auth** — no authentication or API keys
- **Schema migrations** — raw ALTER TABLE via docker exec; needs Alembic
- **CI pipeline** — no automated Docker integration test runs on push
