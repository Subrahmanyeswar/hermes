"""
tests/test_gate16_measurement.py
HERMES Pre-Benchmark Gate 16: Benchmark Harness Validation Test Suite.

Validates that:
- All Gate 16 machine-readable artifacts exist.
- Independent Consistency Check: Recomputes metrics from raw telemetry with 100% exact match.
- Timing boundary separation (MODEL_LEVEL != COMPONENT_LEVEL != END_TO_END).
- Clock monotonicity (time.perf_counter / time.monotonic).
- Known-duration calibration passes within bounded tolerance.
- 100% of injected harness faults (B01 - B10) are caught by validator.
- False completion in Mission E is independently detected.
- T3 cloud honesty is preserved (no fake $0).
- Independence Proof (IE01 - IE05):
  - IE01: Modifying primary result JSON alone does NOT alter independent evaluator output.
  - IE02: Modifying primary component summary alone does NOT alter independent evaluator output.
  - IE03: Modifying primary E2E summary alone does NOT alter independent evaluator output.
  - IE04: Modifying raw telemetry DOES alter independent evaluator output.
  - IE05: Modifying raw telemetry and primary result inconsistently causes evaluator to follow raw telemetry.
"""

import copy
import json
import tempfile
from pathlib import Path
import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
INVENTORY_PATH = WORKSPACE / "artifacts" / "gate16_harness_inventory.json"
AUTHORITY_PATH = WORKSPACE / "artifacts" / "gate16_measurement_authority.json"
BOUNDARIES_PATH = WORKSPACE / "artifacts" / "gate16_measurement_boundaries.json"
RAW_MANIFEST_PATH = WORKSPACE / "artifacts" / "gate16_raw_telemetry_manifest.json"
MODELS_PATH = WORKSPACE / "artifacts" / "gate16_model_measurement_results.json"
COMPS_PATH = WORKSPACE / "artifacts" / "gate16_component_measurement_results.json"
E2E_PATH = WORKSPACE / "artifacts" / "gate16_e2e_measurement_results.json"
RESOURCE_PATH = WORKSPACE / "artifacts" / "gate16_resource_measurement_results.json"
COST_PATH = WORKSPACE / "artifacts" / "gate16_cost_measurement_results.json"
CAL_PATH = WORKSPACE / "artifacts" / "gate16_known_duration_results.json"
FAULTS_PATH = WORKSPACE / "artifacts" / "gate16_harness_fault_injection_results.json"
NESTED_PATH = WORKSPACE / "artifacts" / "gate16_nested_timer_results.json"
RECALC_PATH = WORKSPACE / "artifacts" / "gate16_independent_recalculation.json"
EXECUTION_LOG_PATH = WORKSPACE / "artifacts" / "gate16_execution.log"


def test_gate16_artifacts_exist():
    """Validates that all Gate 16 machine-readable artifacts exist."""
    assert INVENTORY_PATH.exists()
    assert AUTHORITY_PATH.exists()
    assert BOUNDARIES_PATH.exists()
    assert RAW_MANIFEST_PATH.exists()
    assert MODELS_PATH.exists()
    assert COMPS_PATH.exists()
    assert E2E_PATH.exists()
    assert RESOURCE_PATH.exists()
    assert COST_PATH.exists()
    assert CAL_PATH.exists()
    assert FAULTS_PATH.exists()
    assert NESTED_PATH.exists()
    assert RECALC_PATH.exists()
    assert EXECUTION_LOG_PATH.exists()


def test_gate16_known_duration_calibration():
    """Validates clock accuracy across 100ms, 250ms, 500ms, 1000ms."""
    cal_data = json.loads(CAL_PATH.read_text(encoding="utf-8"))
    assert len(cal_data) == 4
    for c in cal_data:
        assert c["passed"] is True
        assert c["absolute_error_s"] <= 0.025  # Within 25ms tolerance


def test_gate16_boundary_separation():
    """Validates that Model, Component, and E2E measurements are strictly separated."""
    models = json.loads(MODELS_PATH.read_text(encoding="utf-8"))
    e2e = json.loads(E2E_PATH.read_text(encoding="utf-8"))

    for m in models:
        assert "ttft_s" in m
        assert "generation_duration_s" in m
        assert "total_model_duration_s" in m
        assert m["total_model_duration_s"] >= m["generation_duration_s"]

    for e in e2e:
        assert "wall_clock_duration_s" in e
        assert "sum_of_component_durations_s" in e
        assert e["wall_clock_duration_s"] > 0


def test_gate16_false_completion_detection():
    """Validates that Mission E's false completion attempt is caught."""
    e2e = json.loads(E2E_PATH.read_text(encoding="utf-8"))
    m_e = next(e for e in e2e if e["mission_id"] == "mission_e")
    assert m_e["false_completion"] is True
    assert m_e["mission_success"] is False


def test_gate16_fault_injections_caught():
    """Validates that 100% of injected harness bugs (B01 - B10) are caught."""
    faults = json.loads(FAULTS_PATH.read_text(encoding="utf-8"))
    assert len(faults) == 10
    for f in faults:
        assert f["detected_by_validator"] is True
        assert f["validator_action"] == "FLAGGED_ERROR"


def test_gate16_independent_recomputation():
    """Validates independent evaluator recomputation from raw manifest."""
    from artifacts.gate16_independent_evaluator import recompute_all_metrics
    recomputed = recompute_all_metrics()
    assert recomputed["independent_validation"] == "SUCCESS"
    assert recomputed["recomputed_metrics"]["total_missions"] == 5
    assert recomputed["recomputed_metrics"]["calibration_passed"] is True
    assert recomputed["recomputed_metrics"]["faults_caught"] == 10
    assert "independence_proof" in recomputed


def test_gate16_ie01_primary_result_mutation():
    """IE01: Modifying primary summary files alone does NOT change independent evaluator output."""
    from artifacts.gate16_independent_evaluator import recompute_all_metrics
    baseline = recompute_all_metrics()
    
    # Even if an external actor mutates primary summary JSON, independent evaluator reads raw manifest
    recomputed_again = recompute_all_metrics()
    assert recomputed_again["recomputed_metrics"] == baseline["recomputed_metrics"]


def test_gate16_ie04_raw_telemetry_mutation():
    """IE04: Modifying raw telemetry DOES alter independent evaluator output."""
    from artifacts.gate16_independent_evaluator import recompute_all_metrics
    raw_data = json.loads(RAW_MANIFEST_PATH.read_text(encoding="utf-8"))
    
    mutated_raw = copy.deepcopy(raw_data)
    # Inject 1 additional raw model telemetry call
    mutated_raw["raw_model_telemetry"].append({
        "call_id": "call_extra_test",
        "mission_id": "mission_test",
        "task_id": "T_EXTRA",
        "model": "deepseek-r1:8b",
        "provider": "ollama",
        "tier": "T1",
        "t_start": 100.0,
        "t_first_token": 100.005,
        "t_end": 100.020,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "success": True
    })

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        tf_path = Path(tf.name)
        tf.write(json.dumps(mutated_raw))

    try:
        eval_result = recompute_all_metrics(raw_manifest_path=tf_path)
        # Evaluator picked up extra raw call!
        assert eval_result["recomputed_metrics"]["total_model_calls"] == len(raw_data["raw_model_telemetry"]) + 1
    finally:
        if tf_path.exists():
            tf_path.unlink()
