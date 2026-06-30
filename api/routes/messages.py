import time
from fastapi import APIRouter, HTTPException, Request
from schemas.message import MessageRequest, MessageResponse
from services.publisher import publisher
from services.idempotency import check_and_set, remove
from datetime import datetime, timezone
from metrics import (
    api_requests_total,
    api_publish_total,
    api_duplicate_total,
    api_publish_failures_total,
    api_request_duration_seconds,
)

router = APIRouter()


@router.post("/api/v1/messages", response_model=MessageResponse, status_code=202)
async def create_message(req: MessageRequest, request: Request):
    start = time.monotonic()

    # 1. Check idempotency — SET NX in Redis
    is_new = await check_and_set(req.message_id)
    if not is_new:
        api_requests_total.labels(endpoint="/api/v1/messages", status="200").inc()
        api_duplicate_total.inc()
        api_request_duration_seconds.labels(endpoint="/api/v1/messages").observe(time.monotonic() - start)
        return MessageResponse(
            message_id=req.message_id,
            status="duplicate",
            duplicate=True,
        )

    # 2. Publish to RabbitMQ
    try:
        routing_key = f"events.created.{req.channel.value}"
        await publisher.publish(req.model_dump(), routing_key=routing_key)
    except Exception:
        api_requests_total.labels(endpoint="/api/v1/messages", status="503").inc()
        api_publish_failures_total.inc()
        api_request_duration_seconds.labels(endpoint="/api/v1/messages").observe(time.monotonic() - start)
        await remove(req.message_id)
        raise HTTPException(status_code=503, detail="Publish failed")

    # 3. Success
    api_requests_total.labels(endpoint="/api/v1/messages", status="200").inc()
    api_publish_total.inc()
    api_request_duration_seconds.labels(endpoint="/api/v1/messages").observe(time.monotonic() - start)
    return MessageResponse(
        message_id=req.message_id,
        status="published",
        published_at=datetime.now(timezone.utc),
    )
