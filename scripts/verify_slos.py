"""Verify SLOs by querying Prometheus metrics.

Usage:
    python scripts/verify_slos.py
    python scripts/verify_slos.py --prometheus http://localhost:9090
"""

import argparse
import sys
import urllib.request
import json


def query_prometheus(prometheus_url: str, query: str) -> float:
    """Run an instant query against Prometheus and return the scalar value."""
    url = f"{prometheus_url}/api/v1/query?query={urllib.request.quote(query)}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data["status"] == "success" and data["data"]["result"]:
                value = data["data"]["result"][0]["value"]
                return float(value[1])
    except Exception as exc:
        print(f"  WARNING: Could not query Prometheus: {exc}")
    return 0.0


def main():
    parser = argparse.ArgumentParser(description="Verify SLOs from Prometheus metrics")
    parser.add_argument("--prometheus", type=str, default="http://localhost:9090",
                        help="Prometheus base URL")
    args = parser.parse_args()

    print("=" * 60)
    print("Reliability Lab — SLO Verification")
    print("=" * 60)

    metrics = {
        "Total Published": "api_publish_total",
        "Total Duplicates": "api_duplicate_total",
        "Publish Failures": "api_publish_failures_total",
        "Worker Processed": "worker_messages_processed_total",
        "Worker Failed": "worker_messages_failed_total",
        "Worker Retried": "worker_messages_retried_total",
        "Worker DLQ'd": "worker_messages_dlq_total",
        "PG Inserts": "worker_pg_insert_total",
        "ES Indexed": "worker_es_index_total",
        "ES Index Failed": "worker_es_index_failed_total",
    }

    for label, metric_name in metrics.items():
        value = query_prometheus(args.prometheus, metric_name)
        print(f"  {label:.<30} {value:>10.0f}")

    # Derived SLOs
    published = query_prometheus(args.prometheus, "api_publish_total")
    duplicates = query_prometheus(args.prometheus, "api_duplicate_total")
    failures = query_prometheus(args.prometheus, "api_publish_failures_total")
    processed = query_prometheus(args.prometheus, "worker_messages_processed_total")
    dlq = query_prometheus(args.prometheus, "worker_messages_dlq_total")
    es_failed = query_prometheus(args.prometheus, "worker_es_index_failed_total")

    total_requests = published + duplicates + failures
    print(f"\n  {'Total API Requests':.<30} {total_requests:>10.0f}")

    if total_requests > 0:
        success_rate = (published / total_requests) * 100
        print(f"  {'Publish Success Rate':.<30} {success_rate:>9.1f}%")

    if processed > 0 and es_failed > 0:
        es_success_rate = ((processed - es_failed) / processed) * 100
        print(f"  {'ES Index Success Rate':.<30} {es_success_rate:>9.1f}%")

    print(f"\n  {'DLQ Backlog':.<30} {dlq:>10.0f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
