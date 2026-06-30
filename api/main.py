from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import Response
from routes import health, messages
from services.publisher import publisher
from metrics import get_metrics


@asynccontextmanager
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


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=get_metrics(), media_type="text/plain")
