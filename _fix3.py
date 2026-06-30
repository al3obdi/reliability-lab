import os

base = '/Users/3obd/reliability-lab'

# worker/config.py — clean, no test code
worker_config = """from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    rabbitmq_url: str = "amqp://guest:***@localhost:5672/"
    database_url: str = "postgresql://postgres:***@localhost:5432/postgres"
    redis_url: str = "redis://localhost:***@localhost:5672/"
    database_url: str = "postgresql://postgres:***@localhost:5432/postgres"
    redis_url: str = "redis://localhost:***@pytest.fixture(scope="session")
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
"""

with open(os.path.join(base, 'worker/config.py'), 'w') as f:
    f.write(worker_config)

# tests/conftest.py — clean
conftest = """import time
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
"""

with open(os.path.join(base, 'tests/conftest.py'), 'w') as f:
    f.write(conftest)

# tests/test_publish.py — clean
test_pub = """import httpx


def test_publish_accepted(api_url):
    payload = {
        "customer_id": "cust-001",
        "text": "\\u0645\\u0631\\u062d\\u0628\\u0627\\u060c \\u0623\\u0631\\u064a\\u062f \\u0627\\u0644\\u0627\\u0633\\u062a\\u0641\\u0633\\u0627\\u0631 \\u0639\\u0646 \\u0637\\u0644\\u0628\\u064a \\u0631\\u0642\\u0645 \\u0665\\u0665\\u0663\\u0662",
        "channel": "web",
    }
    r = httpx.post(f"{api_url}/api/v1/messages", json=payload)
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "published"
    assert "message_id" in data
"""

with open(os.path.join(base, 'tests/test_publish.py'), 'w') as f:
    f.write(test_pub)

# Verify
import py_compile
for f in ['worker/config.py', 'tests/conftest.py', 'tests/test_publish.py']:
    try:
        py_compile.compile(os.path.join(base, f), doraise=True)
        print(f'{f}: OK')
    except py_compile.PyCompileError as e:
        print(f'{f}: ERROR - {e}')
