"""Elasticsearch service — derived search store.

PostgreSQL is the source of truth. Elasticsearch is a rebuildable index.
ES failures do NOT cause message requeue.
"""

from elasticsearch import AsyncElasticsearch
from config import settings

_client: AsyncElasticsearch | None = None

INDEX_NAME = "messages-v1"

INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "arabic_friendly": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "arabic_normalization"],
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "message_id":    {"type": "keyword"},
            "customer_id":   {"type": "keyword"},
            "text":          {"type": "text", "analyzer": "arabic_friendly"},
            "text_normalized": {"type": "text", "analyzer": "arabic_friendly"},
            "channel":       {"type": "keyword"},
            "status":        {"type": "keyword"},
            "created_at":    {"type": "date"},
        }
    },
}


async def get_client() -> AsyncElasticsearch:
    global _client
    if _client is None:
        _client = AsyncElasticsearch(settings.elasticsearch_url)
    return _client


async def ensure_index() -> None:
    """Create the messages-v1 index if it does not exist."""
    client = await get_client()
    exists = await client.indices.exists(index=INDEX_NAME)
    if not exists:
        await client.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)
        print(f"[ES] Created index: {INDEX_NAME}", flush=True)
    else:
        print(f"[ES] Index already exists: {INDEX_NAME}", flush=True)


async def index_message(
    message_id: str,
    customer_id: str,
    text: str,
    text_normalized: str,
    channel: str,
    status: str = "completed",
    created_at: str | None = None,
) -> None:
    """Index a message document in Elasticsearch. Uses message_id as _id for idempotent upserts."""
    client = await get_client()
    doc = {
        "message_id": message_id,
        "customer_id": customer_id,
        "text": text,
        "text_normalized": text_normalized,
        "channel": channel,
        "status": status,
    }
    if created_at:
        # Normalize PostgreSQL timestamp to ISO 8601 for Elasticsearch
        # PG returns: "2026-06-30 08:28:42.760888+00" — ES needs "+00:00" or "Z"
        normalized = created_at.replace(" ", "T")
        if normalized.endswith("+00"):
            normalized = normalized[:-3] + "+00:00"
        doc["created_at"] = normalized

    await client.index(index=INDEX_NAME, id=message_id, document=doc, refresh=True)


async def get_document(message_id: str) -> dict | None:
    """Retrieve a document by message_id. Returns None if not found."""
    client = await get_client()
    try:
        result = await client.get(index=INDEX_NAME, id=message_id)
        return result["_source"]
    except Exception:
        return None


async def close_client() -> None:
    global _client
    if _client:
        await _client.close()
        _client = None
