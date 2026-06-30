# ADR-005: Prometheus for Observability

**Status:** Accepted
**Date:** 2026-06-30

## Context

The pipeline has multiple services (API, Worker, RabbitMQ, PostgreSQL, Redis, Elasticsearch) and multiple failure modes (duplicates, PG failures, ES failures, retries, DLQ). Without observability, operators cannot answer basic questions: "How many messages are in the DLQ?" "What's the processing rate?" "Are ES indexes failing?"

## Decision

**Prometheus for metrics collection.** Both API and Worker expose `/metrics` endpoints using the `prometheus-client` library. A Prometheus server scrapes both every 15 seconds.

**API metrics (5 counters + 1 histogram):**
- `api_requests_total` — by endpoint and status
- `api_publish_total` — successful publishes
- `api_duplicate_total` — idempotency rejections
- `api_publish_failures_total` — RabbitMQ unavailable
- `api_request_duration_seconds` — latency histogram

**Worker metrics (8 counters + 1 histogram):**
- `worker_messages_processed_total` — successful processing
- `worker_messages_failed_total` — any failure
- `worker_messages_retried_total` — sent to retry queues
- `worker_messages_dlq_total` — sent to DLQ
- `worker_pg_insert_total` — PostgreSQL writes
- `worker_es_index_total` — ES index operations
- `worker_es_index_failed_total` — ES failures
- `worker_processing_duration_seconds` — latency histogram

**No Grafana in scope.** Prometheus UI at `:9090` is sufficient for ad-hoc queries. Grafana is listed as a production gap.

## Consequences

- **Positive:** Every state transition is instrumented. Operators can answer "what happened?" without SSH.
- **Positive:** Counters survive restarts (Prometheus handles resets correctly with `rate()`).
- **Positive:** Histograms enable percentile queries (`histogram_quantile(0.99, ...)`) for latency SLOs.
- **Negative:** No alerting. Prometheus can evaluate alert rules, but without Alertmanager, there's no notification path.
- **Negative:** Metrics are in-memory only. No remote write to long-term storage.

## Alternatives Considered

1. **Log-based observability (ELK)** — Rejected. Logs are useful for debugging but poor for answering aggregate questions ("how many retries in the last hour?").
2. **OpenTelemetry** — Considered. More powerful (traces + metrics + logs) but significantly more complex to set up. Prometheus is simpler and sufficient for a single-node pipeline.
3. **CloudWatch / Datadog** — Rejected. This is a local lab. Cloud services add cost and dependency.
4. **No observability** — Rejected. A reliability lab without observability cannot demonstrate reliability.
