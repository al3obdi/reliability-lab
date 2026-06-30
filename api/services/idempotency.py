import redis.asyncio as aioredis
from config import settings

_redis: aioredis.Redis | None = None

IDEMPOTENCY_TTL = 86400  # 24 hours


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def check_and_set(message_id: str) -> bool:
    """Try to set an idempotency key. Returns True if this is the first
    time (key was set), False if it already exists (duplicate)."""
    r = await get_redis()
    key = f"idempotency:{message_id}"
    # SET NX: only set if key does not exist
    was_set = await r.set(key, "1", nx=True, ex=IDEMPOTENCY_TTL)
    return bool(was_set)


async def remove(message_id: str) -> None:
    """Remove the idempotency key. Used when publish fails after SETNX succeeded."""
    r = await get_redis()
    key = f"idempotency:{message_id}"
    await r.delete(key)


async def close():
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
