# Reliability Lab — Portfolio Overview

**For recruiters and engineering managers:** This is a focused demonstration of backend reliability patterns. It's not a production system — it's a proof that the author understands the architectural decisions that production systems require.

## What This Project Is

A reliability-first Arabic event processing pipeline. Messages arrive via a FastAPI endpoint, pass through Redis for idempotency, are published to RabbitMQ for durable queuing, consumed by a Python worker that persists to PostgreSQL (source of truth) and indexes to Elasticsearch (derived, rebuildable search). If PostgreSQL fails, the system retries with exponential backoff (15s → 30s → 60s) then dead-letters the message. If Elasticsearch fails, the message is still processed — ES is rebuilt from PostgreSQL later. Everything is instrumented with Prometheus.

## What This Project Proves

| Pattern | Implementation |
|---|---|
| **Idempotency** | Redis SET NX + PostgreSQL ON CONFLICT DO NOTHING — two independent mechanisms |
| **Durable messaging** | RabbitMQ persistent messages, publisher confirms, consumer ACKs |
| **Source of truth** | PostgreSQL is authoritative; Elasticsearch is derived and rebuildable |
| **Bounded retries** | TTL-based retry queues (15s/30s/60s) — RabbitMQ handles timing, not app code |
| **Dead Letter Queue** | Poison messages and exhausted retries go to DLQ with full error metadata |
| **Observability** | 13 Prometheus counters + 2 histograms across API and Worker |
| **Decoupling** | API returns 202 immediately; worker processes at its own pace |

## 6 Reliability Proof Scenarios

Run `make portfolio-verify` to execute all 6:

| # | Scenario | What It Proves |
|---|---|---|
| A | Happy path | Message flows API → PG → ES correctly |
| B | Duplicate idempotency | Same message_id twice → `duplicate=true`, PG row count = 1 |
| C | Elasticsearch outage | Stop ES → publish → PG still works → restart ES → reindex recovers |
| D | PostgreSQL failure → DLQ | Stop PG → publish → 3 retries → message lands in DLQ |
| E | Invalid payload → DLQ | Malformed message → immediate DLQ, no retries |
| F | Metrics evidence | API + Worker /metrics + Prometheus targets all UP |

## Technology Stack

- **Python 3.12** — FastAPI (API), aio-pika (Worker)
- **RabbitMQ 3.13** — durable topic exchange, TTL retry queues, DLQ
- **PostgreSQL 16** — source of truth, ON CONFLICT DO NOTHING
- **Redis 7** — idempotency key store, SET NX with 24h TTL
- **Elasticsearch 8.15** — derived search index, Arabic analyzer
- **Prometheus 2.54** — metrics collection, 15s scrape interval
- **Docker Compose** — 7 containers, one command to start

## How to Run

```bash
git clone https://github.com/al3obdi/reliability-lab.git
cd reliability-lab

make up                  # Start 7 containers
make migrate             # Run schema migration
make test                # 23 tests, ~100s
make portfolio-verify    # 6 end-to-end scenarios
```

## Honest Positioning

This is a **local reliability lab**, not a production billion-event infrastructure. It demonstrates that I understand the patterns — not that I've run them at scale.

What's missing for production:
- API authentication
- Alembic schema migrations
- CI pipeline (GitHub Actions)
- Grafana dashboard
- Load testing / throughput benchmarks

The architectural decisions — source of truth, derived stores, bounded retries, defense in depth for idempotency, observability from day one — are the same decisions you make at scale.

## Best Interview Talking Points

1. **"PostgreSQL is the source of truth; Elasticsearch is derived."** This is the key insight. Most systems treat ES as a peer to the database, then panic when ES loses data. By making ES explicitly derived, we eliminate an entire class of reliability problems.

2. **"Defense in depth for idempotency."** Redis SET NX at the API layer (fast, O(1)) + PostgreSQL ON CONFLICT DO NOTHING at the persistence layer. Two independent mechanisms. If Redis is flushed, PG still prevents duplicates.

3. **"Bounded retries, not infinite loops."** TTL-based retry queues with RabbitMQ handling the timing — no custom scheduler, no `asyncio.sleep` in application code. After 3 attempts, messages go to DLQ with full error metadata.

4. **"Derived stores don't block the critical path."** ES failures never cause retries or message loss. The worker ACKs after PG confirms the write. ES indexing is best-effort with a reindex recovery path.

5. **"Observability from day one."** 13 counters track every state transition. You can answer "how many messages are in the DLQ?" with a PromQL query, not by SSHing into a container.

## Key Files for Reviewers

| File | What It Shows |
|---|---|
| [`README.md`](README.md) | Full project documentation |
| [`docs/architecture.md`](docs/architecture.md) | System design and data flows |
| [`docs/adr/`](docs/adr/) | 5 Architecture Decision Records |
| [`docs/interview-notes.md`](docs/interview-notes.md) | How to talk about this project |
| [`reports/portfolio-verification-report.md`](reports/portfolio-verification-report.md) | Machine-verified evidence |
| [`worker/processor.py`](worker/processor.py) | Core retry/DLQ logic |
| [`api/services/idempotency.py`](api/services/idempotency.py) | Redis idempotency |
| [`tests/`](tests/) | 23 tests covering all failure modes |
