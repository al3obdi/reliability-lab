"""Test load_verify report generation.

These tests verify that the report generation logic works correctly
without running the full load test (which publishes real messages).
"""

import json
import sys
from pathlib import Path

# Add scripts/ to path so we can import load_verify
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import load_verify as lv


class MockLoadResult:
    """Minimal mock of LoadResult for testing report generation."""

    def __init__(self):
        self.attempted = 100
        self.published = 98
        self.duplicates = 0
        self.failures = 2
        self.message_ids = [f"msg-{i:03d}" for i in range(98)]


class MockArgs:
    """Minimal mock of argparse args for testing report generation."""

    def __init__(self):
        self.count = 100
        self.concurrency = 5
        self.customer_prefix = "load-test"


def test_generate_reports_creates_files(tmp_path):
    """Report generation creates both .md and .json files with DLQ delta."""
    original_reports = lv.REPORTS_DIR
    lv.REPORTS_DIR = tmp_path

    try:
        result = MockLoadResult()
        persistence = {
            "pg_count": 98,
            "indexed_count": 98,
            "failed_index_count": 0,
            "pending_count": 0,
            "wait_seconds": 5.2,
            "fully_persisted": True,
        }
        metrics = {
            "api": {"api_publish_total": 150.0, "api_duplicate_total": 0.0,
                    "api_publish_failures_total": 2.0},
            "worker": {"worker_messages_processed_total": 98.0,
                       "worker_messages_failed_total": 0.0,
                       "worker_messages_retried_total": 0.0,
                       "worker_messages_dlq_total": 0.0,
                       "worker_pg_insert_total": 98.0,
                       "worker_es_index_total": 98.0,
                       "worker_es_index_failed_total": 0.0},
        }
        queues = {
            "events.queue": 0,
            "events.retry.15s": 0,
            "events.retry.30s": 0,
            "events.retry.60s": 0,
            "events.dlq": 1,
        }
        args = MockArgs()
        duration = 3.5
        es_total = 200
        dlq_before = 1
        dlq_after = 1

        md_path, json_path = lv.generate_reports(
            result, persistence, metrics, queues, args, duration, es_total,
            dlq_before, dlq_after,
        )

        # Verify files exist
        assert Path(md_path).exists(), f"MD report not found at {md_path}"
        assert Path(json_path).exists(), f"JSON report not found at {json_path}"

        # Verify MD content
        md_content = Path(md_path).read_text()
        assert "# Load and Backpressure Verification Report" in md_content
        assert "## Publish Results" in md_content
        assert "## Persistence Verification" in md_content
        assert "## Queue Health" in md_content
        assert "### Dead Letter Queue Delta" in md_content
        assert "DLQ before load run" in md_content
        assert "DLQ after load run" in md_content
        assert "DLQ delta (this run)" in md_content
        assert "DLQ clean" in md_content
        assert "## Prometheus Metrics Snapshot" in md_content
        assert "## Observations" in md_content
        assert "## Bottlenecks and Limits" in md_content
        assert "## Worker Scaling Comparison" in md_content
        assert "## Honest Note" in md_content
        assert "98" in md_content  # published count
        assert "local Docker lab" in md_content
        assert "DLQ delta = 0" in md_content  # delta is zero
        assert "pre-existing messages" in md_content  # note about pre-existing

        # Verify JSON content
        json_content = json.loads(Path(json_path).read_text())
        assert json_content["report_type"] == "load-backpressure-verification"
        assert json_content["input"]["count"] == 100
        assert json_content["input"]["concurrency"] == 5
        assert json_content["publish"]["published"] == 98
        assert json_content["publish"]["failures"] == 2
        assert json_content["persistence"]["fully_persisted"] is True
        assert json_content["persistence"]["pg_count"] == 98
        assert json_content["queues"]["events.dlq"] == 1
        assert json_content["dlq"]["before"] == 1
        assert json_content["dlq"]["after"] == 1
        assert json_content["dlq"]["delta"] == 0
        assert json_content["dlq"]["clean"] is True
        assert json_content["metrics"]["api"]["api_publish_total"] == 150.0
        assert json_content["elasticsearch_total_documents"] == 200

    finally:
        lv.REPORTS_DIR = original_reports


