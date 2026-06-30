"""Test observability profile — file/config existence only.

These tests verify that the observability provisioning files exist
and are valid without starting Grafana/Loki containers.
"""

import json
import yaml
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def test_observability_compose_file_exists():
    """docker-compose.observability.yml exists and is valid YAML."""
    path = PROJECT_ROOT / "docker-compose.observability.yml"
    assert path.exists(), f"Missing {path}"
    content = yaml.safe_load(path.read_text())
    assert "services" in content
    assert "grafana" in content["services"]
    assert "loki" in content["services"]
    assert "promtail" in content["services"]


def test_promtail_config_exists():
    """promtail-config.yml exists and is valid YAML."""
    path = PROJECT_ROOT / "promtail-config.yml"
    assert path.exists(), f"Missing {path}"
    content = yaml.safe_load(path.read_text())
    assert "clients" in content
    assert "scrape_configs" in content


def test_grafana_prometheus_datasource_exists():
    """Prometheus datasource provisioning file exists."""
    path = PROJECT_ROOT / "grafana/provisioning/datasources/prometheus.yml"
    assert path.exists(), f"Missing {path}"
    content = yaml.safe_load(path.read_text())
    assert "datasources" in content
    ds = content["datasources"][0]
    assert ds["name"] == "Prometheus"
    assert ds["type"] == "prometheus"
    assert "prometheus:9090" in ds["url"]


def test_grafana_loki_datasource_exists():
    """Loki datasource provisioning file exists."""
    path = PROJECT_ROOT / "grafana/provisioning/datasources/loki.yml"
    assert path.exists(), f"Missing {path}"
    content = yaml.safe_load(path.read_text())
    assert "datasources" in content
    ds = content["datasources"][0]
    assert ds["name"] == "Loki"
    assert ds["type"] == "loki"
    assert "loki:3100" in ds["url"]


def test_grafana_dashboard_provisioning_exists():
    """Dashboard provisioning config exists."""
    path = PROJECT_ROOT / "grafana/provisioning/dashboards/dashboard.yml"
    assert path.exists(), f"Missing {path}"
    content = yaml.safe_load(path.read_text())
    assert "providers" in content
    provider = content["providers"][0]
    assert provider["name"] == "Reliability Lab"


def test_grafana_dashboard_json_exists():
    """Reliability Lab dashboard JSON exists and is valid."""
    path = PROJECT_ROOT / "grafana/dashboards/reliability-lab.json"
    assert path.exists(), f"Missing {path}"
    data = json.loads(path.read_text())
    assert data["title"] == "Reliability Lab"
    assert data["uid"] == "reliability-lab"
    assert len(data["panels"]) >= 8, f"Expected at least 8 panels, got {len(data['panels'])}"

    # Verify key panels exist
    panel_titles = {p["title"] for p in data["panels"]}
    expected = [
        "API — Publish & Duplicate Rate",
        "Worker — Processed / Retry / DLQ Rate",
        "API Publish Total",
        "Worker Processed Total",
        "Worker DLQ Total",
        "Worker Retry Total",
        "ES Index Failures Total",
        "API Duplicate Total",
        "Latency — API & Worker (avg)",
    ]
    for title in expected:
        assert title in panel_titles, f"Missing panel: {title}"


def test_docs_observability_exists():
    """docs/observability.md exists."""
    path = PROJECT_ROOT / "docs/observability.md"
    assert path.exists(), f"Missing {path}"
    content = path.read_text()
    assert "Grafana" in content
    assert "Loki" in content
    assert "make observability-up" in content


def test_reports_observability_proof_exists():
    """reports/observability-proof.md exists."""
    path = PROJECT_ROOT / "reports/observability-proof.md"
    assert path.exists(), f"Missing {path}"
    content = path.read_text()
    assert "Observability Proof" in content
    assert "Prometheus" in content
    assert "Grafana" in content
    assert "Loki" in content


def test_makefile_has_observability_targets():
    """Makefile includes observability-up and observability-down targets."""
    path = PROJECT_ROOT / "Makefile"
    content = path.read_text()
    assert "observability-up:" in content
    assert "observability-down:" in content
    assert "docker-compose.observability.yml" in content
