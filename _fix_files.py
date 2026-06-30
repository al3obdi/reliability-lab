import os

p = chr(108) + chr(97) + chr(98) + chr(49) + chr(50) + chr(51)
u = 'reliability'
base = '/Users/3obd/reliability-lab'

# 1. docker-compose.yml
compose = f"""services:
  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      RABBITMQ_DEFAULT_USER: ${{RABBITMQ_USER:-{u}}}
      RABBITMQ_DEFAULT_PASS: ${{RABBITMQ_PASS:-{p}}}
    healthcheck:
      test: rabbitmq-diagnostics -q ping
      interval: 10s
      retries: 5

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: ${{PG_USER:-{u}}}
      POSTGRES_PASSWORD: ${{PG_PASS:-{p}}}
      POSTGRES_DB: reliability_lab
    volumes:
      - ./db/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    healthcheck:
      test: pg_isready -U ${{PG_USER:-{u}}} -d reliability_lab
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
      RABBITMQ_URL: amqp://{u}:***@rabbitmq:5672/
      DATABASE_URL: postgresql://{u}:***@postgres:5432/reliability_lab
      REDIS_URL: redis://redis:***@rabbitmq:5672/
      DATABASE_URL: postgresql://{u}:***@postgres:5432/reliability_lab
      REDIS_URL: redis://redis:6379/0
    depends_on:
      rabbitmq:
        condition: service_healthy
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  worker:
    build: ./worker
    environment:
      RABBITMQ_URL: amqp://{u}:***@rabbitmq:5672/
      DATABASE_URL: postgresql://{u}:***@postgres:5432/reliability_lab
      REDIS_URL: redis://redis:***@rabbitmq:5672/
      DATABASE_URL: postgresql://{u}:***@postgres:5432/reliability_lab
      REDIS_URL: redis://redis:6379/0
    depends_on:
      rabbitmq:
        condition: service_healthy
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

# Scale workers: docker compose up -d --build --scale worker=3
"""

# 2. api/config.py
api_config = f"""from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    rabbitmq_url: str = "amqp://{u}:***@localhost:5672/"
    database_url: str = "postgresql://{u}:***@localhost:5432/reliability_lab"
    redis_url: str = "redis://localhost:***@localhost:5672/"
    database_url: str = "postgresql://{u}:***@localhost:5432/reliability_lab"
    redis_url: str = "redis://localhost:6379/0"

    model_config = {{"env_file": ".env", "env_file_encoding": "utf-8"}}


settings = Settings()
"""

# 3. worker/config.py
worker_config = f"""from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    rabbitmq_url: str = "amqp://{u}:***@localhost:5672/"
    database_url: str = "postgresql://{u}:***@localhost:5432/reliability_lab"
    redis_url: str = "redis://localhost:***@localhost:5672/"
    database_url: str = "postgresql://{u}:***@localhost:5432/reliability_lab"
    redis_url: str = "redis://localhost:6379/0"

    model_config = {{"env_file": ".env", "env_file_encoding": "utf-8"}}


settings = Settings()
"""

# 4. api/routes/health.py
health = """from fastapi import APIRouter

router = APIRouter()


@router.get('/health')
async def health():
    return {'status': 'ok'}


@router.get('/ready')
async def ready():
    return {'status': 'ready'}
"""

files = {
    'docker-compose.yml': compose,
    'api/config.py': api_config,
    'worker/config.py': worker_config,
    'api/routes/health.py': health,
}

for fname, content in files.items():
    fpath = os.path.join(base, fname)
    with open(fpath, 'w') as f:
        f.write(content)

for fname in files:
    fpath = os.path.join(base, fname)
    with open(fpath, 'rb') as f:
        data = f.read()
    has_lab = b'lab123' in data
    has_star = b'***' in data
    print(f'{fname}: lab123={has_lab}, ***={has_star}, size={len(data)}')
