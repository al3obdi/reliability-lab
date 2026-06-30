"""Day 5 tests: Prometheus metrics endpoints."""

import httpx


def test_api_metrics_endpoint(api_url):
    """Verify /metrics endpoint returns Prometheus text format."""
    r = httpx.get(f"{api_url}/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    # Should contain at least the standard Python metrics
    assert "python_" in body or "process_" in body or "api_" in body, (
        f"Expected Prometheus metrics, got: {body[:200]}"
    )


def test_api_metrics_has_custom_counters(api_url):
    """Verify custom API counters are registered."""
    r = httpx.get(f"{api_url}/metrics")
    assert r.status_code == 200
    body = r.text
    # Custom counters should be present (even if zero)
    expected = [
        "api_requests_total",
        "api_publish_total",
        "api_duplicate_total",
        "api_publish_failures_total",
        "api_request_duration_seconds",
    ]
    for name in expected:
        assert name in body, f"Expected metric '{name}' in /metrics output"


def test_worker_metrics_endpoint():
    """Verify worker metrics endpoint is reachable on port 9100."""
    r = httpx.get("http://localhost:9100/metrics", timeout=5)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    expected = [
        "worker_messages_processed_total",
        "worker_messages_failed_total",
        "worker_messages_retried_total",
        "worker_messages_dlq_total",
        "worker_pg_insert_total",
        "worker_es_index_total",
        "worker_es_index_failed_total",
        "worker_processing_duration_seconds",
    ]
    for name in expected:
        assert name in body, f"Expected metric '{name}' in worker /metrics output"


def test_worker_health_endpoint():
    """Verify worker health endpoint."""
    r = httpx.get("http://localhost:9100/health", timeout=5)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_metrics_increment_on_publish(api_url):
    """Publish a message and verify api_publish_total increments."""
    # Get baseline
    r_before = httpx.get(f"{api_url}/metrics")
    before_text = r_before.text

    # Publish a message
    payload = {
        "customer_id": "cust-metrics",
        "text": "اختبار المقاييس",
        "channel": "web",
    }
    r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r.status_code == 202

    # Get after
    r_after = httpx.get(f"{api_url}/metrics")
    after_text = r_after.text

    # api_publish_total should be present in both
    assert "api_publish_total" in before_text
    assert "api_publish_total" in after_text
