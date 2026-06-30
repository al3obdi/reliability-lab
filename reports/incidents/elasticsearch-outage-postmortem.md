# Incident Postmortem: Elasticsearch Outage — Graceful Degradation + Reindex Recovery

**Incident ID:** INC-002
**Date:** 2026-06-30 (simulated)
**Severity:** Medium
**Duration:** Variable (until reindex completes)
**Status:** Resolved — index rebuilt from PostgreSQL via reindex script

## Summary

Elasticsearch became unavailable while the worker was processing messages. Per the architecture's design principle — "Elasticsearch is derived and rebuildable" — the worker continued processing messages normally. PostgreSQL persisted all messages with `index_status='failed'`. The worker ACKed messages after PG confirmation; ES failures never triggered retries or DLQ routing.

Once Elasticsearch was restored, the `reindex_failed.py` script rebuilt the index from PostgreSQL, recovering all documents that failed to index during the outage.

No messages were lost. No processing was blocked. The critical path (API → RabbitMQ → Worker → PostgreSQL) was completely unaffected.

## Impact

- **User-facing:** None — API and message processing continued normally
- **Search availability:** Search results incomplete during outage (documents missing from ES)
- **Data integrity:** Zero data loss — all messages persisted in PostgreSQL with `index_status='failed'`
- **Recovery time:** Depends on number of failed documents; reindex processes in batches

## Detection

- **Prometheus alert:** `worker_es_index_failed_total` counter incrementing
- **PostgreSQL query:** `SELECT COUNT(*) FROM messages WHERE index_status = 'failed'`
- **Worker logs:** "Elasticsearch index failed for message_id=..., index_status set to 'failed'"
- **ES health:** `/_cluster/health` returning "unreachable" or "red"

## Timeline

| Time | Event |
|------|-------|
| T+0s | Elasticsearch container stopped (simulated outage) |
| T+0s | Worker attempts ES index → failure → sets `index_status='failed'` → ACKs message |
| T+5m | Operator notices `worker_es_index_failed_total` incrementing |
| T+10m | Elasticsearch restarted, cluster health returns to green |
| T+10m | Operator runs `reindex_failed.py` |
| T+12m | All failed documents reindexed, `index_status` updated to 'indexed' |

## Root Cause

Elasticsearch was unavailable (simulated container stop). The architecture correctly treated this as a non-critical failure — ES is a derived store, not the source of truth. The worker's design (ACK after PG, best-effort ES indexing) prevented this from becoming a data-loss incident.

## Mitigation

1. **Immediate:** Restart Elasticsearch (`docker compose start elasticsearch`)
2. **Recovery:** Run `docker exec reliability-lab-worker-1 python /scripts/reindex_failed.py`
3. **Verification:** Confirm `index_status='indexed'` for previously-failed documents
4. **Search validation:** Query ES for a sample of recovered documents

## Prevention

- **ES replication:** Multi-node cluster with replicas (production)
- **Health-aware indexing:** Worker could buffer index operations when ES is unhealthy (adds complexity)
- **Scheduled reindex:** Cron job that periodically reindexes `index_status='failed'` documents
- **Alerting:** Alert when `worker_es_index_failed_total` rate exceeds threshold

## Metrics to Watch

| Metric | Normal | Warning | Critical |
|--------|--------|---------|----------|
| `worker_es_index_failed_total` rate | 0 | > 5/min | > 50/min |
| `messages WHERE index_status='failed'` | 0 | > 10 | > 100 |
| ES cluster health | green | yellow | red/unreachable |
| `worker_es_index_total` rate | > 0 | — | flatline (ES down) |

## Runbook Commands

```bash
# Check ES health
curl -s http://localhost:9200/_cluster/health | jq .

# Count failed index operations
docker exec reliability-lab-postgres-1 psql -U reliability -d reliability_lab \
  -c "SELECT COUNT(*) FROM messages WHERE index_status = 'failed'"

# Reindex all failed documents
docker exec reliability-lab-worker-1 python /scripts/reindex_failed.py

# Verify recovery
docker exec reliability-lab-postgres-1 psql -U reliability -d reliability_lab \
  -c "SELECT COUNT(*) FROM messages WHERE index_status = 'indexed'"

# Check ES document count
curl -s http://localhost:9200/messages-v1/_count | jq .count

# Compare PG vs ES counts (should match after reindex)
docker exec reliability-lab-postgres-1 psql -U reliability -d reliability_lab \
  -t -A -c "SELECT COUNT(*) FROM messages WHERE index_status = 'indexed'"
```

## What This Project Proves

1. **Derived stores don't block the critical path:** ES failure never causes message loss or processing delays
2. **Source of truth pattern works:** PostgreSQL is the authoritative store; ES is always rebuildable
3. **Reindex recovery is practical:** The `reindex_failed.py` script provides a clear recovery path
4. **Observability tracks degradation:** `index_status` column + `worker_es_index_failed_total` counter provide full visibility
5. **Graceful degradation:** Search is degraded during ES outage, but message processing continues unaffected
