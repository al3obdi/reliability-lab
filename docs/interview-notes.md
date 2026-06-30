# Interview Notes — Reliability Lab

## 60-Second Explanation

"I built a reliability-first Arabic event processing pipeline. It accepts messages via a FastAPI endpoint, enforces idempotency through Redis, publishes to RabbitMQ for decoupling, and a Python worker persists to PostgreSQL as the source of truth and indexes to Elasticsearch for search. If PostgreSQL fails, the system retries with exponential backoff — 15, 30, 60 seconds — then dead-letters the message. If Elasticsearch fails, the message is still processed and can be reindexed later. Everything is instrumented with Prometheus. Twenty automated tests prove the reliability behavior end-to-end."

## 3-Minute Deep Technical Explanation

### The Problem

Customer service platforms receive messages through multiple channels — web, mobile, WhatsApp. These messages need to be persisted reliably, searched, and never lost. Network retries can cause duplicates. Downstream systems can fail. We need a pipeline that handles all of this gracefully.

### The Architecture

**API Layer (FastAPI):** Accepts `POST /api/v1/messages`. Before doing anything, it checks Redis with `SET NX` — if the message_id was seen before, it returns `duplicate=true` immediately. This is O(1) and prevents duplicate work from ever entering the system.

**Message Broker (RabbitMQ):** The API publishes to a durable topic exchange and returns `202 Accepted`. This decouples ingestion from processing — the API doesn't wait for the worker. If the worker is down, messages queue up. If the API is down, the worker drains the backlog.

**Worker (Python/aio-pika):** Consumes messages one at a time. First, writes to PostgreSQL with `INSERT ... ON CONFLICT DO NOTHING` — this is the source of truth. If PG is down, the worker publishes to a TTL-based retry queue. RabbitMQ holds the message for 15 seconds, then dead-letters it back to the main exchange for retry. After 3 attempts (15s → 30s → 60s), the message goes to a Dead Letter Queue with full error metadata.

**Search (Elasticsearch):** After PG confirms the write, the worker indexes to ES. If ES is down, the worker marks `index_status='failed'` in PG and continues. ES failures never cause retries or message loss. A reindex script rebuilds ES from PG at any time.

**Observability (Prometheus):** Both API and Worker expose `/metrics` endpoints. Thirteen counters track every state transition — published, duplicate, retried, DLQ'd, indexed, index-failed. Histograms track latency. You can answer "how many messages are in the DLQ right now?" with a PromQL query, not by SSHing into a container.

### Architecture Decisions

**Why PostgreSQL is source of truth:** PostgreSQL is ACID-compliant and designed for durability. Elasticsearch is designed for search, not persistence. If they disagree, PG wins. This means ES can be rebuilt from PG at any time — it's a derived store, not an authoritative one.

**Why Elasticsearch is derived:** This is the key insight. Most systems treat ES as a peer to the database, then panic when ES loses data. By making ES explicitly derived, we eliminate an entire class of reliability problems. ES failure is a search degradation, not a data loss event.

**Why Redis SETNX for idempotency:** It's O(1), in-memory, and the 24-hour TTL prevents unbounded growth. PostgreSQL `ON CONFLICT DO NOTHING` is the safety net — two independent mechanisms, defense in depth.

**Why RabbitMQ retry queues instead of infinite requeue:** An infinite requeue loop would consume all worker capacity during a PG outage. Bounded retries with backoff give PG time to recover while protecting the worker. The DLQ preserves the message for operator inspection — nothing is lost, but nothing blocks the pipeline either.

**Why no TTL on the main queue:** Messages waiting to be processed for the first time should never expire. TTL is only for retry queues, where we want the delay. Putting TTL on the main queue would cause data loss if the worker is slow.

### Production Gaps (Honest Assessment)

This is a **local reliability lab**, not a production billion-event system. What's missing:

- **API authentication** — the endpoint is open. In production, you'd add API keys or OAuth.
- **Alembic schema migrations** — currently using raw `ALTER TABLE` via docker exec. Alembic would provide versioned, reversible migrations.
- **CI pipeline** — tests run locally. A GitHub Actions workflow would run them on every push.
- **Grafana dashboard** — Prometheus collects metrics, but there's no visualization beyond the Prometheus UI.
- **Load testing** — no throughput benchmarks. I'd use k6 or locust to establish baseline performance and find bottlenecks.

### Honest Positioning

"This project demonstrates that I understand reliability patterns — not that I've run a production system at scale. The principles are production-grade: source of truth, derived stores, bounded retries, defense in depth for idempotency, observability from day one. The implementation is a local lab. In a real system, you'd add auth, CI, proper migrations, and load testing. But the architectural decisions — those are the same decisions you make at scale."

### Whiteboard Diagram

```
Client → API → Redis (idempotency)
           → RabbitMQ (durable, persistent)
                → Worker → PostgreSQL (source of truth)
                         → Elasticsearch (derived, rebuildable)
                → Retry Queues (15s/30s/60s TTL → DLX back to exchange)
                → DLQ (after 3 failures)
Prometheus ← scrape ← API (:8000/metrics) + Worker (:9100/metrics)
```

### Questions to Expect

**"Why not just use Kafka?"** — Kafka is better for high-throughput event streaming and replay. For this use case (message processing with retry/DLQ semantics), RabbitMQ's TTL + dead-letter exchange pattern is simpler and more explicit. The choice depends on whether you need ordered replay (Kafka) or per-message retry/DLQ (RabbitMQ).

**"What if Redis and PostgreSQL disagree?"** — They can't disagree on idempotency because they check different things. Redis checks "have we seen this message_id before?" at publish time. PostgreSQL checks "does this row already exist?" at insert time. If Redis says "new" but PG says "duplicate" (e.g., Redis was flushed), PG wins — `ON CONFLICT DO NOTHING` prevents the duplicate row.

**"How do you replay DLQ messages?"** — Currently manual via `scripts/inspect_dlq.py`. In production, you'd add a replay endpoint that reads from DLQ and republishes to the main exchange. The DLQ preserves the original payload, so replay is lossless.

**"What's the throughput?"** — Not benchmarked. This is a correctness demo, not a performance demo. The architecture supports horizontal scaling (more workers, RabbitMQ competing consumers), but I haven't measured it.
