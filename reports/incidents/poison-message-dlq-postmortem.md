# Incident Postmortem: Poison Message → Immediate DLQ Routing

**Incident ID:** INC-003
**Date:** 2026-06-30 (simulated)
**Severity:** Low
**Duration:** Instantaneous (single message)
**Status:** Resolved — poison message isolated in DLQ, no retry churn

## Summary

A malformed message (invalid JSON payload, missing required fields) was published directly to RabbitMQ, bypassing the API's validation layer. The worker attempted to process it, failed immediately due to schema validation, and — critically — routed it directly to the Dead Letter Queue **without retrying**.

This is the correct behavior: poison messages (messages that will never succeed regardless of retries) should not consume retry capacity. The worker distinguishes between transient failures (PG down → retry) and permanent failures (invalid payload → DLQ immediately).

## Impact

- **User-facing:** None — single malformed message isolated
- **System health:** No impact — no retry churn, no queue buildup
- **Data integrity:** No data loss — message captured in DLQ with error metadata
- **DLQ:** One additional message in `events.dlq`

## Detection

- **Prometheus alert:** `worker_messages_dlq_total` counter incremented
- **DLQ depth:** `events.dlq` message count increased by 1
- **Worker logs:** "Invalid message payload, routing to DLQ: missing required field 'message_id'"

## Root Cause

A message with invalid structure was published directly to RabbitMQ (bypassing the API's Pydantic validation). The worker's processor correctly identified the payload as permanently invalid and routed it to DLQ without retries.

This is **expected behavior** — the system is designed to distinguish between:
- **Transient failures** (PG down, network blip) → retry with backoff
- **Permanent failures** (invalid payload, schema mismatch) → DLQ immediately

## Mitigation

1. **Immediate:** Inspect the DLQ message to understand the invalid payload
2. **Source fix:** Identify and fix the publisher that sent the malformed message
3. **Purge:** After review, purge the poison message from DLQ

## Prevention

- **API validation:** All messages should go through the API's Pydantic validation (this message bypassed it)
- **Schema registry:** Maintain a message schema registry; reject messages that don't conform
- **Publisher authentication:** Require API keys to prevent unauthorized publishers from injecting malformed messages
- **DLQ monitoring:** Alert when DLQ receives messages with `error_type='ValidationError'` — these indicate publisher bugs

## Metrics to Watch

| Metric | Normal | Warning | Critical |
|--------|--------|---------|----------|
| `worker_messages_dlq_total` (validation errors) | 0 | > 1/hour | > 10/hour |
| `events.dlq` depth | 0 | > 0 | > 10 |
| `worker_messages_retried_total` for invalid messages | 0 | > 0 | > 0 (should never retry) |

## Runbook Commands

```bash
# Inspect DLQ for poison messages
make inspect-dlq ARGS="--peek 10"

# Look for validation errors in DLQ messages
# (manually review the JSON output for "error_type": "ValidationError")

# Purge specific poison messages after review
make inspect-dlq ARGS="--purge"

# Check how many messages were DLQ'd without retries
curl -s http://localhost:9100/metrics | grep worker_messages_dlq_total

# Verify no retry churn for poison messages
curl -s http://localhost:9100/metrics | grep worker_messages_retried_total
```

## What This Project Proves

1. **Poison message detection:** The worker distinguishes transient from permanent failures
2. **No retry waste:** Invalid messages don't consume retry capacity — they go straight to DLQ
3. **DLQ as isolation mechanism:** Poison messages are isolated, not silently dropped
4. **Error metadata:** DLQ messages carry full error context for operator debugging
5. **Defense in depth:** API validation is the first line; worker validation is the safety net for messages that bypass the API
