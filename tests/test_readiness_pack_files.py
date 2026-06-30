"""Tests for Production Readiness Pack 3 files.

These tests verify that the readiness pack files exist and contain expected content.
They do NOT require Kubernetes, APISIX, Rails, AWS, or GCP to be installed.
They do NOT run real deployments.
"""

import os
import json
import yaml


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with open(os.path.join(PROJECT_ROOT, path)) as f:
        return f.read()


# ─────────────────────────────────────────────────────────
# Kubernetes readiness pack
# ─────────────────────────────────────────────────────────

def test_k8s_readme_exists():
    content = _read("deploy/k8s/README.md")
    assert "Kubernetes Readiness Pack" in content
    assert "readiness evidence" in content.lower()
    assert "not a deployed production cluster" in content.lower()


def test_k8s_api_deployment_exists():
    content = _read("deploy/k8s/api-deployment.yaml")
    docs = list(yaml.safe_load_all(content))
    assert len(docs) >= 1
    dep = docs[0]
    assert dep["kind"] == "Deployment"
    assert dep["metadata"]["name"] == "api"
    # Must have liveness and readiness probes
    containers = dep["spec"]["template"]["spec"]["containers"]
    assert any("livenessProbe" in c for c in containers)
    assert any("readinessProbe" in c for c in containers)


def test_k8s_api_service_exists():
    content = _read("deploy/k8s/api-service.yaml")
    svc = yaml.safe_load(content)
    assert svc["kind"] == "Service"
    assert svc["spec"]["type"] == "ClusterIP"


def test_k8s_worker_deployment_exists():
    content = _read("deploy/k8s/worker-deployment.yaml")
    dep = yaml.safe_load(content)
    assert dep["kind"] == "Deployment"
    assert dep["metadata"]["name"] == "worker"


def test_k8s_configmap_exists():
    content = _read("deploy/k8s/configmap.yaml")
    cm = yaml.safe_load(content)
    assert cm["kind"] == "ConfigMap"
    assert "ELASTICSEARCH_URL" in cm.get("data", {})


def test_k8s_secret_example_exists():
    content = _read("deploy/k8s/secret.example.yaml")
    secret = yaml.safe_load(content)
    assert secret["kind"] == "Secret"
    # Must contain placeholder, not real secrets
    assert "replace-me" in content.lower() or "example" in content.lower()


def test_k8s_worker_hpa_exists():
    content = _read("deploy/k8s/worker-hpa.yaml")
    hpa = yaml.safe_load(content)
    assert hpa["kind"] == "HorizontalPodAutoscaler"
    assert hpa["spec"]["scaleTargetRef"]["name"] == "worker"


def test_k8s_network_policy_exists():
    content = _read("deploy/k8s/network-policy.example.yaml")
    assert "NetworkPolicy" in content
    assert "api-network-policy" in content or "worker-network-policy" in content


# ─────────────────────────────────────────────────────────
# APISIX readiness pack
# ─────────────────────────────────────────────────────────

def test_apisix_readme_exists():
    content = _read("deploy/apisix/README.md")
    assert "APISIX" in content
    assert "readiness evidence" in content.lower()


def test_apisix_routes_example_exists():
    content = _read("deploy/apisix/routes.example.yaml")
    assert "routes" in content.lower()
    assert "api/v1/messages" in content or "/api/v1/messages" in content


def test_apisix_docker_compose_exists():
    content = _read("deploy/apisix/docker-compose.apisix.example.yml")
    parsed = yaml.safe_load(content)
    assert "services" in parsed
    assert "apisix" in parsed["services"]


# ─────────────────────────────────────────────────────────
# Cloud deployment map
# ─────────────────────────────────────────────────────────

def test_cloud_deployment_map_exists():
    content = _read("docs/cloud-deployment-map.md")
    assert "Cloud Deployment Map" in content
    assert "AWS" in content
    assert "GCP" in content
    assert "RDS" in content or "Cloud SQL" in content


# ─────────────────────────────────────────────────────────
# Rails integration example
# ─────────────────────────────────────────────────────────

def test_rails_readme_exists():
    content = _read("examples/rails-event-publisher/README.md")
    assert "Rails" in content
    assert "integration example" in content.lower()


def test_rails_publisher_exists():
    content = _read("examples/rails-event-publisher/customer_message_publisher.rb")
    assert "CustomerMessagePublisher" in content
    assert "message_id" in content
    assert "idempotency" in content.lower() or "duplicate" in content.lower()
    # Must be valid Ruby syntax (basic check)
    assert "class" in content
    assert "def" in content
    assert "end" in content


# ─────────────────────────────────────────────────────────
# SLO & incident readiness
# ─────────────────────────────────────────────────────────

def test_slo_doc_exists():
    content = _read("docs/slo-and-incident-readiness.md")
    assert "SLO" in content
    assert "error budget" in content.lower()
    assert "PromQL" in content or "promql" in content.lower()
    assert "incident response" in content.lower()


# ─────────────────────────────────────────────────────────
# README and PORTFOLIO updates
# ─────────────────────────────────────────────────────────

def test_readme_has_production_readiness_packs():
    content = _read("README.md")
    assert "Production Readiness Packs" in content
    assert "Pack 3" in content
    assert "deploy/k8s/" in content
    assert "deploy/apisix/" in content
    assert "cloud-deployment-map.md" in content
    assert "rails-event-publisher" in content
    assert "slo-and-incident-readiness.md" in content


def test_portfolio_has_role_stack_alignment():
    content = _read("PORTFOLIO.md")
    assert "Role Stack Alignment" in content
    assert "Kubernetes" in content
    assert "APISIX" in content
    assert "Ruby on Rails" in content
    assert "SLO-driven engineering" in content


def test_current_status_updated():
    content = _read("reports/current-status.md")
    assert "Pack 3" in content
    assert "Kubernetes" in content
    assert "APISIX" in content
