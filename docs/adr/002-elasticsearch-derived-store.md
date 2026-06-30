# ADR-002: Elasticsearch as Derived Store

**Status:** Accepted
**Date:** 2026-06-30

## Context

The pipeline needs full-text search over Arabic customer messages. PostgreSQL can do this with `tsvector`, but Elasticsearch provides better Arabic tokenization, relevance scoring, and query performance at scale.

However, Elasticsearch is not a durable store. Clusters can lose data. We need search without risking message loss.

## Decision

**Elasticsearch is a derived, rebuildable index.** It is populated by the Worker after PostgreSQL confirms the write. If ES is unavailable, the Worker marks `index_status='failed'` in PostgreSQL and continues. The message is never retried or dead-lettered for ES failures.

A reindex script (`scripts/reindex_failed.py`) rebuilds ES from PostgreSQL for any messages with `index_status='failed'`.

## Consequences

- **Positive:** ES failures never block the critical path. Messages are processed and ACKed regardless of ES state.
- **Positive:** Full rebuild is always possible. If the ES index is corrupted or deleted, `reindex_failed.py` reconstructs it.
- **Positive:** Clear separation of concerns — PG handles durability, ES handles search.
- **Negative:** ES can be stale. After an outage, search results are incomplete until reindex runs.
- **Negative:** Two data stores to operate and monitor.

## Alternatives Considered

1. **Retry ES failures** — Rejected. ES outages can last minutes or hours. Retrying would clog the worker and delay processing of other messages.
2. **Dead-letter ES failures** — Rejected. ES failures are not data corruption — the message is safely in PG. DLQ is for messages that need operator intervention; ES failures just need a reindex.
3. **PostgreSQL full-text search only** — Rejected. Arabic text search in PG requires manual dictionary configuration and performs worse than ES for relevance-ranked queries.
