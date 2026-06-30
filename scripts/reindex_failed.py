"""Reindex failed Elasticsearch documents from PostgreSQL.

Usage:
    python scripts/reindex_failed.py

Reads rows where index_status='failed' from PostgreSQL and reindexes them
into Elasticsearch. On success, updates index_status to 'indexed'.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from services.postgres import get_pool, get_failed_index_rows, mark_indexed, mark_index_failed, close_pool
from services.elasticsearch import get_client, ensure_index, index_message, close_client


async def reindex_failed(limit: int = 100) -> int:
    """Reindex failed rows. Returns count of successfully reindexed."""
    await ensure_index()
    rows = await get_failed_index_rows(limit=limit)

    if not rows:
        print("[REINDEX] No failed rows found.", flush=True)
        return 0

    print(f"[REINDEX] Found {len(rows)} failed rows.", flush=True)
    success = 0

    for row in rows:
        msg_id = row["message_id"]
        try:
            await index_message(
                message_id=msg_id,
                customer_id=row["customer_id"],
                text=row["text"],
                text_normalized=row["text_normalized"] or row["text"],
                channel=row["channel"],
                status=row["status"],
                created_at=row.get("created_at"),
            )
            await mark_indexed(msg_id)
            success += 1
            print(f"[REINDEX] OK: {msg_id}", flush=True)
        except Exception as exc:
            error_str = str(exc)[:500]
            await mark_index_failed(msg_id, error_str)
            print(f"[REINDEX] FAIL: {msg_id} — {error_str}", flush=True)

    print(f"[REINDEX] Done: {success}/{len(rows)} succeeded.", flush=True)
    return success


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    count = asyncio.run(reindex_failed(limit=limit))
    asyncio.run(close_pool())
    asyncio.run(close_client())
    sys.exit(0 if count > 0 else 0)
