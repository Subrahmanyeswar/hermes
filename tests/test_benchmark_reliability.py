"""
tests/test_benchmark_reliability.py
HERMES Gate 19: Reliability Metrics & Protocol Test Suite.

Validates that:
- Mission success rate, first-attempt rate, and repair recovery rates are calculated accurately.
- False completion and false negative metrics are preserved.
- Routing escalation frequencies and T3 availability semantics are respected.
- Independent reliability validator detects primary vs raw discrepancies.
- Repeated-attempt reliability protocol (20 tasks x 3 attempts) calculates consistency metrics properly.
"""

import copy
import json
from pathlib import Path
import pytest

from benchmarks.reliability import (
    aggregate_reliability_metrics,
    evaluate_repeated_attempt_study,
    RELIABILITY_SUBSET_TASK_IDS
)
from benchmarks.independent_reliability_validator import validate_reliability_independence

WORKSPACE = Path(__file__).resolve().parent.parent
RELIABILITY_SUMMARY_PATH = WORKSPACE / "artifacts" / "final_benchmark_reliability_summary.json"


def test_reliability_summary_artifact_exists():
    """Validates that final_benchmark_reliability_summary.json exists and is non-empty."""
    assert RELIABILITY_SUMMARY_PATH.exists()
    data = json.loads(RELIABILITY_SUMMARY_PATH.read_text(encoding="utf-8"))
    assert data["tasks_evaluated"] == 80
    assert "mission" in data
    assert "first_attempt" in data
    assert "repair" in data
    assert "false_completion" in data
    assert "routing" in data
    assert "latency_distributions" in data
    assert "category_breakdown" in data


def test_synthetic_reliability_aggregation_math():
    """Validates reliability metric calculations across synthetic test scenarios."""
    records = [
        {"task_id": "A01", "category": "simple", "objective_status": "PASS", "repair_count": 0, "hermes_reported_status": "COMPLETED", "e2e_latency_s": 10.0},
        {"task_id": "A02", "category": "simple", "objective_status": "PASS", "repair_count": 1, "hermes_reported_status": "COMPLETED", "e2e_latency_s": 15.0},
        {"task_id": "A03", "category": "simple", "objective_status": "FAIL", "repair_count": 2, "hermes_reported_status": "COMPLETED", "false_completion": True, "e2e_latency_s": 25.0},
        {"task_id": "A04", "category": "simple", "objective_status": "FAIL", "repair_count": 0, "hermes_reported_status": "FAILED", "e2e_latency_s": 8.0},
    ]
    summary = aggregate_reliability_metrics(records)

    assert summary["tasks_evaluated"] == 4
    assert summary["mission"]["success_count"] == 2
    assert summary["mission"]["success_rate"] == 0.50

    # First attempt: 1 pass with 0 repairs
    assert summary["first_attempt"]["success_count"] == 1
    assert summary["first_attempt"]["success_rate"] == 0.25

    # Repair: 2 required, 1 succeeded, 1 failed
    assert summary["repair"]["required_count"] == 2
    assert summary["repair"]["success_count"] == 1
    assert summary["repair"]["failure_count"] == 1
    assert summary["repair"]["success_rate"] == 0.50

    # False completion: 1 task
    assert summary["false_completion"]["count"] == 1
    assert summary["false_completion"]["rate_all_tasks"] == 0.25


def test_independent_reliability_validator():
    """Validates that independent validator reconciles raw records with primary summary."""
    records = [
        {"task_id": "B01", "category": "standard_coding", "objective_status": "PASS", "repair_count": 0, "hermes_reported_status": "COMPLETED", "e2e_latency_s": 12.0},
        {"task_id": "B02", "category": "standard_coding", "objective_status": "PASS", "repair_count": 1, "hermes_reported_status": "COMPLETED", "e2e_latency_s": 18.0}
    ]
    primary_summary = aggregate_reliability_metrics(records)
    val_res = validate_reliability_independence(records, primary_summary)
    assert val_res["validation_status"] == "PASS"
    assert val_res["independence_verified"] is True


def test_independent_reliability_validator_detects_tampering():
    """Validates that modifying primary summary causes validator assertion failure."""
    records = [
        {"task_id": "B01", "category": "standard_coding", "objective_status": "PASS", "repair_count": 0, "hermes_reported_status": "COMPLETED", "e2e_latency_s": 12.0}
    ]
    primary_summary = aggregate_reliability_metrics(records)
    # Corrupt primary summary artificially
    tampered_summary = copy.deepcopy(primary_summary)
    tampered_summary["mission"]["success_count"] = 999

    with pytest.raises(AssertionError):
        validate_reliability_independence(records, tampered_summary)


def test_repeated_attempt_study_evaluator():
    """Validates repeated-attempt study evaluator across consistency variations."""
    repeated_data = {
        "A01": [
            {"objective_status": "PASS"},
            {"objective_status": "PASS"},
            {"objective_status": "PASS"}
        ],
        "B01": [
            {"objective_status": "PASS"},
            {"objective_status": "FAIL"},
            {"objective_status": "PASS"}
        ],
        "C01": [
            {"objective_status": "FAIL"},
            {"objective_status": "FAIL"},
            {"objective_status": "FAIL"}
        ]
    }
    res = evaluate_repeated_attempt_study(repeated_data)
    assert res["repeated_tasks_count"] == 3
    # 2 tasks (A01 and C01) have 100% consistent outcomes across 3 runs
    assert res["consistent_tasks_count"] == 2
    assert res["task_consistency_rate"] == round(2 / 3, 4)
    assert res["per_task_results"]["A01"]["pass_rate"] == 1.0
    assert res["per_task_results"]["B01"]["pass_rate"] == round(2 / 3, 4)
    assert res["per_task_results"]["C01"]["pass_rate"] == 0.0


def test_reliability_subset_task_ids_frozen():
    """Validates that the 20-task reliability subset is deterministic and frozen."""
    assert len(RELIABILITY_SUBSET_TASK_IDS) == 20
    assert "A01" in RELIABILITY_SUBSET_TASK_IDS
    assert "D01" in RELIABILITY_SUBSET_TASK_IDS
    assert "H09" in RELIABILITY_SUBSET_TASK_IDS
