"""Prometheus metrics for the Worker service."""

from prometheus_client import Counter, Histogram, generate_latest, REGISTRY

# ── Counters ──────────────────────────────────────────────────────
worker_messages_processed_total = Counter(
    "worker_messages_processed_total",
    "Total messages successfully processed (PG + ES ok)",
)

worker_messages_failed_total = Counter(
    "worker_messages_failed_total",
    "Total messages that failed processing",
)

worker_messages_retried_total = Counter(
    "worker_messages_retried_total",
    "Total messages sent to retry queues",
)

worker_messages_dlq_total = Counter(
    "worker_messages_dlq_total",
    "Total messages sent to Dead Letter Queue",
)

worker_pg_insert_total = Counter(
    "worker_pg_insert_total",
    "Total PostgreSQL inserts (including duplicates)",
)

worker_es_index_total = Counter(
    "worker_es_index_total",
    "Total Elasticsearch index operations",
)

worker_es_index_failed_total = Counter(
    "worker_es_index_failed_total",
    "Total Elasticsearch index failures",
)

# ── Histograms ────────────────────────────────────────────────────
worker_processing_duration_seconds = Histogram(
    "worker_processing_duration_seconds",
    "Worker message processing duration in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def get_metrics() -> bytes:
    """Return Prometheus text format metrics."""
    return generate_latest(REGISTRY)
