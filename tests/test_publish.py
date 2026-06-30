import httpx


def test_publish_accepted(api_url):
    """First publish succeeds."""
    payload = {
        "customer_id": "cust-001",
        "text": "مرحبا، أريد الاستفسار عن طلبي رقم ٥٥٣٢",
        "channel": "web",
    }
    r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "published"
    assert data["duplicate"] is False
    assert data["published_at"] is not None
    assert "message_id" in data


def test_duplicate_message_returns_idempotent_response(api_url):
    """Same message_id twice: second request returns duplicate=true."""
    message_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    payload = {
        "message_id": message_id,
        "customer_id": "cust-002",
        "text": "رسالة مكررة للاختبار",
        "channel": "web",
    }

    # First request — should publish
    r1 = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r1.status_code == 202
    assert r1.json()["status"] == "published"
    assert r1.json()["duplicate"] is False

    # Second request with same message_id — should be duplicate
    r2 = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r2.status_code == 202
    assert r2.json()["status"] == "duplicate"
    assert r2.json()["duplicate"] is True
    assert r2.json()["published_at"] is None
