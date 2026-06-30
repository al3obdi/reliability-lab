#!/usr/bin/env python3
"""Load and Backpressure Verification — concurrent load generator with evidence collection.

Publishes Arabic messages through the API with configurable concurrency,
then verifies persistence in PostgreSQL, Elasticsearch indexing, and
captures Prometheus metrics and DLQ state (with before/after delta).

Generates:
  reports/load-backpressure-report.md
  reports/load-backpressure-report.json

Usage:
    python scripts/load_verify.py --count 1000 --concurrency 20
    python scripts/load_verify.py --count 100 --concurrency 5 --customer-prefix load
    make load-verify ARGS="--count 100 --concurrency 10"
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ── Configuration ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"

PG_CONTAINER = "reliability-lab-postgres-1"
RABBITMQ_CONTAINER = "reliability-lab-rabbitmq-1"

SAMPLE_TEXTS = [
    "مرحبا، أريد الاستفسار عن طلبي رقم ٥٥٣٢",
    "السلام عليكم، هل يمكنني تغيير موعد التسليم؟",
    "أريد إلغاء الطلب رقم ١٢٣٤ من فضلك",
    "شكرا على الخدمة الممتازة، وصل الطلب قبل الموعد",
    "هل يوجد توصيل إلى مدينة الرياض؟",
    "أريد تتبع الشحنة رقم ٧٨٩٠",
    "الفاتورة غير صحيحة، المبلغ المدفوع أكثر من المطلوب",
    "متى يصل مندوب التوصيل؟ أنا في انتظاره منذ ساعة",
    "المنتج وصل تالف، أريد استبداله أو استرداد المبلغ",
    "هل تقبلون الدفع عند الاستلام؟",
    "أريد تغيير عنوان التوصيل إلى حي النزهة",
    "كم المدة المتوقعة للتوصيل داخل جدة؟",
    "الطلب رقم ٤٤٥٥ لم يصل بعد، مضى عليه ٥ أيام",
    "هل يمكنني إضافة منتج آخر للطلب قبل الشحن؟",
    "شكرا جزيلا، التجربة كانت رائعة وسأكرر الطلب",
]

CHANNELS = ["web", "mobile", "email", "whatsapp"]


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


def _prometheus_metric(metric_name: str) -> float:
    """Scrape a Prometheus metric from the API /metrics endpoint."""
    try:
        r = httpx.get("http://localhost:8000/metrics", timeout=5)
        for line in r.text.split("\n"):
            if line.startswith(metric_name) and not line.startswith(metric_name + "_"):
                parts = line.split()
                if len(parts) >= 2:
                    return float(parts[-1])
    except Exception:
        pass
    return -1.0


def _worker_metric(metric_name: str) -> float:
    """Scrape a Prometheus metric from the Worker /metrics endpoint."""
    try:
        r = httpx.get("http://localhost:9100/metrics", timeout=5)
        for line in r.text.split("\n"):
            if line.startswith(metric_name) and not line.startswith(metric_name + "_"):
                parts = line.split()
                if len(parts) >= 2:
                    return float(parts[-1])
    except Exception:
        pass
    return -1.0


def _es_count() -> int:
    """Get total document count from Elasticsearch."""
    try:
        r = httpx.get("http://localhost:9200/messages-v1/_count", timeout=5)
        if r.status_code == 200:
            return r.json().get("count", -1)
    except Exception:
        pass
    return -1


# ═══════════════════════════════════════════════════════════════════════
# Concurrent publisher
# ═══════════════════════════════════════════════════════════════════════

class LoadResult:
    """Thread-safe accumulator for load test results."""

    def __init__(self):
        self.attempted = 0
        self.published = 0
        self.duplicates = 0
        self.failures = 0
        self.message_ids: list[str] = []
        self._lock = asyncio.Lock()

    async def record(self, status_code: int, body: dict, msg_id: str):
        async with self._lock:
            self.attempted += 1
            if status_code == 202:
                if body.get("duplicate"):
                    self.duplicates += 1
                else:
                    self.published += 1
                    self.message_ids.append(msg_id)
            else:
                self.failures += 1


async def publish_one(client: httpx.AsyncClient, api_url: str, msg_id: str,
                      customer_id: str, text: str, channel: str,
                      result: LoadResult, sem: asyncio.Semaphore):
    """Publish a single message through the API with concurrency control."""
    async with sem:
        payload = {
            "message_id": msg_id,
            "customer_id": customer_id,
            "text": text,
            "channel": channel,
        }
        try:
            r = await client.post(
                f"{api_url}/api/v1/messages",
                json=payload,
                timeout=30.0,
            )
            body = r.json() if r.text else {}
            await result.record(r.status_code, body, msg_id)
        except Exception:
            await result.record(0, {}, msg_id)


async def run_load(args) -> LoadResult:
    """Run the concurrent load test."""
    result = LoadResult()
    sem = asyncio.Semaphore(args.concurrency)

    limits = httpx.Limits(
        max_keepalive_connections=args.concurrency + 10,
        max_connections=args.concurrency + 10,
    )
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = []
        for i in range(args.count):
            msg_id = str(uuid.uuid4())
            customer_id = f"{args.customer_prefix}-{i:05d}"
            text = SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)]
            channel = CHANNELS[i % len(CHANNELS)]
            tasks.append(
                publish_one(client, args.api, msg_id, customer_id, text, channel,
                            result, sem)
            )
        await asyncio.gather(*tasks)

    return result


# ═══════════════════════════════════════════════════════════════════════
# Verification
# ═══════════════════════════════════════════════════════════════════════

def verify_persistence(customer_prefix: str, expected_count: int,
                       timeout_sec: int = 120) -> dict:
    """Wait for all published messages to appear in PostgreSQL.

    Returns dict with final counts and timing.
    """
    start = time.monotonic()
    deadline = start + timeout_sec

    pg_count = 0
    indexed_count = 0
    failed_index_count = 0
    pending_count = 0

    while time.monotonic() < deadline:
        raw = _pg_query(
            f"SELECT COUNT(*) FROM messages WHERE customer_id LIKE '{customer_prefix}-%'"
        )
        try:
            pg_count = int(raw) if raw.strip() else 0
        except ValueError:
            pg_count = 0

        if pg_count >= expected_count:
            break
        time.sleep(2)

    elapsed = time.monotonic() - start

    if pg_count > 0:
        raw = _pg_query(
            f"SELECT COUNT(*) FROM messages WHERE customer_id LIKE '{customer_prefix}-%' "
            f"AND index_status = 'indexed'"
        )
        try:
            indexed_count = int(raw) if raw.strip() else 0
        except ValueError:
            indexed_count = 0

        raw = _pg_query(
            f"SELECT COUNT(*) FROM messages WHERE customer_id LIKE '{customer_prefix}-%' "
            f"AND index_status = 'failed'"
        )
        try:
            failed_index_count = int(raw) if raw.strip() else 0
        except ValueError:
            failed_index_count = 0

        raw = _pg_query(
            f"SELECT COUNT(*) FROM messages WHERE customer_id LIKE '{customer_prefix}-%' "
            f"AND index_status = 'pending'"
        )
        try:
            pending_count = int(raw) if raw.strip() else 0
        except ValueError:
            pending_count = 0

    return {
        "pg_count": pg_count,
        "indexed_count": indexed_count,
        "failed_index_count": failed_index_count,
        "pending_count": pending_count,
        "wait_seconds": round(elapsed, 1),
        "fully_persisted": pg_count >= expected_count,
    }


def capture_metrics_snapshot() -> dict:
    """Capture a snapshot of key Prometheus metrics from API and Worker."""
    api_metrics = {}
    worker_metrics = {}

    for name in ["api_publish_total", "api_duplicate_total", "api_publish_failures_total"]:
        api_metrics[name] = _prometheus_metric(name)

    for name in ["worker_messages_processed_total", "worker_messages_failed_total",
                 "worker_messages_retried_total", "worker_messages_dlq_total",
                 "worker_pg_insert_total", "worker_es_index_total",
                 "worker_es_index_failed_total"]:
        worker_metrics[name] = _worker_metric(name)

    return {
        "api": api_metrics,
        "worker": worker_metrics,
    }


def capture_queue_snapshot() -> dict:
    """Capture RabbitMQ queue depths."""
    queues = ["events.queue", "events.retry.15s", "events.retry.30s",
              "events.retry.60s", "events.dlq"]
    return {q: _rmq_queue_count(q) for q in queues}


# ═══════════════════════════════════════════════════════════════════════
# Report generation
# ═══════════════════════════════════════════════════════════════════════

def generate_reports(result: LoadResult, persistence: dict,
                     metrics: dict, queues: dict,
                     args, duration: float, es_total: int,
                     dlq_before: int, dlq_after: int) -> tuple[str, str]:
    """Generate Markdown and JSON reports. Returns (md_path, json_path)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rate = result.attempted / duration if duration > 0 else 0
    dlq_delta = dlq_after - dlq_before

    # ── Markdown report ──────────────────────────────────────────
    md_lines = []
    md_lines.append("# Load and Backpressure Verification Report")
    md_lines.append("")
    md_lines.append(f"**Generated:** {timestamp}")
    md_lines.append(f"**Input:** {args.count} messages, concurrency={args.concurrency}")
    md_lines.append("")

    md_lines.append("## Publish Results")
    md_lines.append("")
    md_lines.append("| Metric | Value |")
    md_lines.append("|--------|-------|")
    md_lines.append(f"| Total attempted | {result.attempted} |")
    md_lines.append(f"| Published (new) | {result.published} |")
    md_lines.append(f"| Duplicates | {result.duplicates} |")
    md_lines.append(f"| Failures | {result.failures} |")
    md_lines.append(f"| Publish duration | {duration:.1f}s |")
    md_lines.append(f"| Approximate rate | {rate:.1f} msg/s |")
    md_lines.append("")

    md_lines.append("## Persistence Verification")
    md_lines.append("")
    md_lines.append("| Metric | Value |")
    md_lines.append("|--------|-------|")
    md_lines.append(f"| PostgreSQL rows (this run) | {persistence['pg_count']} |")
    md_lines.append(f"| Expected rows | {result.published} |")
    md_lines.append(f"| Fully persisted | {'✅ Yes' if persistence['fully_persisted'] else '❌ No'} |")
    md_lines.append(f"| Indexed in ES | {persistence['indexed_count']} |")
    md_lines.append(f"| Index failed | {persistence['failed_index_count']} |")
    md_lines.append(f"| Index pending | {persistence['pending_count']} |")
    md_lines.append(f"| Wait time for persistence | {persistence['wait_seconds']}s |")
    md_lines.append(f"| ES total documents | {es_total} |")
    md_lines.append("")

    md_lines.append("## Queue Health")
    md_lines.append("")
    md_lines.append("| Queue | Message Count |")
    md_lines.append("|-------|---------------|")
    for q, count in queues.items():
        md_lines.append(f"| {q} | {count} |")
    md_lines.append("")

    md_lines.append("### Dead Letter Queue Delta")
    md_lines.append("")
    md_lines.append("| Metric | Value |")
    md_lines.append("|--------|-------|")
    md_lines.append(f"| DLQ before load run | {dlq_before} |")
    md_lines.append(f"| DLQ after load run | {dlq_after} |")
    md_lines.append(f"| DLQ delta (this run) | {dlq_delta} |")
    md_lines.append(f"| DLQ clean | {'✅ Yes' if dlq_delta == 0 else '❌ No (+' + str(dlq_delta) + ')'} |")
    md_lines.append("")

    md_lines.append("## Prometheus Metrics Snapshot")
    md_lines.append("")
    md_lines.append("### API Metrics")
    md_lines.append("")
    md_lines.append("| Metric | Value |")
    md_lines.append("|--------|-------|")
    for name, val in metrics["api"].items():
        md_lines.append(f"| {name} | {val} |")
    md_lines.append("")
    md_lines.append("### Worker Metrics")
    md_lines.append("")
    md_lines.append("| Metric | Value |")
    md_lines.append("|--------|-------|")
    for name, val in metrics["worker"].items():
        md_lines.append(f"| {name} | {val} |")
    md_lines.append("")

    md_lines.append("## Observations")
    md_lines.append("")
    if persistence["fully_persisted"]:
        md_lines.append(f"- ✅ All {result.published} published messages were persisted in PostgreSQL.")
    else:
        md_lines.append(f"- ⚠️ Only {persistence['pg_count']}/{result.published} messages persisted — "
                        f"some may still be in-flight or in retry queues.")
    if persistence["indexed_count"] == persistence["pg_count"]:
        md_lines.append("- ✅ All persisted messages were indexed in Elasticsearch.")
    elif persistence["indexed_count"] > 0:
        md_lines.append(f"- ⚠️ {persistence['indexed_count']}/{persistence['pg_count']} messages indexed; "
                        f"{persistence['pending_count']} pending, {persistence['failed_index_count']} failed.")
    if result.failures > 0:
        md_lines.append(f"- ⚠️ {result.failures} publish failures — check API and RabbitMQ health.")
    if dlq_delta == 0:
        md_lines.append(f"- ✅ DLQ delta = 0 — no new dead-lettered messages from this load run.")
    else:
        md_lines.append(f"- ⚠️ DLQ delta = +{dlq_delta} — {dlq_delta} new messages in DLQ from this run.")
    if dlq_after > 0 and dlq_delta == 0:
        md_lines.append(f"- ℹ️ DLQ has {dlq_after} pre-existing messages (from prior scenarios, not this run).")
    md_lines.append("")

    md_lines.append("## Bottlenecks and Limits")
    md_lines.append("")
    md_lines.append(f"- **Publish throughput:** {rate:.1f} msg/s at concurrency={args.concurrency}")
    md_lines.append("- **Worker processing:** check `worker_messages_processed_total` vs publish rate")
    md_lines.append("- **Queue buildup:** if `events.queue` > 0, workers are not keeping up")
    md_lines.append("- **Retry queues:** non-zero counts indicate transient failures (PG/ES)")
    md_lines.append("")

    md_lines.append("## Worker Scaling Comparison")
    md_lines.append("")
    md_lines.append("To compare throughput with different worker counts:")
    md_lines.append("")
    md_lines.append("```bash")
    md_lines.append("# 1 worker (default)")
    md_lines.append("docker compose up -d --scale worker=1")
    md_lines.append('make load-verify ARGS="--count 500 --concurrency 20"')
    md_lines.append("")
    md_lines.append("# 3 workers")
    md_lines.append("docker compose up -d --scale worker=3")
    md_lines.append('make load-verify ARGS="--count 500 --concurrency 20"')
    md_lines.append("```")
    md_lines.append("")
    md_lines.append("Compare the `worker_messages_processed_total` rate and queue depths between runs.")
    md_lines.append("")

    md_lines.append("## Honest Note")
    md_lines.append("")
    md_lines.append("This is a **local Docker lab**, not a production benchmark. Results reflect")
    md_lines.append("single-machine performance with all services on one host. Production throughput")
    md_lines.append("would differ significantly due to network latency, resource contention, and")
    md_lines.append("horizontal scaling. This test validates that the pipeline handles concurrent")
    md_lines.append("load correctly — not that it achieves a specific throughput number.")
    md_lines.append("")

    md_content = "\n".join(md_lines)

    # ── JSON report ──────────────────────────────────────────────
    json_report = {
        "report_type": "load-backpressure-verification",
        "timestamp": timestamp,
        "input": {
            "count": args.count,
            "concurrency": args.concurrency,
            "customer_prefix": args.customer_prefix,
        },
        "publish": {
            "attempted": result.attempted,
            "published": result.published,
            "duplicates": result.duplicates,
            "failures": result.failures,
            "duration_seconds": round(duration, 2),
            "rate_per_second": round(rate, 1),
        },
        "persistence": persistence,
        "queues": queues,
        "dlq": {
            "before": dlq_before,
            "after": dlq_after,
            "delta": dlq_delta,
            "clean": dlq_delta == 0,
        },
        "metrics": metrics,
        "elasticsearch_total_documents": es_total,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / "load-backpressure-report.md"
    json_path = REPORTS_DIR / "load-backpressure-report.json"

    md_path.write_text(md_content, encoding="utf-8")
    json_path.write_text(json.dumps(json_report, indent=2, ensure_ascii=False), encoding="utf-8")

    return str(md_path), str(json_path)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Load and Backpressure Verification — concurrent load generator"
    )
    parser.add_argument("--count", type=int, default=1000,
                        help="Number of messages to publish (default: 1000)")
    parser.add_argument("--concurrency", type=int, default=20,
                        help="Max concurrent HTTP connections (default: 20)")
    parser.add_argument("--customer-prefix", type=str, default="load",
                        help="Customer ID prefix for this run (default: load)")
    parser.add_argument("--api", type=str, default="http://localhost:8000",
                        help="API base URL")
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip persistence verification (publish only)")
    args = parser.parse_args()

    print("=" * 70)
    print("  Reliability Lab — Load and Backpressure Verification")
    print("=" * 70)
    print(f"  Messages:    {args.count}")
    print(f"  Concurrency: {args.concurrency}")
    print(f"  Prefix:      {args.customer_prefix}")
    print()

    # ── Phase 0: Capture DLQ baseline ─────────────────────────────
    dlq_before = _rmq_queue_count("events.dlq")
    print(f"── Phase 0: DLQ baseline: {dlq_before} ──")
    print()

    # ── Phase 1: Publish ──────────────────────────────────────────
    print("── Phase 1: Publishing messages ──")
    start = time.monotonic()
    result = asyncio.run(run_load(args))
    duration = time.monotonic() - start
    rate = result.attempted / duration if duration > 0 else 0

    print(f"  Attempted:  {result.attempted}")
    print(f"  Published:  {result.published}")
    print(f"  Duplicates: {result.duplicates}")
    print(f"  Failures:   {result.failures}")
    print(f"  Duration:   {duration:.1f}s")
    print(f"  Rate:       {rate:.1f} msg/s")
    print()

    # ── Phase 2: Verify persistence ───────────────────────────────
    persistence = {"pg_count": 0, "indexed_count": 0, "failed_index_count": 0,
                   "pending_count": 0, "wait_seconds": 0, "fully_persisted": False}
    if not args.no_verify and result.published > 0:
        print("── Phase 2: Verifying persistence ──")
        persistence = verify_persistence(args.customer_prefix, result.published)
        print(f"  PG rows:     {persistence['pg_count']}/{result.published}")
        print(f"  Indexed:     {persistence['indexed_count']}")
        print(f"  Index fail:  {persistence['failed_index_count']}")
        print(f"  Index pend:  {persistence['pending_count']}")
        print(f"  Wait time:   {persistence['wait_seconds']}s")
        print(f"  Persisted:   {'✅ YES' if persistence['fully_persisted'] else '❌ NO'}")
        print()

    # ── Phase 3: Capture metrics and queue state ──────────────────
    print("── Phase 3: Capturing metrics and queue state ──")
    metrics = capture_metrics_snapshot()
    queues = capture_queue_snapshot()
    es_total = _es_count()
    dlq_after = queues.get("events.dlq", -1)
    dlq_delta = dlq_after - dlq_before

    print(f"  API publish_total:     {metrics['api'].get('api_publish_total', '?')}")
    print(f"  Worker processed:      {metrics['worker'].get('worker_messages_processed_total', '?')}")
    print(f"  Worker DLQ'd:          {metrics['worker'].get('worker_messages_dlq_total', '?')}")
    print(f"  events.queue depth:    {queues.get('events.queue', '?')}")
    print(f"  DLQ before:            {dlq_before}")
    print(f"  DLQ after:             {dlq_after}")
    print(f"  DLQ delta:             {dlq_delta} {'✅' if dlq_delta == 0 else '❌'}")
    print(f"  ES total documents:    {es_total}")
    print()

    # ── Phase 4: Generate reports ─────────────────────────────────
    print("── Phase 4: Generating reports ──")
    md_path, json_path = generate_reports(
        result, persistence, metrics, queues, args, duration, es_total,
        dlq_before, dlq_after,
    )
    print(f"  Report: {md_path}")
    print(f"  Report: {json_path}")
    print()

    # ── Summary ───────────────────────────────────────────────────
    print("=" * 70)
    all_ok = (
        result.failures == 0
        and persistence["fully_persisted"]
        and dlq_delta == 0
    )
    if all_ok:
        print("  ✅ Load verification PASSED")
    else:
        print("  ⚠️  Load verification completed with warnings")
        if result.failures > 0:
            print(f"     - {result.failures} publish failures")
        if not persistence["fully_persisted"]:
            print(f"     - Not all messages persisted")
        if dlq_delta != 0:
            print(f"     - DLQ delta = +{dlq_delta} (new messages in DLQ from this run)")
    print("=" * 70)

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
