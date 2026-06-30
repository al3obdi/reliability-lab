#!/usr/bin/env python3
"""Observability verification — wait for Grafana + Loki readiness, then verify.

Usage:
    python scripts/observability_verify.py
    make observability-verify
"""

import sys
import time
import urllib.request
import json


GRAFANA_URL = "http://localhost:3000"
LOKI_URL = "http://localhost:3100"
PROMETHEUS_URL = "http://localhost:9090"
LOKI_READY_TIMEOUT = 60


def _get(url: str, timeout: int = 5) -> tuple[int, str]:
    """HTTP GET, returns (status_code, body)."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except Exception as e:
        return 0, str(e)


def wait_for_loki(timeout: int = LOKI_READY_TIMEOUT) -> tuple[bool, float]:
    """Poll Loki /ready until it returns 'Ready' or timeout. Returns (ready, elapsed_seconds)."""
    start = time.monotonic()
    deadline = start + timeout
    while time.monotonic() < deadline:
        status, body = _get(f"{LOKI_URL}/ready", timeout=5)
        if status == 200 and "ready" in body.lower():
            return True, round(time.monotonic() - start, 1)
        time.sleep(2)
    return False, round(time.monotonic() - start, 1)


def main():
    all_ok = True

    print("=" * 60)
    print("  Observability Verification")
    print("=" * 60)
    print()

    # ── Grafana health ──────────────────────────────────────────
    print("── Grafana health ──")
    status, _ = _get(f"{GRAFANA_URL}/api/health")
    if status == 200:
        print("  Grafana: 200 OK ✅")
    else:
        print(f"  Grafana: {status} ❌")
        all_ok = False
    print()

    # ── Loki readiness (with wait) ─────────────────────────────
    print(f"── Loki readiness (waiting up to {LOKI_READY_TIMEOUT}s) ──")
    ready, elapsed = wait_for_loki()
    if ready:
        print(f"  Loki ready after {elapsed}s: PASS ✅")
    else:
        print(f"  Loki not ready after {elapsed}s ❌")
        all_ok = False
    print()

    # ── Prometheus targets ─────────────────────────────────────
    print("── Prometheus targets ──")
    status, body = _get(f"{PROMETHEUS_URL}/api/v1/targets")
    if status == 200:
        data = json.loads(body)
        targets = data.get("data", {}).get("activeTargets", [])
        for t in targets:
            job = t["labels"].get("job", "?")
            health = t["health"]
            icon = "✅" if health == "up" else "❌"
            print(f"  {job}: {health} {icon}")
            if health != "up":
                all_ok = False
    else:
        print(f"  Prometheus unreachable: {status} ❌")
        all_ok = False
    print()

    # ── Grafana datasources ────────────────────────────────────
    print("── Grafana datasources ──")
    status, body = _get(f"{GRAFANA_URL}/api/datasources")
    if status == 200:
        datasources = json.loads(body)
        expected = {"prometheus", "loki"}
        found = set()
        for ds in datasources:
            name = ds["name"]
            ds_type = ds["type"]
            url = ds.get("url", "?")
            found.add(ds_type)
            print(f"  {name}: {ds_type} → {url} ✅")
        missing = expected - found
        if missing:
            print(f"  Missing datasources: {missing} ❌")
            all_ok = False
    else:
        print(f"  Grafana datasources unreachable: {status} ❌")
        all_ok = False
    print()

    # ── Grafana dashboard ──────────────────────────────────────
    print("── Grafana dashboard ──")
    status, body = _get(f"{GRAFANA_URL}/api/search?type=dash-db")
    if status == 200:
        results = json.loads(body)
        dashboards = [d for d in results if d.get("uid") == "reliability-lab"]
        if dashboards:
            print(f"  Reliability Lab dashboard: provisioned ✅")
        else:
            print("  Reliability Lab dashboard: NOT FOUND ❌")
            all_ok = False
    else:
        print(f"  Dashboard search failed: {status} ❌")
        all_ok = False
    print()

    # ── Summary ────────────────────────────────────────────────
    print("=" * 60)
    if all_ok:
        print("  ✅ Observability verification PASSED")
    else:
        print("  ❌ Observability verification FAILED")
    print("=" * 60)

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
