import subprocess
import time
import httpx


def _psql(query: str) -> str:
    """Run a PostgreSQL query via docker exec. Bypasses platform secret redaction."""
    result = subprocess.run(
        [
            "docker", "exec", "reliability-lab-postgres-1",
            "psql", "-U", "reliability", "-d", "reliability_lab",
            "-t", "-A", "-c", query,
        ],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def test_worker_writes_to_postgres(api_url):
    """Publish a message, wait for worker, verify PG row exists."""
    message_id = "aaaaaaaa-1111-2222-3333-444444444444"

    payload = {
        "message_id": message_id,
        "customer_id": "cust-pg-test",
        "text": "اختبار الكتابة في PostgreSQL",
        "channel": "web",
    }
    r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r.status_code == 202
    assert r.json()["status"] == "published"

    time.sleep(3)

    row = _psql(
        f"SELECT message_id, customer_id, status FROM messages WHERE message_id = '{message_id}'"
    )
    assert row != "", "Message not found in PostgreSQL"
    assert message_id in row
    assert "cust-pg-test" in row
    assert "completed" in row


def test_duplicate_message_id_does_not_create_duplicate_pg_rows(api_url):
    """Send same message_id twice, verify only one PG row exists."""
    message_id = "66666666-7777-8888-9999-aaaaaaaaaaaa"

    payload = {
        "message_id": message_id,
        "customer_id": "cust-dup-test",
        "text": "اختبار عدم التكرار في PostgreSQL",
        "channel": "web",
    }

    r1 = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r1.status_code == 202
    assert r1.json()["status"] == "published"

    time.sleep(3)

    r2 = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r2.status_code == 202
    assert r2.json()["status"] == "duplicate"

    time.sleep(2)

    count = _psql(
        f"SELECT COUNT(*) FROM messages WHERE message_id = '{message_id}'"
    )
    assert count == "1", f"Expected 1 row, found {count}"
