# Cloud Deployment Map

**Status:** Readiness evidence — not a deployed cloud infrastructure.

This document maps the Reliability Lab architecture to AWS and GCP managed services.
It shows how the local Docker Compose services translate to cloud-native equivalents.
No Terraform, no CloudFormation, no real cloud accounts required.

## What Stays the Same Architecturally

Regardless of cloud provider, these architectural decisions are invariant:

- **PostgreSQL is the source of truth.** All other stores are derived.
- **Elasticsearch is derived and rebuildable.** ES failures never block the critical path.
- **Redis provides idempotency at the API layer.** SET NX with 24h TTL.
- **RabbitMQ decouples ingestion from processing.** API returns 202 immediately.
- **Bounded retries with TTL queues.** 15s → 30s → 60s → DLQ (max 3 attempts).
- **Prometheus metrics on every state transition.** Counters + histograms.
- **Worker is horizontally scalable.** Multiple consumers on the same queue.

## AWS Mapping

| Local Service | AWS Managed Service | Notes |
|---|---|---|
| **API (FastAPI)** | ECS Fargate / EKS | Fargate for simplicity (no node management); EKS if already using Kubernetes |
| **Worker (Python)** | ECS Fargate / EKS | Same as API; scale via Service Auto Scaling or HPA |
| **RabbitMQ** | Amazon MQ for RabbitMQ | Fully managed, supports single-instance or cluster deployment. Alternative: CloudAMQP (AWS Marketplace) |
| **PostgreSQL** | RDS PostgreSQL | Multi-AZ for HA, automated backups, point-in-time recovery |
| **Redis** | ElastiCache Redis | Cluster mode for scaling, automatic failover |
| **Elasticsearch** | Amazon OpenSearch Service | Managed Elasticsearch-compatible. Alternative: Elastic Cloud (elastic.co) |
| **Prometheus** | Amazon Managed Prometheus | Serverless, no self-hosted Prometheus to maintain |
| **Grafana** | Amazon Managed Grafana | Integrates with AMP, CloudWatch, and other data sources |
| **Logs** | CloudWatch Logs | Container logs via awslogs driver. Alternative: self-hosted Loki |
| **Secrets** | AWS Secrets Manager | Connection URLs, API keys. Rotate automatically |
| **Networking** | VPC + ALB + Security Groups | Private subnets for data stores, public ALB for API |

### AWS Architecture Diagram (Logical)

```
┌─────────────────────────────────────────────────────────┐
│                      AWS VPC                              │
│                                                           │
│  ┌──────────┐     ┌──────────────┐                       │
│  │   ALB    │────▶│  ECS Fargate │  (API, 2+ tasks)      │
│  │ (public) │     │  api:8000    │                       │
│  └──────────┘     └──────┬───────┘                       │
│                          │                                │
│                          ▼                                │
│  ┌──────────────────────────────────────────────┐        │
│  │              Amazon MQ (RabbitMQ)              │        │
│  │         events.exchange / events.queue         │        │
│  │         retry.15s / retry.30s / retry.60s     │        │
│  │         events.dlq                              │        │
│  └──────────────────────┬───────────────────────┘        │
│                          │                                │
│                          ▼                                │
│  ┌──────────────┐     ┌──────────────┐                  │
│  │ ECS Fargate  │     │ ElastiCache  │                   │
│  │ worker:9100  │     │ Redis        │                   │
│  │ (2-10 tasks) │     │ (idempotency)│                   │
│  └──┬───────┬───┘     └──────────────┘                   │
│     │       │                                             │
│     ▼       ▼                                             │
│  ┌──────┐ ┌────────────┐                                 │
│  │ RDS  │ │ OpenSearch │                                 │
│  │ PG   │ │ (derived)  │                                 │
│  └──────┘ └────────────┘                                 │
│                                                           │
│  ┌──────────────────┐  ┌──────────────────┐              │
│  │ Amazon Managed   │  │ Amazon Managed   │              │
│  │ Prometheus       │  │ Grafana          │              │
│  └──────────────────┘  └──────────────────┘              │
│                                                           │
│  ┌──────────────────┐                                    │
│  │ CloudWatch Logs  │                                    │
│  └──────────────────┘                                    │
└─────────────────────────────────────────────────────────┘
```

## GCP Mapping

| Local Service | GCP Managed Service | Notes |
|---|---|---|
| **API (FastAPI)** | Cloud Run / GKE | Cloud Run for serverless simplicity; GKE if using Kubernetes |
| **Worker (Python)** | Cloud Run / GKE | Cloud Run jobs for event-driven processing. GKE for long-running consumers |
| **RabbitMQ** | CloudAMQP (Marketplace) / GKE self-managed | GCP has no native managed RabbitMQ. CloudAMQP is the standard choice. Alternative: consider Pub/Sub if willing to change messaging semantics |
| **PostgreSQL** | Cloud SQL PostgreSQL | High availability, automated backups, read replicas |
| **Redis** | Memorystore Redis | Fully managed, standard Redis protocol |
| **Elasticsearch** | Elastic Cloud (Marketplace) | GCP has no native managed Elasticsearch. Elastic Cloud is the standard choice |
| **Prometheus** | Google Cloud Managed Prometheus (GMP) | Integrated with Cloud Monitoring, no self-hosted Prometheus |
| **Grafana** | Self-hosted or Grafana Cloud | GCP has no native managed Grafana. Use Grafana Cloud or deploy on GKE |
| **Logs** | Cloud Logging | Container logs via Cloud Operations suite |
| **Secrets** | Secret Manager | Connection URLs, API keys |
| **Networking** | VPC + Cloud Load Balancer + Firewall Rules | Private subnets, Cloud Armor for WAF |

