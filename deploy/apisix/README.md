# APISIX Gateway Readiness Pack

**Status:** Readiness evidence — not a deployed gateway.

This directory contains example APISIX configuration demonstrating how an API gateway
would sit in front of the Reliability Lab API. These are **example route definitions**
for portfolio and interview purposes. They are not required for local development.

## What APISIX Does

Apache APISIX is a cloud-native API gateway that handles:

- **Routing** — direct traffic to the correct upstream service
- **Health checks** — detect unhealthy upstreams and route around them
- **Rate limiting** — protect services from abuse
- **Request size limits** — prevent oversized payloads
- **Traffic splitting** — canary deployments and blue/green releases
- **Authentication** — API keys, JWT validation, OAuth
- **Observability** — Prometheus metrics, logging, tracing

## How APISIX Maps to Enterprise API Gateway Concerns

| Concern | APISIX Feature | Example in This Pack |
|---|---|---|
| **Routing** | Routes + Upstreams | Route POST `/api/v1/messages` → API service |
| **Health checks** | Active/Passive health checks | Upstream health check on `/health` |
| **Rate limiting** | limit-count / limit-req plugins | 100 req/s per consumer |
| **Request size** | client-control plugin | Max body size 1MB |
| **Traffic splitting** | weighted upstream nodes | 90% stable, 10% canary |
| **Environment isolation** | Route-level service discovery | Different upstreams per environment |

## Architecture

```
Internet / Internal Network
        │
        ▼
┌───────────────┐
│   APISIX       │  ← API Gateway (port 9080)
│   Gateway      │
└───────┬───────┘
        │ route matching
        ▼
┌───────────────┐
│   FastAPI      │  ← Upstream service (api:8000)
│   (api/)       │
└───────────────┘
```

## Files

| File | Purpose |
|---|---|
| `routes.example.yaml` | APISIX route definitions with plugin examples |
| `docker-compose.apisix.example.yml` | Lightweight APISIX + etcd for local experimentation |

## Quick Local Experiment

```bash
# Start APISIX + etcd (standalone, does not require the main stack)
docker compose -f deploy/apisix/docker-compose.apisix.example.yml up -d

# Create a route
curl -s http://localhost:9180/apisix/admin/routes/1 \
  -H 'X-API-KEY: edd1c9f034335f136f87ad84b625c8f1' \
  -X PUT -d '{
    "uri": "/api/v1/messages",
    "methods": ["POST"],
    "upstream": {
      "type": "roundrobin",
      "nodes": { "host.docker.internal:8000": 1 }
    }
  }'

# Test through the gateway
curl -s -X POST http://localhost:9080/api/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{"message_id":"...","customer_id":"cust-001","text":"test","channel":"web"}'

# Clean up
docker compose -f deploy/apisix/docker-compose.apisix.example.yml down
```

## Honest Positioning

This is an example configuration showing that I understand API gateway patterns —
routing, health checks, rate limiting, traffic splitting, and the role of a gateway
in production architecture. It is not a production APISIX deployment.
