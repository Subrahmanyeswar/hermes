"""
tests/test_cost_accounting.py
HERMES Gate 20: Tier 3 Cost Accounting Test Suite.

Validates:
- Logical requests vs underlying provider attempts.
- Exact token accounting (input, output, total).
- Decimal cost calculation and precision.
- Cost per successful mission using Gate 18 objective status (NOT self-report).
- Cost per 100 missions normalization.
- Division-by-zero protection when 0 successful missions occur.
- Honest tracking of unavailable T3 calls without fake $0 or 0 tokens.
- Credential sanitization (zero secrets or API keys in telemetry).
"""

from decimal import Decimal
import json
from pathlib import Path
import pytest

from benchmarks.cost_accounting import (
    aggregate_t3_cost_metrics,
    sanitize_telemetry,
    COST_ACCOUNTING_VERSION
)

WORKSPACE = Path(__file__).resolve().parent.parent
COST_SUMMARY_PATH = WORKSPACE / "artifacts" / "final_benchmark_cost_summary.json"
COST_MANIFEST_PATH = WORKSPACE / "artifacts" / "final_benchmark_cost_manifest.json"


def test_cost_artifacts_exist():
    """Validates that final_benchmark_cost_summary.json and manifest exist."""
    assert COST_SUMMARY_PATH.exists()
    assert COST_MANIFEST_PATH.exists()
    manifest = json.loads(COST_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["cost_accounting_version"] == "1.0.0"
    assert manifest["frozen"] is True
    assert manifest["benchmark_execution_allowed"] is False


def test_t3_logical_requests_vs_attempts():
    """Validates that multiple provider attempts do not artificially inflate logical request count."""
    t3_records = [
        {"mission_id": "m1", "task_id": "A01", "requested_model": "m", "requested_provider": "p", "provider_attempts": 3, "reported_cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50},
        {"mission_id": "m2", "task_id": "A02", "requested_model": "m", "requested_provider": "p", "provider_attempts": 1, "reported_cost_usd": 0.02, "input_tokens": 200, "output_tokens": 100}
    ]
    missions = [{"mission_id": "m1", "objective_status": "PASS"}, {"mission_id": "m2", "objective_status": "PASS"}]
    summary = aggregate_t3_cost_metrics(t3_records, missions)

    assert summary["t3"]["logical_requests"] == 2
    assert summary["t3"]["provider_attempts"] == 4
    assert summary["t3"]["input_tokens"] == 300
    assert summary["t3"]["output_tokens"] == 150
    assert summary["t3"]["total_tokens"] == 450
    assert summary["t3"]["total_cost_usd"] == 0.03


def test_cost_per_successful_mission_uses_objective_status():
    """Validates that cost per successful mission only divides by objectively passed missions."""
    t3_records = [
        {"mission_id": "m1", "task_id": "A01", "reported_cost_usd": 0.05, "input_tokens": 100, "output_tokens": 50},
        {"mission_id": "m2", "task_id": "A02", "reported_cost_usd": 0.05, "input_tokens": 100, "output_tokens": 50}
    ]
    # m1 passed objectively, m2 failed objectively (even if agent self-reported completed)
    missions = [
        {"mission_id": "m1", "objective_status": "PASS", "hermes_reported_status": "COMPLETED"},
        {"mission_id": "m2", "objective_status": "FAIL", "hermes_reported_status": "COMPLETED"},
        {"mission_id": "m3", "objective_status": "PASS", "hermes_reported_status": "COMPLETED"}
    ]
    summary = aggregate_t3_cost_metrics(t3_records, missions)

    assert summary["t3"]["t3_successful_missions_count"] == 1  # Only m1!
    assert summary["t3"]["total_cost_usd"] == 0.10
    # Cost per successful mission = 0.10 / 1 = 0.10
    assert summary["t3"]["cost_per_successful_mission_usd"] == 0.10


def test_cost_per_100_missions_normalization():
    """Validates cost per 100 missions scaling math."""
    t3_records = [{"mission_id": "m1", "reported_cost_usd": 0.05}]
    missions = [{"mission_id": f"m{i}", "objective_status": "PASS"} for i in range(1, 51)]  # 50 missions
    summary = aggregate_t3_cost_metrics(t3_records, missions)

    assert summary["missions_evaluated"] == 50
    assert summary["t3"]["total_cost_usd"] == 0.05
    # (0.05 / 50) * 100 = 0.10
    assert summary["t3"]["cost_per_100_missions_usd"] == 0.10


def test_zero_successful_missions_no_divide_by_zero():
    """Validates that 0 successful missions returns None / NOT_AVAILABLE without crashing."""
    t3_records = [{"mission_id": "m1", "reported_cost_usd": 0.05}]
    missions = [{"mission_id": "m1", "objective_status": "FAIL"}]
    summary = aggregate_t3_cost_metrics(t3_records, missions)

    assert summary["t3"]["t3_successful_missions_count"] == 0
    assert summary["t3"]["cost_per_successful_mission_usd"] is None


def test_unavailable_t3_no_fake_zeros():
    """Validates that unavailable T3 calls do not report fake zero cost or token counts."""
    t3_records = [
        {"mission_id": "m1", "status": "NOT_AVAILABLE", "reported_cost_usd": None, "input_tokens": None, "output_tokens": None}
    ]
    missions = [{"mission_id": "m1", "objective_status": "FAIL"}]
    summary = aggregate_t3_cost_metrics(t3_records, missions)

    assert summary["t3"]["total_cost_usd"] is None
    assert summary["t3"]["cost_status"] == "NOT_AVAILABLE"
    assert summary["t3"]["input_tokens"] is None
    assert summary["t3"]["total_tokens"] is None


def test_telemetry_sanitization_removes_secrets():
    """Validates that secrets, api keys, and bearer tokens are redacted."""
    raw_data = {
        "mission_id": "m1",
        "api_key": "sk-secret-123456",
        "auth_header": "Bearer token_xyz",
        "input_tokens": 150,
        "nested": {
            "openrouter_secret": "sensitive_data",
            "model": "stealth/ox-alpha"
        }
    }
    clean = sanitize_telemetry(raw_data)
    assert clean["api_key"] == "[REDACTED]"
    assert clean["auth_header"] == "[REDACTED]"
    assert clean["nested"]["openrouter_secret"] == "[REDACTED]"
    assert clean["input_tokens"] == 150
    assert clean["nested"]["model"] == "stealth/ox-alpha"
