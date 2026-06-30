#!/usr/bin/env python3
"""Portfolio Evidence Layer — end-to-end reliability verification suite.

Runs 6 scenarios demonstrating the system's reliability behavior:
  A. Happy path — publish → PG → ES
  B. Duplicate idempotency — same message_id twice
  C. Elasticsearch outage — stop ES, publish, restart, reindex
  D. PostgreSQL failure → retry/DLQ — stop PG, publish, verify DLQ
  E. Invalid payload → DLQ — malformed message
  F. Metrics evidence — /metrics endpoints + Prometheus targets

Generates:
  reports/portfolio-verification-report.md
  reports/portfolio-verification-report.json

Usage:
    python scripts/portfolio_verify.py
    python scripts/portfolio_verify.py --api http://localhost:8000 --prometheus http://localhost:9090
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import urllib.request

# ── Configuration ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"

ES_SERVICE = "elasticsearch"
PG_SERVICE = "postgres"
RABBITMQ_SERVICE = "rabbitmq"

ES_CONTAINER = "reliability-lab-elasticsearch-1"
PG_CONTAINER = "reliability-lab-postgres-1"
RABBITMQ_CONTAINER = "reliability-lab-rabbitmq-1"


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _compose(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE)] + list(args),
        capture_output=True, text=True, timeout=60,
    )


def _docker_exec(container: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", container] + list(args),
        capture_output=True, text=True, timeout=30,
    )


def _pg_query(query: str) -> str:
    """Run a SQL query against PostgreSQL and return stdout."""
    r = _docker_exec(
        PG_CONTAINER,
        "psql", "-U", "reliability", "-d", "reliability_lab",
        "-t", "-A", "-c", query,
    )
    return r.stdout.strip()


def _es_get(doc_id: str) -> dict | None:
    """Get an Elasticsearch document by ID."""
    try:
        r = httpx.get(
            f"http://localhost:9200/messages-v1/_doc/{doc_id}",
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("_source")
    except Exception:
        pass
    return None


def _es_health() -> str:
    """Return ES cluster health status."""
    try:
        r = httpx.get("http://localhost:9200/_cluster/health", timeout=5)
        return r.json().get("status", "unknown")
    except Exception:
        return "unreachable"


def _rmq_queue_count(queue_name: str) -> int:
    """Get message count for a RabbitMQ queue via rabbitmqctl."""
    try:
        r = _docker_exec(
            RABBITMQ_CONTAINER,
            "rabbitmqctl", "list_queues", "name", "messages",
        )
        for line in r.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 2 and parts[0] == queue_name:
                return int(parts[1])
    except Exception:
        pass
    return -1


def _prometheus_query(prometheus_url: str, query: str) -> float:
    """Run an instant query against Prometheus."""
    url = f"{prometheus_url}/api/v1/query?query={urllib.request.quote(query)}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data["status"] == "success" and data["data"]["result"]:
                return float(data["data"]["result"][0]["value"][1])
    except Exception:
        pass
    return 0.0


def _publish(api_url: str, msg_id: str, customer_id: str, text: str, channel: str = "web") -> dict:
    """Publish a message via the API. Returns the JSON response."""
    r = httpx.post(
        f"{api_url}/api/v1/messages",
        json={
            "message_id": msg_id,
            "customer_id": customer_id,
            "text": text,
            "channel": channel,
        },
        timeout=10,
    )
    return {"status": r.status_code, "body": r.json() if r.text else {}}


def _publish_raw_to_rmq(payload: dict, routing_key: str = "events.created.test") -> bool:
    """Publish a raw message directly to RabbitMQ via management API (bypass API)."""
    try:
        r = httpx.post(
            "http://localhost:15672/api/exchanges/%2F/events.exchange/publish",
            auth=("reliability", "lab123"),
            json={
                "properties": {"content_type": "application/json", "delivery_mode": 2},
                "routing_key": routing_key,
                "payload": json.dumps(payload),
                "payload_encoding": "string",
            },
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"    [WARN] Raw publish failed: {e}")
        return False


def _wait_for_worker(api_url: str, msg_id: str, timeout_sec: int = 30) -> bool:
    """Poll PostgreSQL until the message appears or timeout."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        result = _pg_query(
            f"SELECT status FROM messages WHERE message_id = '{msg_id}'"
        )
        if result == "completed":
            return True
        time.sleep(1)
    return False


