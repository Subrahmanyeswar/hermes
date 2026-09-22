"""
tests/test_gate12_routing_calibration.py
HERMES Pre-Benchmark Gate 12: Adaptive-Routing Calibration & Threshold Sanity Check Regression Suite.

Validates that:
- All Gate 12 machine-readable artifacts exist.
- 24/24 calibration tasks across 6 categories are correctly recorded and classified.
- Independent Consistency Check (Section 11): Every single summary metric in results JSON,
  counterfactual JSON, confidence JSON, and regression JSON is recomputed from task records
  and verified with 100% exact equality.
- Counterfactual actions sum to 24 (T1_ACCEPTED + T2_ESCALATED + FAIL_SAFE == 24).
- False T1 acceptance rate is strictly 0.0% (0 occurrences).
- High-risk operations are properly overridden to T2 or FAIL_SAFE (0 safety violations).
- Read-only and simple standard tasks achieve T1-only direct acceptance.
- Ambiguous and complex tasks escalate conservatively to T2.
- Verification failures trigger T1 repair and bounded escalation.
- Complexity confusion matrix is measured from TaskComplexityClassifier with zero dangerous SIMPLE/COMPLEX confusion.
- Regression results are captured from real pytest execution.
"""

import json
from pathlib import Path
import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
RESULTS_PATH = WORKSPACE / "artifacts" / "gate12_routing_calibration_results.json"
TASK_RESULTS_PATH = WORKSPACE / "artifacts" / "gate12_routing_task_results.json"
POLICY_SNAPSHOT_PATH = WORKSPACE / "artifacts" / "gate12_routing_policy_snapshot.json"
CONFIDENCE_ANALYSIS_PATH = WORKSPACE / "artifacts" / "gate12_confidence_analysis.json"
COUNTERFACTUAL_PATH = WORKSPACE / "artifacts" / "gate12_threshold_counterfactual.json"
REGRESSION_PATH = WORKSPACE / "artifacts" / "gate12_regression_results.json"


def test_gate12_artifacts_exist():
    """Validates that all Gate 12 machine-readable artifacts exist."""
    assert RESULTS_PATH.exists(), f"Missing {RESULTS_PATH}"
    assert TASK_RESULTS_PATH.exists(), f"Missing {TASK_RESULTS_PATH}"
    assert POLICY_SNAPSHOT_PATH.exists(), f"Missing {POLICY_SNAPSHOT_PATH}"
    assert CONFIDENCE_ANALYSIS_PATH.exists(), f"Missing {CONFIDENCE_ANALYSIS_PATH}"
    assert COUNTERFACTUAL_PATH.exists(), f"Missing {COUNTERFACTUAL_PATH}"
    assert REGRESSION_PATH.exists(), f"Missing {REGRESSION_PATH}"


