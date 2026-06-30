"""Day 4 tests: bounded retries + DLQ.

These tests verify:
  - PostgreSQL failure → retry queue (15s/30s/60s) → DLQ after 3 attempts
  - Invalid payload → DLQ immediately
  - Elasticsearch failure → NOT in DLQ, PG row saved with index_status='failed'
  - Duplicate behavior unchanged

IMPORTANT: These tests stop/start services. They must run AFTER the standard
tests (elasticsearch, postgres, publish, health) to avoid polluting them.
Run with: pytest tests/test_retry_dlq.py -v (after standard tests pass).
"""

import subprocess
import time
import json
import uuid
import httpx


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _psql(query: str) -> str:
    result = subprocess.run(
        [
            "docker", "exec", "reliability-lab-postgres-1",
            "psql", "-U", "reliability", "-d", "reliability_lab",
            "-t", "-A", "-c", query,
        ],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def _queue_message_count(queue_name: str) -> int:
    """Return message count via rabbitmqadmin inside RabbitMQ container."""
    result = subprocess.run(
        ["docker", "exec", "reliability-lab-rabbitmq-1",
         "rabbitmqadmin", "-u", "reliability", "-p", "lab123",
         "list", "queues", "name", "messages"],
        capture_output=True, text=True, timeout=15,
    )
    for line in result.stdout.split("\n"):
        if queue_name in line:
            parts = line.strip().split("|")
            # Format: "| events.dlq | 0 |"
            for i, part in enumerate(parts):
                if part.strip() == queue_name and i + 1 < len(parts):
                    try:
                        return int(parts[i + 1].strip())
                    except ValueError:
                        pass
    return 0


def _purge_queue(queue_name: str) -> None:
    """Purge a queue via rabbitmqctl."""
    subprocess.run(
        ["docker", "exec", "reliability-lab-rabbitmq-1",
         "rabbitmqctl", "purge_queue", queue_name],
        capture_output=True, timeout=15,
    )


def _publish_direct(payload: dict, routing_key: str = "events.created.web") -> None:
    """Publish directly to RabbitMQ via rabbitmqadmin (bypasses API validation)."""
    body = json.dumps(payload, default=str)
    subprocess.run(
        ["docker", "exec", "reliability-lab-rabbitmq-1",
         "rabbitmqadmin", "-u", "reliability", "-p", "lab123",
         "publish",
         "routing_key=" + routing_key,
         "exchange=events.exchange",
         "payload=" + body],
        capture_output=True, timeout=10,
    )


def _worker_logs_contain(pattern: str) -> bool:
    """Check if worker logs contain a pattern."""
    result = subprocess.run(
        ["docker", "logs", "reliability-lab-worker-1"],
        capture_output=True, text=True, timeout=10,
    )
    return pattern in result.stdout


def _pg_is_ready() -> bool:
    """Check if PostgreSQL is accepting connections."""
    result = subprocess.run(
        ["docker", "exec", "reliability-lab-postgres-1",
         "pg_isready", "-U", "reliability", "-d", "reliability_lab"],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def _es_is_ready() -> bool:
    """Check if Elasticsearch is healthy."""
    import urllib.request
    try:
        req = urllib.request.Request("http://localhost:9200/_cluster/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("status") in ("green", "yellow")
    except Exception:
        return False


def _ensure_pg_ready():
    """Block until PostgreSQL is ready."""
    for _ in range(30):
        if _pg_is_ready():
            return True
        time.sleep(1)
    raise RuntimeError("PostgreSQL did not become ready")


def _ensure_es_ready():
    """Block until Elasticsearch is ready."""
    for _ in range(30):
        if _es_is_ready():
            return True
        time.sleep(1)
    raise RuntimeError("Elasticsearch did not become ready")


def _fresh_id() -> str:
    """Generate a unique message_id for this test run."""
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════

def test_pg_failure_routes_to_retry_queue(api_url):
    """Stop PostgreSQL, publish a message, verify worker retries with backoff."""
    message_id = _fresh_id()

    # Clean up
    _purge_queue("events.retry.15s")
    _purge_queue("events.retry.30s")
    _purge_queue("events.retry.60s")
    _purge_queue("events.dlq")

    # Stop PostgreSQL
    subprocess.run(
        ["docker", "stop", "reliability-lab-postgres-1"],
        capture_output=True, timeout=15,
    )
    time.sleep(3)

    try:
        payload = {
            "message_id": message_id,
            "customer_id": "cust-retry",
            "text": "اختبار إعادة المحاولة",
            "channel": "web",
        }
        r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
        assert r.status_code == 202

        # Wait for worker to attempt processing and publish to retry queue
        time.sleep(8)

        # Verify worker logged a retry attempt
        assert _worker_logs_contain(f"Retry 1/3: {message_id}"), (
            "Worker should have logged a retry attempt"
        )

        # Message should NOT be in DLQ yet (only 1st retry)
        count_dlq = _queue_message_count("events.dlq")
        assert count_dlq == 0, (
            f"Message should not be in DLQ on first retry, got count={count_dlq}"
        )

    finally:
        subprocess.run(
            ["docker", "start", "reliability-lab-postgres-1"],
            capture_output=True, timeout=15,
        )
        _ensure_pg_ready()


def test_max_retries_routes_to_dlq(api_url):
    """Publish with retry_count=3 (max exhausted) while PG is down → DLQ."""
    message_id = _fresh_id()

    _purge_queue("events.dlq")
    _purge_queue("events.retry.15s")
    _purge_queue("events.retry.30s")
    _purge_queue("events.retry.60s")

    # Ensure PG is down
    subprocess.run(
        ["docker", "stop", "reliability-lab-postgres-1"],
        capture_output=True, timeout=15,
    )
    time.sleep(3)

    try:
        # Publish with retry_count=3 to simulate exhausted retries
        payload = {
            "message_id": message_id,
            "customer_id": "cust-dlq",
            "text": "اختبار DLQ بعد استنفاد المحاولات",
            "channel": "web",
            "retry_count": 3,
        }
        r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
        assert r.status_code == 202

        # Wait for worker to process and route to DLQ
        time.sleep(8)

        # Verify worker logged DLQ
        assert _worker_logs_contain(f"DLQ: {message_id}"), (
            "Worker should have logged DLQ routing"
        )

        # Message should be in DLQ
        count_dlq = _queue_message_count("events.dlq")
        assert count_dlq > 0, (
            f"Expected message in DLQ after max retries, got count={count_dlq}"
        )

    finally:
        subprocess.run(
            ["docker", "start", "reliability-lab-postgres-1"],
            capture_output=True, timeout=15,
        )
        _ensure_pg_ready()


def test_invalid_payload_routes_to_dlq(api_url):
    """Publish a message with missing required fields directly to RabbitMQ → DLQ."""
    message_id = _fresh_id()

    _purge_queue("events.dlq")

    # Publish directly to RabbitMQ with missing 'text' field
    # (API would reject with 422, so we bypass it)
    _publish_direct({
        "message_id": message_id,
        "customer_id": "cust-invalid",
        # "text" is intentionally missing
        "channel": "web",
    })

    time.sleep(6)

    # Verify worker logged DLQ for invalid payload
    assert _worker_logs_contain(f"DLQ: {message_id}"), (
        "Worker should have logged DLQ for invalid payload"
    )

    # Message should be in DLQ
    count_dlq = _queue_message_count("events.dlq")
    assert count_dlq > 0, (
        f"Expected invalid payload in DLQ, got count={count_dlq}"
    )


def test_es_failure_does_not_dlq(api_url):
    """ES failure: PG row saved with index_status='failed', NOT in DLQ."""
    message_id = _fresh_id()

    _purge_queue("events.dlq")

    # Stop Elasticsearch
    subprocess.run(
        ["docker", "stop", "reliability-lab-elasticsearch-1"],
        capture_output=True, timeout=15,
    )
    time.sleep(3)

    try:
        payload = {
            "message_id": message_id,
            "customer_id": "cust-es-dlq",
            "text": "اختبار أن فشل ES لا يذهب إلى DLQ",
            "channel": "web",
        }
        r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
        assert r.status_code == 202

        time.sleep(6)

        # Verify PG row exists with index_status='failed'
        row = _psql(
            f"SELECT message_id, index_status FROM messages WHERE message_id = '{message_id}'"
        )
        assert row != "", "Message should exist in PostgreSQL"
        assert "failed" in row, f"Expected index_status=failed, got: {row}"

        # Verify NOT in DLQ
        count_dlq = _queue_message_count("events.dlq")
        assert count_dlq == 0, (
            f"ES failure should NOT route to DLQ, got count={count_dlq}"
        )

    finally:
        subprocess.run(
            ["docker", "start", "reliability-lab-elasticsearch-1"],
            capture_output=True, timeout=15,
        )
        _ensure_es_ready()


def test_duplicate_still_idempotent(api_url):
    """Duplicate message_id still returns duplicate=true (Day 2 behavior preserved)."""
    message_id = _fresh_id()

    payload = {
        "message_id": message_id,
        "customer_id": "cust-dup-d4",
        "text": "اختبار التكرار Day 4",
        "channel": "web",
    }

    r1 = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r1.status_code == 202
    assert r1.json()["status"] == "published"
    assert r1.json()["duplicate"] is False

    time.sleep(3)

    r2 = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r2.status_code == 202
    assert r2.json()["status"] == "duplicate"
    assert r2.json()["duplicate"] is True

    # Verify single PG row
    count = _psql(
        f"SELECT COUNT(*) FROM messages WHERE message_id = '{message_id}'"
    )
    assert count == "1", f"Expected 1 row, found {count}"