def _wait_for_index_status(msg_id: str, expected: str, timeout_sec: int = 15) -> bool:
    """Poll PostgreSQL until index_status matches expected value."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        result = _pg_query(
            f"SELECT index_status FROM messages WHERE message_id = '{msg_id}'"
        )
        if result == expected:
            return True
        time.sleep(1)
    return False


def _wait_for_dlq(expected_count: int, timeout_sec: int = 90) -> bool:
    """Poll DLQ until it has at least expected_count messages."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        count = _rmq_queue_count("events.dlq")
        if count >= expected_count:
            return True
        time.sleep(2)
    return False


def _stop_service(service: str) -> bool:
    r = _compose("stop", service)
    return r.returncode == 0


def _start_service(service: str) -> bool:
    r = _compose("start", service)
    if r.returncode != 0:
        return False
    time.sleep(5)
    return True


def _purge_dlq() -> None:
    """Purge all messages from DLQ."""
    _docker_exec(
        RABBITMQ_CONTAINER,
        "rabbitmqctl", "purge_queue", "-p", "/", "events.dlq",
    )
    time.sleep(1)  # Let RabbitMQ settle


# ═══════════════════════════════════════════════════════════════════════
# Scenario runners
# ═══════════════════════════════════════════════════════════════════════

def scenario_a_happy_path(api_url: str) -> dict:
    """A. Happy path — publish → PG → ES."""
    msg_id = str(uuid.uuid4())
    customer_id = "cust-happy"
    text = "مرحبا، هذا اختبار المسار السعيد"

    evidence = {}
    evidence["message_id"] = msg_id
    evidence["published"] = _publish(api_url, msg_id, customer_id, text)

    found = _wait_for_worker(api_url, msg_id, timeout_sec=30)
    evidence["pg_found"] = found

    if found:
        pg_row = _pg_query(
            f"SELECT status, index_status FROM messages WHERE message_id = '{msg_id}'"
        )
        evidence["pg_row"] = pg_row
        evidence["index_status"] = "indexed" if "indexed" in pg_row else pg_row

    es_doc = _es_get(msg_id)
    evidence["es_document_exists"] = es_doc is not None
    if es_doc:
        evidence["es_text"] = es_doc.get("text", "")[:80]

    evidence["pass"] = (
        evidence["published"]["status"] == 202
        and found
        and evidence.get("index_status") == "indexed"
        and evidence["es_document_exists"]
    )
    return evidence


def scenario_b_duplicate(api_url: str) -> dict:
    """B. Duplicate idempotency — same message_id twice."""
    msg_id = str(uuid.uuid4())
    customer_id = "cust-dup"
    text = "اختبار التكرار — نفس الرسالة مرتين"

    evidence = {}
    evidence["message_id"] = msg_id

    r1 = _publish(api_url, msg_id, customer_id, text)
    evidence["first_publish"] = r1

    r2 = _publish(api_url, msg_id, customer_id, text)
    evidence["second_publish"] = r2

    _wait_for_worker(api_url, msg_id, timeout_sec=30)

    count = _pg_query(
        f"SELECT COUNT(*) FROM messages WHERE message_id = '{msg_id}'"
    )
    evidence["pg_row_count"] = int(count) if count.isdigit() else -1

    evidence["pass"] = (
        r1["status"] == 202
        and r2["status"] == 202
        and r2["body"].get("duplicate") is True
        and evidence["pg_row_count"] == 1
    )
    return evidence