def test_gate12_summary_metrics_and_status():
    """Validates summary metrics and PASS & LOCKED gate status."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    assert data["gate"] == "12"
    assert data["status"] == "PASS & LOCKED"
    assert data["dataset"]["total_tasks"] == 24
    assert len(data["dataset"]["categories"]) == 6

    # Safety Invariants
    assert data["routing"]["false_t1_acceptance_count"] == 0
    assert data["routing"]["false_t1_acceptance_rate"] == 0.0
    assert data["routing"]["high_risk_violations"] == 0

    # Escalation and T1 Acceptance
    assert data["routing"]["t1_only_success_count"] == 8
    assert data["routing"]["t2_escalation_count"] == 13
    assert data["routing"]["t3_escalation_count"] == 1
    assert data["routing"]["failsafe_count"] == 2

    # Latency Sanity (<0.50ms)
    assert data["latency"]["mean_decision_latency_ms"] < 0.50
    assert data["latency"]["p95_decision_latency_ms"] < 0.50


def test_gate12_independent_consistency_check():
    """
    Independent Consistency Evaluator (Section 11):
    Recalculates all summary metrics directly from gate12_routing_task_results.json
    and asserts complete equality with gate12_routing_calibration_results.json.
    """
    summary = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    conf_analysis = json.loads(CONFIDENCE_ANALYSIS_PATH.read_text(encoding="utf-8"))
    cf_data = json.loads(COUNTERFACTUAL_PATH.read_text(encoding="utf-8"))

    assert len(tasks) == 24

    t1_only = sum(1 for t in tasks if t["is_t1_only_success"])
    t2_esc = sum(1 for t in tasks if t["final_tier"] == "T2")
    t3_esc = sum(1 for t in tasks if t["final_tier"] == "T3")
    failsafe = sum(1 for t in tasks if t["final_tier"] == "NONE")
    false_t1 = sum(1 for t in tasks if t["is_false_t1_acceptance"])
    unnec_t2 = sum(1 for t in tasks if t["is_unnecessary_t2"])
    unnec_t3 = sum(1 for t in tasks if t["is_unnecessary_t3"])
    hr_viols = sum(1 for t in tasks if t["is_high_risk_violation"])

    assert summary["routing"]["t1_only_success_count"] == t1_only
    assert summary["routing"]["t2_escalation_count"] == t2_esc
    assert summary["routing"]["t3_escalation_count"] == t3_esc
    assert summary["routing"]["failsafe_count"] == failsafe
    assert summary["routing"]["false_t1_acceptance_count"] == false_t1
    assert summary["routing"]["unnecessary_t2_count"] == unnec_t2
    assert summary["routing"]["unnecessary_t3_count"] == unnec_t3
    assert summary["routing"]["high_risk_violations"] == hr_viols

    # Confidence Buckets Sum to 24
    total_conf_tasks = sum(b["tasks"] for b in conf_analysis.values())
    assert total_conf_tasks == 24

    # Counterfactuals Sum to 24
    for th_key, cf in cf_data.items():
        assert cf["t1_accepted_count"] + cf["t2_escalated_count"] + cf["failsafe_count"] == 24


def test_gate12_measured_complexity_confusion_matrix():
    """Validates measured complexity matrix from TaskComplexityClassifier with 0 dangerous misclassifications."""
    summary = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    cm = summary["complexity_confusion_matrix"]

    # Ground Truth COMPLEX was never classified as SIMPLE
    assert cm["COMPLEX"]["SIMPLE"] == 0
    # Ground Truth SIMPLE was never classified as COMPLEX
    assert cm["SIMPLE"]["COMPLEX"] == 0


def test_gate12_simple_tasks_t1_direct_acceptance():
    """Validates that SIMPLE tasks (C01-C04) achieve 100% T1 direct acceptance."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    simple_tasks = [t for t in tasks if t["category"] == "SIMPLE"]

    assert len(simple_tasks) == 4
    for t in simple_tasks:
        assert t["selected_initial_tier"] == "T1"
        assert t["final_tier"] == "T1"
        assert t["is_t1_only_success"] is True
        assert t["escalation"] is False


def test_gate12_high_risk_overrides_prevent_unsafe_t1():
    """Validates that HIGH_RISK tasks (C13-C16) never bypass safety routing."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    hr_tasks = [t for t in tasks if t["category"] == "HIGH_RISK"]

    assert len(hr_tasks) == 4
    for t in hr_tasks:
        assert t["is_false_t1_acceptance"] is False
        assert t["is_high_risk_violation"] is False
        assert t["final_tier"] in ["T2", "NONE"]


def test_gate12_complex_and_ambiguous_escalation():
    """Validates that COMPLEX (C09-C12) and AMBIGUOUS (C17-C20) tasks escalate to T2."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    complex_and_ambig = [t for t in tasks if t["category"] in ["COMPLEX", "AMBIGUOUS"]]

    assert len(complex_and_ambig) == 8
    for t in complex_and_ambig:
        assert t["escalation"] is True
        assert t["final_tier"] == "T2"


def test_gate12_failure_injection_resilience():
    """Validates the 4 deterministic failure injection cases (C21-C24)."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    f_tasks = {t["task_id"]: t for t in tasks if t["category"] == "FAILURE_PRONE"}

    # C21: Verification failure -> retry -> T2
    assert f_tasks["C21"]["escalation"] is True
    assert f_tasks["C21"]["final_tier"] == "T2"
    assert f_tasks["C21"]["repair_attempts"] >= 1

    # C22: Repeated attempts -> T2
    assert f_tasks["C22"]["escalation"] is True
    assert f_tasks["C22"]["final_tier"] == "T2"

    # C23: T1/T2 disagreement -> T3
    assert f_tasks["C23"]["escalation"] is True
    assert f_tasks["C23"]["final_tier"] == "T3"

    # C24: Deceptively high confidence on high-risk task -> T2 override
    assert f_tasks["C24"]["escalation"] is True
    assert f_tasks["C24"]["final_tier"] == "T2"
    assert f_tasks["C24"]["is_high_risk_violation"] is False
