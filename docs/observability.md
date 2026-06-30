# Observability — Optional Grafana + Loki Profile

The Reliability Lab includes an **optional** observability profile that adds Grafana dashboards and Loki log exploration on top of the default stack. It is not required for normal operation.

## Quick Start

```bash
# 1. Start the default stack (if not already running)
make up

# 2. Start the optional observability stack
make observability-up

# 3. Open Grafana
open http://localhost:3000
```

**Default credentials:** `admin` / `admin` (anonymous viewer access is enabled)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Default Stack (make up)                            │
│                                                     │
│  API ──▶ RabbitMQ ──▶ Worker ──▶ PostgreSQL        │
│   │                      │         │                │
│   │                      │         └── Elasticsearch│
│   ▼                      ▼                          │
│  Prometheus ◀── scrape ──┘                          │
│  :9090                                               │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│  Observability Profile (make observability-up)      │
│                                                     │
│  Grafana ◀── Prometheus (datasource)                │
│  :3000    ◀── Loki (datasource)                     │
│                ▲                                     │
│  Promtail ─────┘ (Docker log collector)             │
│  Loki :3100                                          │
└─────────────────────────────────────────────────────┘
```

## Services

| Service | Port | Purpose |
|---|---|---|
| **Grafana** | 3000 | Dashboards, Prometheus queries, log exploration |
| **Loki** | 3100 | Log aggregation and storage |
| **Promtail** | — | Collects Docker container logs, ships to Loki |

## Dashboard

The **Reliability Lab** dashboard is provisioned automatically and includes:

### Rate Panels (timeseries)
- **API — Publish & Duplicate Rate** — `rate(api_publish_total[1m])`, `rate(api_duplicate_total[1m])`
- **Worker — Processed / Retry / DLQ Rate** — `rate(worker_messages_processed_total[1m])`, retry rate, DLQ rate
- **Latency — API & Worker (avg)** — average request and processing duration

### Counter Panels (stat)
- API Publish Total
- Worker Processed Total
- Worker DLQ Total
- Worker Retry Total
- ES Index Failures Total
- API Duplicate Total

### Log Panels
- **Logs — Worker & API (errors/retries/DLQ)** — filtered to `error|fail|retry|dlq`
- **Logs — Worker & API (all)** — all container logs

## Metrics to Inspect

| What to Check | PromQL Query |
|---|---|
| Publish throughput | `rate(api_publish_total[1m])` |
| Duplicate rate | `rate(api_duplicate_total[1m])` |
| Worker processing rate | `rate(worker_messages_processed_total[1m])` |
| Retry rate (transient failures) | `rate(worker_messages_retried_total[1m])` |
| DLQ rate (permanent failures) | `rate(worker_messages_dlq_total[1m])` |
| ES indexing failure rate | `rate(worker_es_index_failed_total[1m])` |
| API latency (p90) | `histogram_quantile(0.9, rate(api_request_duration_seconds_bucket[1m]))` |
| Worker latency (p90) | `histogram_quantile(0.9, rate(worker_processing_duration_seconds_bucket[1m]))` |

## Inspecting Worker Retry/DLQ Logs

In Grafana, use the **Explore** tab with the Loki datasource:

```logql
# All worker logs
{service="worker"}

# Worker errors and retries
{service="worker"} |~ "(?i)(error|fail|retry|dlq)"

# API errors
{service="api"} |~ "(?i)(error|fail|503)"

# DLQ routing events
{service="worker"} |~ "routing to DLQ"
```

## How Prometheus, Grafana, and Loki Fit Together

1. **Prometheus** scrapes `/metrics` from the API (:8000) and Worker (:9100) every 15s. It stores time-series data (counters, histograms).
2. **Grafana** queries Prometheus for dashboards and alerting. It also queries Loki for log exploration.
3. **Loki** receives logs from Promtail, indexes them by labels (container, service), and serves them to Grafana.
4. **Promtail** tails Docker container logs via the Docker socket and ships them to Loki.

## Honest Limitations

### Docker Log Collection on macOS
Promtail uses the Docker socket (`/var/run/docker.sock`) to discover containers and collect logs. On macOS (Docker Desktop), this works but has limitations:
- Log volume depends on the Docker Desktop log driver (`json-file` by default)
- Container restarts may cause brief gaps in log collection
- File-based log scraping (accessing container filesystems directly) is not reliable on macOS

### Loki is Minimal
This setup uses Loki's single-binary mode with local storage. It is suitable for local development and demonstration. Production Loki deployments use object storage (S3/GCS) and separate read/write paths.

### Grafana is Unauthenticated
Anonymous viewer access is enabled for convenience. In production, configure OAuth, LDAP, or at minimum change the default admin password.

### No Alerting Configured
The dashboard shows metrics but does not include alert rules. Grafana alerting can be added by provisioning alert rules in `grafana/provisioning/alerting/`.

## Stopping the Observability Stack

```bash
# Stop only the observability services (Grafana, Loki, Promtail)
make observability-down

# The default stack (API, Worker, RabbitMQ, etc.) continues running
```

## File Layout

```
grafana/
├── provisioning/
│   ├── datasources/
│   │   ├── prometheus.yml    # Prometheus datasource config
│   │   └── loki.yml          # Loki datasource config
│   └── dashboards/
│       └── dashboard.yml     # Dashboard provider config
├── dashboards/
│   └── reliability-lab.json  # Provisioned dashboard
docker-compose.observability.yml  # Optional compose file
promtail-config.yml                # Promtail log collection config
```