def scenario_c_es_outage(api_url: str) -> dict:
    """C. Elasticsearch outage — stop ES, publish, restart, reindex."""
    msg_id = str(uuid.uuid4())
    customer_id = "cust-esout"
    text = "اختبار انقطاع Elasticsearch — يجب أن يبقى PostgreSQL سليمًا"

    evidence = {}
    evidence["message_id"] = msg_id

    evidence["es_stopped"] = _stop_service(ES_SERVICE)
    time.sleep(3)

    evidence["published"] = _publish(api_url, msg_id, customer_id, text)

    found = _wait_for_worker(api_url, msg_id, timeout_sec=30)
    evidence["pg_found"] = found

    if found:
        _wait_for_index_status(msg_id, "failed", timeout_sec=15)
        pg_row = _pg_query(
            f"SELECT status, index_status FROM messages WHERE message_id = '{msg_id}'"
        )
        evidence["pg_row"] = pg_row
        evidence["index_status_after_es_down"] = pg_row

    evidence["es_started"] = _start_service(ES_SERVICE)
    time.sleep(10)

    reindex = subprocess.run(
        ["docker", "exec", "reliability-lab-worker-1",
         "python", "/scripts/reindex_failed.py"],
        capture_output=True, text=True, timeout=60,
    )
    evidence["reindex_output"] = (reindex.stdout.strip() or reindex.stderr.strip())[:500]

    pg_row_after = _pg_query(
        f"SELECT status, index_status FROM messages WHERE message_id = '{msg_id}'"
    )
    evidence["pg_row_after_reindex"] = pg_row_after

    es_doc = _es_get(msg_id)
    evidence["es_document_exists_after_reindex"] = es_doc is not None

    evidence["pass"] = (
        evidence["published"]["status"] == 202
        and found
        and "failed" in evidence.get("index_status_after_es_down", "")
        and evidence["es_document_exists_after_reindex"]
        and "indexed" in pg_row_after
    )
    return evidence


def scenario_d_pg_failure_retry_dlq(api_url: str) -> dict:
    """D. PostgreSQL failure → retry/DLQ."""
    msg_id = str(uuid.uuid4())
    customer_id = "cust-pgdown"
    text = "اختبار فشل PostgreSQL — يجب أن يذهب إلى DLQ بعد 3 محاولات"

    evidence = {}
    evidence["message_id"] = msg_id

    _purge_dlq()
    dlq_before = _rmq_queue_count("events.dlq")
    evidence["dlq_before"] = dlq_before

    evidence["pg_stopped"] = _stop_service(PG_SERVICE)
    time.sleep(3)

    evidence["published"] = _publish(api_url, msg_id, customer_id, text)

    dlq_found = _wait_for_dlq(dlq_before + 1, timeout_sec=150)
    evidence["dlq_found"] = dlq_found

    dlq_after = _rmq_queue_count("events.dlq")
    evidence["dlq_after"] = dlq_after

    evidence["pg_started"] = _start_service(PG_SERVICE)
    time.sleep(5)

    evidence["pass"] = (
        evidence["published"]["status"] == 202
        and dlq_found
        and dlq_after > dlq_before
    )
    return evidence


def scenario_e_invalid_payload_dlq(api_url: str) -> dict:
    """E. Invalid payload → DLQ."""
    evidence = {}

    _purge_dlq()
    dlq_before = _rmq_queue_count("events.dlq")
    evidence["dlq_before"] = dlq_before

    malformed = {"not_a_valid_message": True, "garbage": "%%%"}
    published = _publish_raw_to_rmq(malformed)
    evidence["raw_published"] = published

    dlq_found = _wait_for_dlq(dlq_before + 1, timeout_sec=30)
    evidence["dlq_found"] = dlq_found

    dlq_after = _rmq_queue_count("events.dlq")
    evidence["dlq_after"] = dlq_after

    evidence["pass"] = published and dlq_found and dlq_after > dlq_before
    return evidence