### GCP Architecture Diagram (Logical)

```
┌─────────────────────────────────────────────────────────┐
│                      GCP VPC                              │
│                                                           │
│  ┌──────────────┐    ┌──────────────┐                    │
│  │ Cloud Load   │───▶│  Cloud Run   │  (API)             │
│  │ Balancer     │    │  api:8000    │                    │
│  └──────────────┘    └──────┬───────┘                    │
│                             │                             │
│                             ▼                             │
│  ┌──────────────────────────────────────────────┐        │
│  │           CloudAMQP (RabbitMQ)                 │        │
│  │    events.exchange / events.queue              │        │
│  │    retry.15s / retry.30s / retry.60s          │        │
│  │    events.dlq                                   │        │
│  └──────────────────────┬───────────────────────┘        │
│                          │                                │
│                          ▼                                │
│  ┌──────────────┐     ┌──────────────┐                  │
│  │ Cloud Run    │     │ Memorystore  │                   │
│  │ worker:9100  │     │ Redis        │                   │
│  └──┬───────┬───┘     └──────────────┘                   │
│     │       │                                             │
│     ▼       ▼                                             │
│  ┌──────┐ ┌────────────┐                                 │
│  │Cloud │ │ Elastic    │                                  │
│  │SQL PG│ │ Cloud      │                                  │
│  └──────┘ └────────────┘                                 │
│                                                           │
│  ┌──────────────────┐  ┌──────────────────┐              │
│  │ Managed          │  │ Grafana Cloud    │              │
│  │ Prometheus (GMP) │  │ (or self-hosted) │              │
│  └──────────────────┘  └──────────────────┘              │
│                                                           │
│  ┌──────────────────┐                                    │
│  │ Cloud Logging    │                                    │
│  └──────────────────┘                                    │
└─────────────────────────────────────────────────────────┘
```

## Risk and Cost Notes

### AWS

| Service | Cost Driver | Monthly Estimate (dev/test) |
|---|---|---|
| ECS Fargate (2 API + 2 Worker) | vCPU + memory per task | ~$50-80 |
| Amazon MQ (mq.t3.micro) | Instance hours + storage | ~$30-50 |
| RDS PostgreSQL (db.t3.micro) | Instance hours + storage | ~$25-40 |
| ElastiCache (cache.t3.micro) | Instance hours | ~$15-25 |
| OpenSearch (t3.small.search) | Instance hours + storage | ~$50-80 |
| ALB | Hours + LCU | ~$20-30 |
| AMP + AMG | Ingestion + workspace | ~$30-50 |
| **Total (dev/test)** | | **~$220-355/month** |

### GCP

| Service | Cost Driver | Monthly Estimate (dev/test) |
|---|---|---|
| Cloud Run (API + Worker) | vCPU-seconds + memory-seconds | ~$30-50 |
| CloudAMQP (Little Lemur) | Plan tier | ~$20-30 |
| Cloud SQL (db-f1-micro) | Instance hours + storage | ~$15-25 |
| Memorystore (M1) | Instance hours | ~$30-50 |
| Elastic Cloud (1GB) | Deployment size | ~$50-80 |
| Cloud Load Balancer | Hours + traffic | ~$20-30 |
| GMP + Cloud Logging | Ingestion + retention | ~$20-40 |
| **Total (dev/test)** | | **~$185-305/month** |

**Risk: CloudAMQP is the only non-native GCP service.** If GCP-native is a hard requirement,
consider replacing RabbitMQ with Pub/Sub. This would require changing the retry/DLQ
architecture (Pub/Sub has built-in retry + dead letter topics, but the semantics differ
from TTL-based retry queues).

## Local Lab vs Production Deployment Boundary

| Concern | Local Lab (docker compose) | Production (cloud) |
|---|---|---|
| **Stateful services** | Containers with ephemeral storage | Managed services with persistent storage, backups, HA |
| **Secrets** | `.env` file (gitignored) | Cloud secret manager, never in version control |
| **Networking** | Docker bridge network | VPC, private subnets, security groups, WAF |
| **Scaling** | `docker compose up --scale worker=N` | Auto Scaling (ECS) / HPA (EKS) / Cloud Run concurrency |
| **Monitoring** | Prometheus + optional Grafana/Loki | Managed Prometheus + Grafana + CloudWatch/Cloud Logging |
| **TLS** | None (localhost) | ALB/Cloud LB termination + cert-manager |
| **Auth** | None (unauthenticated) | API keys, JWT, OAuth via gateway |
| **CI/CD** | Manual `make up` | GitHub Actions → build → push → deploy |
| **Disaster recovery** | None | Automated backups, multi-region, point-in-time recovery |

## Honest Positioning

This document demonstrates that I understand how to map a local architecture to
cloud-native managed services on both AWS and GCP. It shows awareness of cost,
risk, and the boundary between local development and production infrastructure.
It is not a deployed cloud environment and does not claim to be one.
