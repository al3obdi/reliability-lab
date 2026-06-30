# SLO and Incident Readiness

**Status:** Readiness evidence — proposed SLOs, not contractual commitments.

This document proposes Service Level Objectives (SLOs) for the Reliability Lab
pipeline, maps them to existing Prometheus metrics, and defines an incident
response workflow. It demonstrates SLO-driven engineering thinking without
claiming production SLO compliance.

## Proposed SLOs

### SLO-1: API Availability

| Field | Value |
|---|---|
| **SLI** | Proportion of successful requests (2xx) to total requests |
| **SLO** | 99.9% availability over 28-day rolling window |
| **Error budget** | 0.1% = ~40 minutes/month of acceptable downtime |
| **Prometheus metric** | `api_requests_total{status=~"2.."}` / `api_requests_total` |

**Rationale:** The API is the entry point. If it's down, no messages enter the pipeline.
99.9% is achievable for a well-architected service with redundancy.

### SLO-2: API Publish Latency

| Field | Value |
|---|---|
| **SLI** | 99th percentile latency of POST /api/v1/messages |
| **SLO** | p99 < 200ms over 28-day rolling window |
| **Error budget** | 1% of requests may exceed 200ms |
| **Prometheus metric** | `histogram_quantile(0.99, api_request_duration_seconds_bucket)` |

**Rationale:** The API does Redis SET NX + RabbitMQ publish. Both are O(1) operations.
200ms is generous for this workload.

### SLO-3: Processing Completion Latency

| Field | Value |
|---|---|
| **SLI** | 99th percentile time from publish to PostgreSQL persistence |
| **SLO** | p99 < 5s over 28-day rolling window |
| **Error budget** | 1% of messages may take > 5s |
| **Prometheus metric** | `histogram_quantile(0.99, worker_processing_duration_seconds_bucket)` |

**Rationale:** The worker does PG INSERT + ES index. Under normal conditions this is
sub-second. 5s allows for transient PG/ES slowdowns without alerting.

### SLO-4: DLQ Rate

| Field | Value |
|---|---|
| **SLI** | Proportion of messages routed to DLQ vs total processed |
| **SLO** | < 0.1% DLQ rate over 28-day rolling window |
| **Error budget** | 0.1% of messages may be dead-lettered |
| **Prometheus metric** | `rate(worker_messages_dlq_total[28d])` / `rate(worker_messages_processed_total[28d])` |

**Rationale:** DLQ means the pipeline gave up after 3 retries. This should be rare.
A spike indicates a systemic problem (PG outage, schema mismatch, poison message flood).

### SLO-5: Retry Rate

| Field | Value |
|---|---|
| **SLI** | Proportion of messages retried vs total processed |
| **SLO** | < 1% retry rate over 28-day rolling window |
| **Error budget** | 1% of messages may be retried |
| **Prometheus metric** | `rate(worker_messages_retried_total[28d])` / `rate(worker_messages_processed_total[28d])` |

**Rationale:** Retries mean transient failures. Some retries are normal (PG connection
blips). A sustained spike means something is wrong.

### SLO-6: Elasticsearch Indexing Failure Rate

| Field | Value |
|---|---|
| **SLI** | Proportion of ES index failures vs total index attempts |
| **SLO** | < 5% failure rate over 28-day rolling window |
| **Error budget** | 5% of index operations may fail |
| **Prometheus metric** | `rate(worker_es_index_failed_total[28d])` / `rate(worker_es_index_total[28d])` |

**Rationale:** ES is derived and non-critical. A higher error budget is acceptable
because ES failures don't cause data loss. But sustained failures mean the reindex
recovery path is needed.

## Error Budget Explanation

An **error budget** is the amount of acceptable failure before the SLO is violated.

- **SLO = 99.9% availability** → error budget = 0.1%
- Over 28 days (40,320 minutes): 0.1% = ~40 minutes of downtime
- If the API is down for 20 minutes in a month, 50% of the error budget is consumed
- If the error budget is exhausted, the team should **freeze feature releases** and
  focus on reliability improvements

**Error budget policy (proposed):**

| Budget Remaining | Action |
|---|---|
| > 50% | Normal operations — ship features |
| 25-50% | Caution — prioritize reliability work over features |
| < 25% | Freeze — no feature releases until budget recovers |
| 0% (exhausted) | Incident — all hands on reliability |

## Prometheus Metric Mapping

### API Metrics (port 8000, /metrics)

| Metric | Type | Maps to SLO |
|---|---|---|
| `api_requests_total` | Counter (by endpoint, status) | SLO-1 (availability) |
| `api_publish_total` | Counter | SLO-1 (publish success) |
| `api_duplicate_total` | Counter | — (informational) |
| `api_publish_failures_total` | Counter | SLO-1 (publish failure) |
| `api_request_duration_seconds` | Histogram | SLO-2 (publish latency) |

### Worker Metrics (port 9100, /metrics)

| Metric | Type | Maps to SLO |
|---|---|---|
| `worker_messages_processed_total` | Counter | SLO-3, SLO-4, SLO-5 (denominator) |
| `worker_messages_failed_total` | Counter | — (informational) |
| `worker_messages_retried_total` | Counter | SLO-5 (retry rate) |
| `worker_messages_dlq_total` | Counter | SLO-4 (DLQ rate) |
| `worker_pg_insert_total` | Counter | SLO-3 (processing success) |
| `worker_es_index_total` | Counter | SLO-6 (denominator) |
| `worker_es_index_failed_total` | Counter | SLO-6 (ES failure rate) |
| `worker_processing_duration_seconds` | Histogram | SLO-3 (processing latency) |