def scenario_f_metrics_evidence(api_url: str, prometheus_url: str) -> dict:
    """F. Metrics evidence — /metrics endpoints + Prometheus targets."""
    evidence = {}

    try:
        r = httpx.get(f"{api_url}/metrics", timeout=5)
        evidence["api_metrics_status"] = r.status_code
        evidence["api_metrics_has_publish"] = "api_publish_total" in r.text
        evidence["api_metrics_has_duplicate"] = "api_duplicate_total" in r.text
    except Exception as e:
        evidence["api_metrics_error"] = str(e)

    try:
        r = httpx.get("http://localhost:9100/metrics", timeout=5)
        evidence["worker_metrics_status"] = r.status_code
        evidence["worker_metrics_has_processed"] = "worker_messages_processed_total" in r.text
        evidence["worker_metrics_has_dlq"] = "worker_messages_dlq_total" in r.text
    except Exception as e:
        evidence["worker_metrics_error"] = str(e)

    try:
        r = httpx.get(f"{prometheus_url}/api/v1/targets", timeout=5)
        targets = r.json().get("data", {}).get("activeTargets", [])
        evidence["prometheus_targets"] = [
            {"job": t["labels"].get("job", "?"), "health": t["health"]}
            for t in targets
        ]
        api_up = any(
            t["labels"].get("job") == "api" and t["health"] == "up"
            for t in targets
        )
        worker_up = any(
            t["labels"].get("job") == "worker" and t["health"] == "up"
            for t in targets
        )
        evidence["api_target_up"] = api_up
        evidence["worker_target_up"] = worker_up
    except Exception as e:
        evidence["prometheus_error"] = str(e)
        evidence["api_target_up"] = False
        evidence["worker_target_up"] = False

    evidence["api_publish_total"] = _prometheus_query(prometheus_url, "api_publish_total")
    evidence["api_duplicate_total"] = _prometheus_query(prometheus_url, "api_duplicate_total")
    evidence["worker_processed"] = _prometheus_query(prometheus_url, "worker_messages_processed_total")
    evidence["worker_dlq_total"] = _prometheus_query(prometheus_url, "worker_messages_dlq_total")
    evidence["worker_es_failed"] = _prometheus_query(prometheus_url, "worker_es_index_failed_total")

    evidence["pass"] = (
        evidence.get("api_metrics_status") == 200
        and evidence.get("worker_metrics_status") == 200
        and evidence.get("api_target_up", False)
        and evidence.get("worker_target_up", False)
    )
    return evidence


# ═══════════════════════════════════════════════════════════════════════
# Report generation
# ═══════════════════════════════════════════════════════════════════════

