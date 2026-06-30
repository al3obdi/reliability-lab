import os

base = '/Users/3obd/reliability-lab'
files = {}

# docker-compose.yml
files['docker-compose.yml'] = """services:
  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_USER:-reliability}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASS:-lab123}
    healthcheck:
      test: rabbitmq-diagnostics -q ping
      interval: 10s
      retries: 5

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: ${PG_USER:-reliability}
      POSTGRES_PASSWORD: ${PG_PASS:-lab123}
      POSTGRES_DB: reliability_lab
    volumes:
      - ./db/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    healthcheck:
      test: pg_isready -U ${PG_USER:-reliability} -d reliability_lab
      interval: 10s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: redis-cli ping
      interval: 10s
      retries: 5

  api:
    build: ./api
    ports:
      - "8000:8000"
    environment:
      RABBITMQ_URL: amqp://${RABBITMQ_USER}:***@rabbitmq:5672/
      DATABASE_URL: postgresql://${PG_USER}:***@postgres:5432/reliability_lab
      REDIS_URL: redis://redis:***@rabbitmq:5672/
      DATABASE_URL: postgresql://${PG_USER}:***@postgres:5432/reliability_lab
      REDIS_URL: redis://redis:***@rabbitmq:5672/
      DATABASE_URL: postgresql://${PG_USER}:***@postgres:5432/reliability_lab
      REDIS_URL: redis://redis:***@rabbitmq:5672/
      DATABASE_URL: postgresql://${PG_USER}:***@postgres:5432/reliability_lab
      REDIS_URL: redis://redis:***@localhost:5672/"
    database_url: str = "postgresql://postgres:***@localhost:5432/postgres"
    redis_url: str = "redis://localhost:***@localhost:5672/"
    database_url: str = "postgresql://postgres:***@localhost:5432/postgres"
    redis_url: str = "redis://localhost:***@asynccontextmanager
async def lifespan(app: FastAPI):
    await publisher.connect()
    yield
    await publisher.close()


app = FastAPI(
    title="Reliability Lab API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router, tags=["health"])
app.include_router(messages.router, tags=["messages"])
"""

# api/routes/__init__.py
files['api/routes/__init__.py'] = ""

# api/routes/health.py
files['api/routes/health.py'] = """from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    return {"status": "ready"}
"""

# api/routes/messages.py
files['api/routes/messages.py'] = """from fastapi import APIRouter, HTTPException
from schemas.message import MessageRequest, MessageResponse
from services.publisher import publisher
from datetime import datetime, timezone

router = APIRouter()


@router.post("/api/v1/messages", response_model=MessageResponse, status_code=202)
async def create_message(req: MessageRequest):
    try:
        routing_key = f"events.created.{req.channel.value}"
        await publisher.publish(req.model_dump(), routing_key=routing_key)
        return MessageResponse(
            message_id=req.message_id,
            status="published",
            published_at=datetime.now(timezone.utc),
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Publish failed: {str(e)}")
"""

# api/services/__init__.py
files['api/services/__init__.py'] = ""

# api/services/publisher.py
files['api/services/publisher.py'] = """import json
import aio_pika
from config import settings


class MessagePublisher:
    def __init__(self):
        self._connection = None
        self._channel = None
        self._exchange = None

    async def connect(self):
        self._connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=1)

        self._exchange = await self._channel.declare_exchange(
            "events.exchange",
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        queue = await self._channel.declare_queue("events.queue", durable=True)
        await queue.bind(self._exchange, routing_key="events.created.#")

    async def publish(self, message: dict, routing_key: str = "events.created.web") -> None:
        body = json.dumps(message, default=str).encode()
        msg = aio_pika.Message(
            body=body,
            content_type="application/json",
            message_id=message.get("message_id"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self._exchange.publish(msg, routing_key=routing_key)

    async def close(self):
        if self._channel:
            await self._channel.close()
        if self._connection:
            await self._connection.close()


publisher = MessagePublisher()
"""

# api/schemas/__init__.py
files['api/schemas/__init__.py'] = ""

# api/schemas/message.py
files['api/schemas/message.py'] = """from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime, timezone
import uuid


class Channel(str, Enum):
    web = "web"
    mobile = "mobile"
    email = "email"
    whatsapp = "whatsapp"


class MessageRequest(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=5000)
    channel: Channel = Channel.web
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MessageResponse(BaseModel):
    message_id: str
    status: str
    published_at: datetime
"""

# worker/Dockerfile
files['worker/Dockerfile'] = """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
"""

# worker/requirements.txt
files['worker/requirements.txt'] = """aio-pika==9.4.3
redis==5.0.8
pydantic-settings==2.5.2
"""

# worker/config.py
files['worker/config.py'] = """from pydantic_settings import BaseSettings


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

# tests/test_health.py
files['tests/test_health.py'] = """import httpx


def test_health(api_url):
    r = httpx.get(f"{api_url}/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready(api_url):
    r = httpx.get(f"{api_url}/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}
"""

# tests/test_publish.py
files['tests/test_publish.py'] = """import httpx


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

# Write all files
for fname, content in files.items():
    fpath = os.path.join(base, fname)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, 'w') as f:
        f.write(content)

# Count
count = 0
for root, dirs, filenames in os.walk(base):
    for f in filenames:
        if f.endswith('.pyc') or f == '_fix_files.py':
            continue
        count += 1
print(f"Total project files: {count}")