## Alert Examples

These are Prometheus alerting rules (PromQL expressions). In production, they would
be configured in Prometheus Alertmanager or a managed alerting service.

### Alert: High DLQ Rate

```promql
rate(worker_messages_dlq_total[5m]) / rate(worker_messages_processed_total[5m]) > 0.01
```

**Severity:** Critical
**Meaning:** More than 1% of messages are being dead-lettered in the last 5 minutes.
**Response:** Check PostgreSQL health, worker logs, DLQ contents (`make inspect-dlq`).

### Alert: Retry Rate Spike

```promql
rate(worker_messages_retried_total[5m]) / rate(worker_messages_processed_total[5m]) > 0.05
```

**Severity:** Warning
**Meaning:** More than 5% of messages are being retried.
**Response:** Check PostgreSQL connection pool, network latency, resource saturation.

### Alert: ES Indexing Failure Spike

```promql
rate(worker_es_index_failed_total[5m]) / rate(worker_es_index_total[5m]) > 0.10
```

**Severity:** Warning
**Meaning:** More than 10% of ES index operations are failing.
**Response:** Check ES cluster health, disk space, memory pressure. Run reindex if needed.

### Alert: API Publish Failure Rate

```promql
rate(api_publish_failures_total[5m]) / rate(api_publish_total[5m]) > 0.01
```

**Severity:** Critical
**Meaning:** More than 1% of publish attempts are failing.
**Response:** Check RabbitMQ health, connection pool, network.

### Alert: Worker Processing Latency High

```promql
histogram_quantile(0.99, rate(worker_processing_duration_seconds_bucket[5m])) > 10
```

**Severity:** Warning
**Meaning:** p99 processing latency exceeds 10 seconds.
**Response:** Check PG query performance, ES indexing latency, worker resource saturation.

### Alert: API Availability (Error Budget Burn)

```promql
sum(rate(api_requests_total{status!~"2.."}[1h])) / sum(rate(api_requests_total[1h])) > 0.001
```

**Severity:** Critical
**Meaning:** Error rate exceeds 0.1% over the last hour — error budget burning fast.
**Response:** Investigate immediately. If sustained, freeze feature releases.

## Incident Response Workflow

This is a proposed incident response workflow based on industry practices
(Google SRE, PagerDuty, incident.io).

### Phase 1: Detect

- Prometheus alert fires → PagerDuty/Opsgenie notification
- Or: engineer notices anomaly in Grafana dashboard
- Or: `make verify-slos` shows SLO violation

### Phase 2: Triage

1. **Acknowledge the alert** — who is the incident commander?
2. **Check the dashboard** — Grafana Reliability Lab dashboard shows all metrics
3. **Check recent changes** — any deploys, config changes, or infrastructure changes?
4. **Determine scope** — is this affecting all messages or a subset?
5. **Declare severity** — Sev1 (critical, all hands), Sev2 (major, team), Sev3 (minor, on-call)

### Phase 3: Mitigate

1. **Stop the bleeding** — don't find root cause yet, just stop the damage
   - API down? Restart API pods.
   - DLQ flooding? Check PG, consider pausing worker.
   - ES failures? ES is non-critical — let it fail, fix later.
2. **Communicate** — update status page, notify stakeholders
3. **Preserve evidence** — logs, metrics snapshots, queue states

### Phase 4: Recover

1. **Restore service** — bring systems back to normal
2. **Verify recovery** — run `make portfolio-verify` or targeted health checks
3. **Drain backlog** — if messages queued up, let worker catch up
4. **Reindex if needed** — `make reindex-failed` for ES recovery

### Phase 5: Prevent

1. **Write a postmortem** — use the template from existing postmortems:
   - [`reports/incidents/postgres-outage-postmortem.md`](reports/incidents/postgres-outage-postmortem.md)
   - [`reports/incidents/elasticsearch-outage-postmortem.md`](reports/incidents/elasticsearch-outage-postmortem.md)
   - [`reports/incidents/poison-message-dlq-postmortem.md`](reports/incidents/poison-message-dlq-postmortem.md)
2. **Create action items** — what will prevent this from happening again?
3. **Update runbooks** — add new diagnostic commands, recovery procedures
4. **Review SLOs** — does this incident suggest the SLO is too tight or too loose?

## Runbook Commands

```bash
# Check overall system health
make portfolio-verify

# Check DLQ contents
make inspect-dlq

# Check SLO compliance
make verify-slos

# Reindex failed ES documents
make reindex-failed

# Check queue depths
docker exec reliability-lab-rabbitmq-1 rabbitmqctl list_queues name messages

# Check worker logs for errors
docker compose logs worker | grep -i error

# Check API metrics
curl -s http://localhost:8000/metrics | grep -E 'api_publish|api_duplicate|api_publish_failures'

# Check worker metrics
curl -s http://localhost:9100/metrics | grep -E 'worker_messages|worker_es'
```

## Honest Positioning

These SLOs are proposed targets based on the architecture's design characteristics.
They have not been validated against production traffic because this is a local
reliability lab, not a production service. The alert expressions are syntactically
valid PromQL but have not been tested against real alerting pipelines. The incident
response workflow follows industry best practices but has not been exercised in a
real incident.
