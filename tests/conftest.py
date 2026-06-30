import time
import pytest
import httpx


@pytest.fixture(scope="session")
def api_url():
    base = "http://localhost:8000"
    for _ in range(30):
        try:
            r = httpx.get(f"{base}/health", timeout=2)
            if r.status_code == 200:
                return base
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("API did not become healthy within 30s")