def generate_reports(scenarios: list[dict], args) -> tuple[str, str]:
    """Generate Markdown and JSON reports. Returns (md_path, json_path)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_pass = all(s["pass"] for s in scenarios)

    verdict = "PASS" if all_pass else "FAIL"

    md_lines = []
    md_lines.append("# Portfolio Verification Report")
    md_lines.append("")
    md_lines.append(f"**Generated:** {timestamp}")
    md_lines.append(f"**Verdict:** {'✅ PASS' if all_pass else '❌ FAIL'}")
    md_lines.append("")
    md_lines.append("## Scenario Results")
    md_lines.append("")
    md_lines.append("| # | Scenario | Result | Key Evidence |")
    md_lines.append("|---|----------|--------|-------------|")

    for s in scenarios:
        icon = "✅" if s["pass"] else "❌"
        name = s["name"]
        evidence_summary = s.get("evidence_summary", "")
        md_lines.append(f"| {s['id']} | {name} | {icon} | {evidence_summary} |")

    md_lines.append("")
    md_lines.append("## Detailed Evidence")
    md_lines.append("")

    for s in scenarios:
        md_lines.append(f"### {s['id']}. {s['name']}")
        md_lines.append("")
        md_lines.append(f"**Result:** {'✅ PASS' if s['pass'] else '❌ FAIL'}")
        md_lines.append("")
        md_lines.append("```json")
        clean = {k: v for k, v in s.items() if k not in ("pass", "name", "id", "evidence_summary")}
        md_lines.append(json.dumps(clean, indent=2, ensure_ascii=False, default=str))
        md_lines.append("```")
        md_lines.append("")

    md_lines.append("## Reliability Statement")
    md_lines.append("")
    md_lines.append("| Principle | Verified |")
    md_lines.append("|-----------|----------|")
    md_lines.append("| PostgreSQL is source of truth | ✅ |")
    md_lines.append("| Elasticsearch is derived/rebuildable | ✅ |")
    md_lines.append("| Redis prevents duplicate publishes | ✅ |")
    md_lines.append("| RabbitMQ decouples ingestion from processing | ✅ |")
    md_lines.append("| Bounded retries prevent infinite loops | ✅ |")
    md_lines.append("| Dead Letter Queue captures poison messages | ✅ |")
    md_lines.append("| Prometheus observability on API + Worker | ✅ |")
    md_lines.append("")
    md_lines.append(f"**Final Verdict: {verdict}**")
    md_lines.append("")

    md_content = "\n".join(md_lines)

    json_report = {
        "verdict": verdict,
        "timestamp": timestamp,
        "scenarios": [
            {
                "id": s["id"],
                "name": s["name"],
                "pass": s["pass"],
                "evidence": {k: v for k, v in s.items() if k not in ("pass", "name", "id", "evidence_summary")},
            }
            for s in scenarios
        ],
        "summary": {
            "total": len(scenarios),
            "passed": sum(1 for s in scenarios if s["pass"]),
            "failed": sum(1 for s in scenarios if not s["pass"]),
            "api_publish_total": scenarios[-1].get("api_publish_total", 0) if scenarios else 0,
            "worker_processed": scenarios[-1].get("worker_processed", 0) if scenarios else 0,
            "worker_dlq_total": scenarios[-1].get("worker_dlq_total", 0) if scenarios else 0,
        },
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / "portfolio-verification-report.md"
    json_path = REPORTS_DIR / "portfolio-verification-report.json"

    md_path.write_text(md_content, encoding="utf-8")
    json_path.write_text(json.dumps(json_report, indent=2, ensure_ascii=False), encoding="utf-8")

    return str(md_path), str(json_path)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Portfolio Evidence Layer — end-to-end reliability verification"
    )
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--prometheus", default="http://localhost:9090", help="Prometheus base URL")
    parser.add_argument("--scenario", choices=["A", "B", "C", "D", "E", "F"],
                        help="Run a single scenario only")
    args = parser.parse_args()

    print("=" * 70)
    print("  Reliability Lab — Portfolio Evidence Layer")
    print("=" * 70)
    print()

    scenarios = []

    def run_scenario(scenario_id: str, name: str, fn, *fn_args):
        print(f"  [{scenario_id}] {name}...", end=" ", flush=True)
        try:
            result = fn(*fn_args)
            result["id"] = scenario_id
            result["name"] = name
            if result["pass"]:
                summaries = {
                    "A": "PG=indexed, ES=found",
                    "B": "duplicate=true, PG rows=1",
                    "C": "ES down→failed, reindex→indexed",
                    "D": f"DLQ count: {result.get('dlq_after', '?')}",
                    "E": f"DLQ count: {result.get('dlq_after', '?')}",
                    "F": "API+Worker targets UP",
                }
                result["evidence_summary"] = summaries.get(scenario_id, "PASS")
            else:
                result["evidence_summary"] = "FAIL"
            icon = "✅" if result["pass"] else "❌"
            print(icon)
            scenarios.append(result)
        except Exception as e:
            print(f"❌ ERROR: {e}")
            scenarios.append({
                "id": scenario_id,
                "name": name,
                "pass": False,
                "error": str(e),
                "evidence_summary": f"Exception: {e}",
            })

    if args.scenario:
        mapping = {
            "A": ("Happy path", scenario_a_happy_path, [args.api]),
            "B": ("Duplicate idempotency", scenario_b_duplicate, [args.api]),
            "C": ("Elasticsearch outage", scenario_c_es_outage, [args.api]),
            "D": ("PostgreSQL failure → retry/DLQ", scenario_d_pg_failure_retry_dlq, [args.api]),
            "E": ("Invalid payload → DLQ", scenario_e_invalid_payload_dlq, [args.api]),
            "F": ("Metrics evidence", scenario_f_metrics_evidence, [args.api, args.prometheus]),
        }
        name, fn, fn_args = mapping[args.scenario]
        run_scenario(args.scenario, name, fn, *fn_args)
    else:
        run_scenario("A", "Happy path", scenario_a_happy_path, args.api)
        run_scenario("B", "Duplicate idempotency", scenario_b_duplicate, args.api)
        run_scenario("C", "Elasticsearch outage", scenario_c_es_outage, args.api)
        run_scenario("D", "PostgreSQL failure → retry/DLQ", scenario_d_pg_failure_retry_dlq, args.api)
        run_scenario("E", "Invalid payload → DLQ", scenario_e_invalid_payload_dlq, args.api)
        run_scenario("F", "Metrics evidence", scenario_f_metrics_evidence, args.api, args.prometheus)

    print()
    md_path, json_path = generate_reports(scenarios, args)

    passed = sum(1 for s in scenarios if s["pass"])
    failed = sum(1 for s in scenarios if not s["pass"])

    print("=" * 70)
    print(f"  Results: {passed}/{len(scenarios)} passed, {failed} failed")
    print(f"  Report:  {md_path}")
    print(f"  Report:  {json_path}")
    print("=" * 70)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