def test_generate_reports_json_is_valid_json(tmp_path):
    """JSON report is valid, parseable JSON with Unicode and DLQ fields."""
    original_reports = lv.REPORTS_DIR
    lv.REPORTS_DIR = tmp_path

    try:
        result = MockLoadResult()
        persistence = {
            "pg_count": 50, "indexed_count": 50, "failed_index_count": 0,
            "pending_count": 0, "wait_seconds": 2.0, "fully_persisted": True,
        }
        metrics = {
            "api": {"api_publish_total": 50.0, "api_duplicate_total": 0.0,
                    "api_publish_failures_total": 0.0},
            "worker": {"worker_messages_processed_total": 50.0,
                       "worker_messages_failed_total": 0.0,
                       "worker_messages_retried_total": 0.0,
                       "worker_messages_dlq_total": 0.0,
                       "worker_pg_insert_total": 50.0,
                       "worker_es_index_total": 50.0,
                       "worker_es_index_failed_total": 0.0},
        }
        queues = {"events.queue": 0, "events.retry.15s": 0, "events.retry.30s": 0,
                  "events.retry.60s": 0, "events.dlq": 0}
        args = MockArgs()

        _, json_path = lv.generate_reports(
            result, persistence, metrics, queues, args, 1.5, 100,
            dlq_before=0, dlq_after=0,
        )

        # Should parse without error
        data = json.loads(Path(json_path).read_text())
        assert data["report_type"] == "load-backpressure-verification"
        assert "timestamp" in data
        assert data["publish"]["rate_per_second"] > 0
        assert data["dlq"]["before"] == 0
        assert data["dlq"]["after"] == 0
        assert data["dlq"]["delta"] == 0
        assert data["dlq"]["clean"] is True

    finally:
        lv.REPORTS_DIR = original_reports


def test_generate_reports_with_failures(tmp_path):
    """Report correctly reflects failures and non-zero DLQ delta."""
    original_reports = lv.REPORTS_DIR
    lv.REPORTS_DIR = tmp_path

    try:
        result = MockLoadResult()
        result.attempted = 50
        result.published = 45
        result.failures = 5
        result.message_ids = [f"msg-{i:03d}" for i in range(45)]

        persistence = {
            "pg_count": 45, "indexed_count": 40, "failed_index_count": 3,
            "pending_count": 2, "wait_seconds": 10.0, "fully_persisted": True,
        }
        metrics = {
            "api": {"api_publish_total": 100.0, "api_duplicate_total": 0.0,
                    "api_publish_failures_total": 5.0},
            "worker": {"worker_messages_processed_total": 45.0,
                       "worker_messages_failed_total": 0.0,
                       "worker_messages_retried_total": 0.0,
                       "worker_messages_dlq_total": 3.0,
                       "worker_pg_insert_total": 45.0,
                       "worker_es_index_total": 40.0,
                       "worker_es_index_failed_total": 3.0},
        }
        queues = {"events.queue": 0, "events.retry.15s": 0, "events.retry.30s": 0,
                  "events.retry.60s": 0, "events.dlq": 3}
        args = MockArgs()

        md_path, json_path = lv.generate_reports(
            result, persistence, metrics, queues, args, 2.0, 150,
            dlq_before=0, dlq_after=3,
        )

        md_content = Path(md_path).read_text()
        # Should mention failures
        assert "5" in md_content  # failure count appears somewhere
        assert "DLQ delta" in md_content

        json_content = json.loads(Path(json_path).read_text())
        assert json_content["publish"]["failures"] == 5
        assert json_content["queues"]["events.dlq"] == 3
        assert json_content["dlq"]["before"] == 0
        assert json_content["dlq"]["after"] == 3
        assert json_content["dlq"]["delta"] == 3
        assert json_content["dlq"]["clean"] is False
        assert json_content["persistence"]["failed_index_count"] == 3
        assert json_content["persistence"]["pending_count"] == 2

    finally:
        lv.REPORTS_DIR = original_reports
