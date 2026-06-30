# Kubernetes Readiness Pack

**Status:** Readiness evidence — not a deployed production cluster.

This directory contains Kubernetes manifests that demonstrate how the Reliability Lab
services would be deployed on Kubernetes. These are **example manifests** for portfolio
and interview purposes. They are not required for local development (which uses
`docker compose`).

## How Local Docker Services Map to Kubernetes

| Local (docker compose) | Kubernetes Equivalent | Notes |
|---|---|---|
| `api` container | `api-deployment.yaml` | FastAPI with liveness/readiness probes |
| `worker` container | `worker-deployment.yaml` | Scalable consumer with HPA |
| `rabbitmq` container | **External managed service** | Amazon MQ, CloudAMQP, or self-managed RabbitMQ cluster |
| `postgres` container | **External managed service** | RDS PostgreSQL, Cloud SQL, or self-managed PostgreSQL |
| `redis` container | **External managed service** | ElastiCache, Memorystore, or self-managed Redis |
| `elasticsearch` container | **External managed service** | Amazon OpenSearch, Elastic Cloud, or self-managed ES cluster |
| `prometheus` container | **External managed service** | Amazon Managed Prometheus, GMP, or self-managed Prometheus |

**Key design decision:** PostgreSQL, RabbitMQ, Redis, and Elasticsearch are treated as
**external managed dependencies** in production. The Kubernetes manifests only deploy
the stateless application services (API + Worker). This is the standard pattern for
production Kubernetes — stateful services are managed outside the cluster.

## Files

| File | Purpose |
|---|---|
| `api-deployment.yaml` | FastAPI deployment with liveness/readiness probes, resource requests/limits |
| `api-service.yaml` | ClusterIP service for the API |
| `worker-deployment.yaml` | Worker deployment with scalable replicas |
| `configmap.yaml` | Non-secret configuration (ES URL, queue names, etc.) |
| `secret.example.yaml` | Example secret structure (connection URLs) — **no real secrets** |
| `worker-hpa.yaml` | HorizontalPodAutoscaler for worker based on CPU |
| `network-policy.example.yaml` | Example network policy restricting pod-to-pod traffic |

## Worker Scaling

The worker is designed to scale horizontally:

- Each worker pod consumes from the same RabbitMQ queue
- RabbitMQ handles message distribution (round-robin by default)
- The HPA scales worker replicas based on CPU utilization
- For custom metrics (queue depth), a Prometheus Adapter would be needed

```bash
# Manual scaling
kubectl scale deployment worker --replicas=5

# Check HPA status
kubectl get hpa worker-hpa
```

## What Would Be Required to Deploy for Real

1. **Container registry** — push images to ECR, GCR, or Docker Hub
2. **External services** — provision PostgreSQL, RabbitMQ, Redis, Elasticsearch
3. **Secrets management** — use External Secrets Operator, Sealed Secrets, or cloud secret manager
4. **Ingress controller** — deploy nginx-ingress or use APISIX gateway
5. **TLS certificates** — cert-manager for automatic TLS
6. **Monitoring** — Prometheus Operator + Grafana (or cloud-managed equivalents)
7. **CI/CD pipeline** — GitHub Actions to build, push, and deploy on merge to main
8. **Namespace and RBAC** — dedicated namespace with least-privilege service accounts
9. **Resource tuning** — adjust requests/limits based on load testing
10. **Network policies** — restrict egress to only required external services

## Production Assumptions

- **PostgreSQL, RabbitMQ, Redis, Elasticsearch are external.** The manifests do not
  include StatefulSets or PersistentVolumeClaims for these services. In production,
  use managed services with automated backups, failover, and monitoring.
- **Secrets are external.** The `secret.example.yaml` shows the structure but contains
  placeholder values. Real secrets should come from a secret manager.
- **Images are pre-built.** The manifests reference `reliability-lab/api:latest` and
  `reliability-lab/worker:latest`. In production, use specific version tags.
- **Single namespace.** All resources are in the same namespace. For multi-tenant
  or multi-environment setups, use separate namespaces.
- **No service mesh.** Istio/Linkerd are not included. Add if needed for mTLS,
  traffic splitting, or observability.

## Honest Positioning

These manifests demonstrate that I understand Kubernetes deployment patterns —
Deployments, Services, ConfigMaps, Secrets, HPAs, liveness/readiness probes,
resource management, and the separation of stateless application services from
stateful external dependencies. They are not a production-tested Helm chart.
