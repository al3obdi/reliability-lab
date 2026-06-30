import httpx


def test_health(api_url):
    r = httpx.get(f"{api_url}/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready(api_url):
    r = httpx.get(f"{api_url}/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}
