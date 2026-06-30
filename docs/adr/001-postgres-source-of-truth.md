# ADR-001: PostgreSQL as Source of Truth

**Status:** Accepted
**Date:** 2026-06-30

## Context

The Reliability Lab processes Arabic customer messages through a pipeline: API → Redis → RabbitMQ → Worker → PostgreSQL → Elasticsearch. We need a single authoritative store that defines what "processed" means. If PostgreSQL and Elasticsearch disagree, one must win.

## Decision

**PostgreSQL is the source of truth.** Every message is persisted to PostgreSQL with `INSERT ... ON CONFLICT DO NOTHING`. A message is considered "processed" only after the PostgreSQL row is committed with `status='completed'`.

Elasticsearch is a derived, rebuildable index. It can be reconstructed from PostgreSQL at any time via `scripts/reindex_failed.py`.

## Consequences

- **Positive:** No data loss on Elasticsearch failure. Worker ACKs the RabbitMQ message after PostgreSQL confirms the write. ES indexing is best-effort.
- **Positive:** Reindex is always possible — the full dataset lives in PostgreSQL.
- **Positive:** Clear operational semantics: "check PostgreSQL" is the definitive answer to "was this message processed?"
- **Negative:** Two stores to manage. ES can drift from PG if reindex is not run after outages.
- **Negative:** Read queries that need full-text search must go through ES, not PG.

## Alternatives Considered

1. **Elasticsearch as source of truth** — Rejected. ES is not designed for durable persistence. Cluster failures, split-brain, and index corruption can cause data loss.
2. **Dual-write with distributed transaction** — Rejected. Adds complexity (two-phase commit, saga pattern) without proportional benefit for this use case.
3. **Event sourcing with PG as event store** — Considered but overengineered for a pipeline that processes messages once. The current model is simpler and sufficient.
