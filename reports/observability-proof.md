# Observability Proof — Grafana + Loki Verification

**Generated:** 2026-06-30
**Status:** ✅ Verified

## Prometheus Targets

Both API and Worker targets are UP and being scraped by Prometheus:

```
Job: api     → Target: api:8000     → Health: UP
Job: worker  → Target: worker:9100  → Health: UP
```

Verify:
```bash
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
```

## Grafana — Provisioned Dashboard

The **Reliability Lab** dashboard is provisioned at:
- `grafana/dashboards/reliability-lab.json`

Dashboard UID: `reliability-lab`

Verify:
```bash
# Check dashboard file exists
ls -la grafana/dashboards/reliability-lab.json

# Check dashboard provisioning config
cat grafana/provisioning/dashboards/dashboard.yml
```

## Grafana — Datasources

### Prometheus Datasource
- **Name:** Prometheus
- **Type:** prometheus
- **URL:** http://prometheus:9090
- **Default:** Yes

Verify:
```bash
curl -s -u admin:admin http://localhost:3000/api/datasources | jq '.[] | {name: .name, type: .type, url: .url}'
```

### Loki Datasource
- **Name:** Loki
- **Type:** loki
- **URL:** http://loki:3100

Verify:
```bash
curl -s -u admin:admin http://localhost:3000/api/datasources | jq '.[] | select(.type=="loki") | {name: .name, type: .type, url: .url}'
```

## Example Metrics to Query

### Via Prometheus (direct)
```bash
# API publish total
curl -s 'http://localhost:9090/api/v1/query?query=api_publish_total' | jq '.data.result[0].value[1]'

# Worker processed total
curl -s 'http://localhost:9090/api/v1/query?query=worker_messages_processed_total' | jq '.data.result[0].value[1]'

# Worker DLQ total
curl -s 'http://localhost:9090/api/v1/query?query=worker_messages_dlq_total' | jq '.data.result[0].value[1]'
```

### Via Grafana (proxy)
```bash
# Grafana proxies Prometheus queries
curl -s -u admin:admin 'http://localhost:3000/api/ds/query' \
  -H 'Content-Type: application/json' \
  -d '{"queries":[{"datasource":{"type":"prometheus","uid":"prometheus"},"expr":"api_publish_total","refId":"A"}],"from":"now-5m","to":"now"}'
```

## Loki Readiness

Loki requires a brief startup period before it accepts queries. The verification script waits up to 60 seconds:

```bash
make observability-verify
```

Expected output:
```
── Loki readiness (waiting up to 60s) ──
  Loki ready after 15.3s: PASS ✅
```

If Loki is already warm from a previous run, it may return instantly:
```
  Loki ready after 0.1s: PASS ✅
```

Manual check:
```bash
curl -s http://localhost:3100/ready
# Expected: "Ready" (when fully started)
# During startup: "Ingester not ready: waiting for 15s after being ready"
```

```bash
# Query Loki directly for worker logs
curl -s -G 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={service="worker"}' \
  --data-urlencode 'limit=5' | jq '.data.result[0].values[:2]'

# Query for error/retry/DLQ logs
curl -s -G 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={service="worker"} |~ "(?i)(error|retry|dlq)"' \
  --data-urlencode 'limit=5' | jq '.data.result'
```

## Dashboard Panels Verified

| Panel | Type | Datasource | Status |
|---|---|---|---|
| API — Publish & Duplicate Rate | timeseries | Prometheus | ✅ |
| Worker — Processed / Retry / DLQ Rate | timeseries | Prometheus | ✅ |
| API Publish Total | stat | Prometheus | ✅ |
| Worker Processed Total | stat | Prometheus | ✅ |
| Worker DLQ Total | stat | Prometheus | ✅ |
| Worker Retry Total | stat | Prometheus | ✅ |
| ES Index Failures Total | stat | Prometheus | ✅ |
| API Duplicate Total | stat | Prometheus | ✅ |
| Latency — API & Worker (avg) | timeseries | Prometheus | ✅ |
| Logs — Worker & API (errors/retries/DLQ) | logs | Loki | ✅ |
| Logs — Worker & API (all) | logs | Loki | ✅ |

## Honest Limitations

- **Loki log collection** depends on Docker socket access; on macOS Docker Desktop, log volume may be limited
- **Promtail** may miss logs during container restarts
- **No alerting rules** are provisioned — this is a dashboard-only setup
- **Grafana is unauthenticated** (anonymous viewer access) — not suitable for production without auth
- **Loki uses local storage** — not suitable for production log retention
