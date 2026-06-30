"""Prometheus metrics for the API service."""

from prometheus_client import Counter, Histogram, generate_latest, REGISTRY

# ── Counters ──────────────────────────────────────────────────────
api_requests_total = Counter(
    "api_requests_total",
    "Total API requests by endpoint and status",
    ["endpoint", "status"],
)

api_publish_total = Counter(
    "api_publish_total",
    "Total messages published to RabbitMQ",
)

api_duplicate_total = Counter(
    "api_duplicate_total",
    "Total duplicate messages rejected",
)

api_publish_failures_total = Counter(
    "api_publish_failures_total",
    "Total publish failures (RabbitMQ unavailable)",
)

# ── Histograms ────────────────────────────────────────────────────
api_request_duration_seconds = Histogram(
    "api_request_duration_seconds",
    "API request duration in seconds",
    ["endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def get_metrics() -> bytes:
    """Return Prometheus text format metrics."""
    return generate_latest(REGISTRY)
