import asyncpg
from config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
        )
    return _pool


async def insert_message(message_id: str, customer_id: str, text: str, channel: str) -> bool:
    """Insert a message into PostgreSQL. Returns True if inserted, False if duplicate."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            INSERT INTO messages (message_id, customer_id, text, text_normalized, channel, status)
            VALUES ($1, $2, $3, $3, $4, 'completed')
            ON CONFLICT (message_id) DO NOTHING
            """,
            message_id, customer_id, text, channel,
        )
        inserted = "INSERT 0 1" in result
        return inserted


async def mark_indexed(message_id: str) -> None:
    """Set index_status='indexed' for a message."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE messages SET index_status = 'indexed' WHERE message_id = $1",
            message_id,
        )


async def mark_index_failed(message_id: str, error: str) -> None:
    """Set index_status='failed' and record the error."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE messages SET index_status = 'failed', index_error = $2 WHERE message_id = $1",
            message_id, error,
        )


async def get_failed_index_rows(limit: int = 100) -> list[dict]:
    """Return rows where index_status='failed' for reindexing."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT message_id, customer_id, text, text_normalized, channel, status,
                   created_at::text AS created_at
            FROM messages
            WHERE index_status = 'failed'
            ORDER BY created_at
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
