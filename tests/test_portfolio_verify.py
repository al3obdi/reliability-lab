"""Test portfolio_verify report generation.

These tests verify that the report generation logic works correctly
without running the full end-to-end scenarios (which take 2+ minutes).
"""

import json
import sys
from pathlib import Path

# Add scripts/ to path so we can import portfolio_verify
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import portfolio_verify as pv


def test_generate_reports_creates_files(tmp_path):
    """Report generation creates both .md and .json files."""
    # Override REPORTS_DIR to use tmp_path
    original_reports = pv.REPORTS_DIR
    pv.REPORTS_DIR = tmp_path

    try:
        scenarios = [
            {
                "id": "A",
                "name": "Happy path",
                "pass": True,
                "message_id": "test-001",
                "published": {"status": 202},
                "pg_found": True,
                "index_status": "indexed",
                "es_document_exists": True,
                "evidence_summary": "PG=indexed, ES=found",
            },
            {
                "id": "B",
                "name": "Duplicate idempotency",
                "pass": True,
                "message_id": "test-002",
                "first_publish": {"status": 202},
                "second_publish": {"status": 202, "body": {"duplicate": True}},
                "pg_row_count": 1,
                "evidence_summary": "duplicate=true, PG rows=1",
            },
        ]

        class Args:
            api = "http://localhost:8000"
            prometheus = "http://localhost:9090"

        md_path, json_path = pv.generate_reports(scenarios, Args())

        # Verify files exist
        assert Path(md_path).exists(), f"MD report not found at {md_path}"
        assert Path(json_path).exists(), f"JSON report not found at {json_path}"

        # Verify MD content
        md_content = Path(md_path).read_text()
        assert "# Portfolio Verification Report" in md_content
        assert "✅ PASS" in md_content
        assert "Happy path" in md_content
        assert "Duplicate idempotency" in md_content
        assert "Reliability Statement" in md_content
        assert "PostgreSQL is source of truth" in md_content

        # Verify JSON content
        json_content = json.loads(Path(json_path).read_text())
        assert json_content["verdict"] == "PASS"
        assert len(json_content["scenarios"]) == 2
        assert json_content["scenarios"][0]["id"] == "A"
        assert json_content["scenarios"][0]["pass"] is True
        assert json_content["summary"]["total"] == 2
        assert json_content["summary"]["passed"] == 2
        assert json_content["summary"]["failed"] == 0

    finally:
        pv.REPORTS_DIR = original_reports


def test_generate_reports_fail_verdict(tmp_path):
    """When any scenario fails, verdict is FAIL."""
    original_reports = pv.REPORTS_DIR
    pv.REPORTS_DIR = tmp_path

    try:
        scenarios = [
            {
                "id": "A",
                "name": "Happy path",
                "pass": True,
                "evidence_summary": "ok",
            },
            {
                "id": "D",
                "name": "PG failure → DLQ",
                "pass": False,
                "error": "DLQ not found",
                "evidence_summary": "FAIL",
            },
        ]

        class Args:
            api = "http://localhost:8000"
            prometheus = "http://localhost:9090"

        _, json_path = pv.generate_reports(scenarios, Args())

        json_content = json.loads(Path(json_path).read_text())
        assert json_content["verdict"] == "FAIL"
        assert json_content["summary"]["passed"] == 1
        assert json_content["summary"]["failed"] == 1

    finally:
        pv.REPORTS_DIR = original_reports


def test_generate_reports_json_is_valid_json(tmp_path):
    """JSON report is valid, parseable JSON."""
    original_reports = pv.REPORTS_DIR
    pv.REPORTS_DIR = tmp_path

    try:
        scenarios = [
            {
                "id": "A",
                "name": "Test",
                "pass": True,
                "nested": {"key": [1, 2, 3]},
                "unicode": "مرحبا",
                "evidence_summary": "ok",
            },
        ]

        class Args:
            api = "http://localhost:8000"
            prometheus = "http://localhost:9090"

        _, json_path = pv.generate_reports(scenarios, Args())

        # Should parse without error
        data = json.loads(Path(json_path).read_text())
        assert data["verdict"] == "PASS"
        assert "مرحبا" in json.dumps(data, ensure_ascii=False)

    finally:
        pv.REPORTS_DIR = original_reports
