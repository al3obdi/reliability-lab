import subprocess
import time
import httpx


def _psql(query: str) -> str:
    """Run a PostgreSQL query via docker exec."""
    result = subprocess.run(
        [
            "docker", "exec", "reliability-lab-postgres-1",
            "psql", "-U", "reliability", "-d", "reliability_lab",
            "-t", "-A", "-c", query,
        ],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def _es_get(message_id: str) -> dict | None:
    """Get a document from Elasticsearch by message_id."""
    import urllib.request
    import json
    url = f"http://localhost:9200/messages-v1/_doc/{message_id}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("_source")
    except Exception:
        return None


def test_worker_writes_to_postgres_and_indexes_es(api_url):
    """Publish a message, verify PG row + ES document exist."""
    message_id = "11111111-2222-3333-4444-555555555555"

    payload = {
        "message_id": message_id,
        "customer_id": "cust-es-test",
        "text": "اختبار الفهرسة في Elasticsearch",
        "channel": "web",
    }
    r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r.status_code == 202
    assert r.json()["status"] == "published"

    time.sleep(4)

    # Verify PostgreSQL
    row = _psql(
        f"SELECT message_id, customer_id, index_status FROM messages WHERE message_id = '{message_id}'"
    )
    assert row != "", "Message not found in PostgreSQL"
    assert message_id in row
    assert "cust-es-test" in row
    assert "indexed" in row, f"Expected index_status=indexed, got: {row}"

    # Verify Elasticsearch
    doc = _es_get(message_id)
    assert doc is not None, "Document not found in Elasticsearch"
    assert doc["message_id"] == message_id
    assert doc["customer_id"] == "cust-es-test"
    assert "اختبار" in doc["text"]


def test_es_document_id_matches_message_id(api_url):
    """Verify ES document _id equals message_id."""
    message_id = "22222222-3333-4444-5555-666666666666"

    payload = {
        "message_id": message_id,
        "customer_id": "cust-es-id",
        "text": "اختبار تطابق المُعرّف",
        "channel": "web",
    }
    r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r.status_code == 202

    time.sleep(4)

    # Query ES directly by _id
    import urllib.request
    import json
    url = f"http://localhost:9200/messages-v1/_doc/{message_id}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
        assert data["_id"] == message_id
        assert data["found"] is True


def test_duplicate_message_id_es_upsert_idempotent(api_url):
    """Send same message_id twice, verify single PG row + ES upsert."""
    message_id = "33333333-4444-5555-6666-777777777777"

    payload = {
        "message_id": message_id,
        "customer_id": "cust-dup-es",
        "text": "اختبار upsert في Elasticsearch",
        "channel": "web",
    }

    r1 = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r1.status_code == 202
    assert r1.json()["status"] == "published"

    time.sleep(4)

    r2 = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r2.status_code == 202
    assert r2.json()["status"] == "duplicate"

    time.sleep(2)

    # Verify single PG row
    count = _psql(
        f"SELECT COUNT(*) FROM messages WHERE message_id = '{message_id}'"
    )
    assert count == "1", f"Expected 1 row, found {count}"

    # Verify ES document exists (upserted)
    doc = _es_get(message_id)
    assert doc is not None, "ES document should exist after upsert"
    assert doc["message_id"] == message_id


def test_es_failure_does_not_requeue(api_url):
    """Simulate ES failure: PG row saved, index_status='failed', no requeue.

    This test verifies the reliability rule: ES is derived, PG is source of truth.
    We stop ES, publish, verify PG row has index_status='failed'.
    """
    message_id = "44444444-5555-6666-7777-888888888888"

    # Stop Elasticsearch
    subprocess.run(
        ["docker", "stop", "reliability-lab-elasticsearch-1"],
        capture_output=True, timeout=15,
    )
    time.sleep(3)

    try:
        payload = {
            "message_id": message_id,
            "customer_id": "cust-es-fail",
            "text": "اختبار فشل Elasticsearch",
            "channel": "web",
        }
        r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
        assert r.status_code == 202

        time.sleep(5)

        # Verify PG row exists with index_status='failed'
        row = _psql(
            f"SELECT message_id, index_status, index_error FROM messages WHERE message_id = '{message_id}'"
        )
        assert row != "", "Message should exist in PostgreSQL"
        assert message_id in row
        assert "failed" in row, f"Expected index_status=failed, got: {row}"

        # Verify ES document does NOT exist
        doc = _es_get(message_id)
        assert doc is None, "ES document should not exist when ES is down"

    finally:
        # Restart Elasticsearch
        subprocess.run(
            ["docker", "start", "reliability-lab-elasticsearch-1"],
            capture_output=True, timeout=15,
        )
        time.sleep(15)  # Wait for ES to be ready
