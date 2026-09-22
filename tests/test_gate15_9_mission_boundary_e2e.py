"""
Pre-Benchmark Gate 15.9 Final Correction: Mission-Boundary E2E Regression Suite.
Validates that raw malformed model outputs entering at the real model-client boundary
(OllamaClient.generate) are safely processed, repaired, and executed through the
real Orchestrator and MissionRunner pipelines.
"""

import json
import pytest
from pathlib import Path

from benchmarks.security_validation.mission_boundary_harness import MissionBoundaryE2EHarness

WORKSPACE = Path(__file__).resolve().parent.parent
RESULTS_PATH = WORKSPACE / "artifacts" / "gate_15_9_mission_boundary_results.json"


def test_gate15_9_mission_boundary_results_file_and_metrics():
    """Validates that Gate 15.9 mission boundary results file exists with 8/8 PASS."""
    assert RESULTS_PATH.exists(), f"Missing {RESULTS_PATH}"
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    
    assert data["gate"] == "15.9"
    assert data["correction"] == "MISSION_BOUNDARY_E2E_FINAL_SURGICAL"
    assert data["status"] == "PASS & LOCKED"
    assert data["total_tests"] == 8
    assert data["passed"] == 8
    assert data["failed"] == 0
    assert data["existing_stress_suite"]["total"] == 90
    assert data["existing_stress_suite"]["passed"] == 90
    assert data["existing_stress_suite"]["failed"] == 0
    assert data["mission_boundary"]["total"] == 8
    assert data["mission_boundary"]["passed"] == 8
    assert data["uncaught_exceptions"] == 0
    assert data["infinite_retry_loops"] == 0
    assert data["false_completions"] == 0
    assert data["unauthorized_executions"] == 0
    assert data["duplicate_destructive_side_effects"] == 0
    assert data["sentinel_intact"] is True


@pytest.mark.asyncio
async def test_empty_model_output_survives_real_mission_boundary():
    """E1: Empty object {} recovers on attempt 2 to create file."""
    harness = MissionBoundaryE2EHarness()
    try:
        rec = await harness.run_e1_empty_object()
        assert rec["result"] == "PASS"
        assert rec["orchestrator_success"] is True
        assert rec["file_verified"] is True
        assert rec["sentinel_intact"] is True
    finally:
        harness.cleanup()


@pytest.mark.asyncio
async def test_empty_path_normalization_recovery():
    """E2: Empty path is normalized deterministically and executes successfully on attempt 1."""
    harness = MissionBoundaryE2EHarness()
    try:
        rec = await harness.run_e2_empty_path()
        assert rec["result"] == "PASS"
        assert rec["orchestrator_success"] is True
        assert rec["normalization_observed"] is True
        assert rec["model_call_count"] == 1
        assert rec["file_verified"] is True
        assert rec["sentinel_intact"] is True
    finally:
        harness.cleanup()


@pytest.mark.asyncio
async def test_wrong_type_survives_real_mission_boundary():
    """E3: Integer path / list content recovers on attempt 2 to create file."""
    harness = MissionBoundaryE2EHarness()
    try:
        rec = await harness.run_e3_wrong_type()
        assert rec["result"] == "PASS"
        assert rec["orchestrator_success"] is True
        assert rec["file_verified"] is True
        assert rec["sentinel_intact"] is True
    finally:
        harness.cleanup()


@pytest.mark.asyncio
async def test_malformed_json_survives_real_mission_boundary():
    """E4: Truncated JSON recovers on attempt 2 to create file."""
    harness = MissionBoundaryE2EHarness()
    try:
        rec = await harness.run_e4_malformed_json()
        assert rec["result"] == "PASS"
        assert rec["orchestrator_success"] is True
        assert rec["file_verified"] is True
        assert rec["sentinel_intact"] is True
    finally:
        harness.cleanup()


@pytest.mark.asyncio
async def test_repeated_malformed_output_is_bounded():
    """E5: Repeated malformed output terminates boundedly without crash or false completion."""
    harness = MissionBoundaryE2EHarness()
    try:
        rec = await harness.run_e5_bounded_failure()
        assert rec["result"] == "PASS"
        assert rec["orchestrator_success"] is False
        assert rec["uncaught_exception"] is False
        assert rec["model_call_count"] <= 3
        assert rec["sentinel_intact"] is True
    finally:
        harness.cleanup()


@pytest.mark.asyncio
async def test_malicious_repair_is_rejected_by_real_pipeline():
    """E6: Malicious repair outputting ../../outside path is rejected by security in real pipeline."""
    harness = MissionBoundaryE2EHarness()
    try:
        rec = await harness.run_e6_malicious_repair_security()
        assert rec["result"] == "PASS"
        assert rec["orchestrator_success"] is False
        assert rec["security_denied"] is True
        assert rec["sentinel_intact"] is True
    finally:
        harness.cleanup()


@pytest.mark.asyncio
async def test_false_completion_is_rejected():
    """E7: Model saying 'Done' in plain text without tool call is rejected by orchestrator."""
    harness = MissionBoundaryE2EHarness()
    try:
        rec = await harness.run_e7_false_completion_rejected()
        assert rec["result"] == "PASS"
        assert rec["orchestrator_success"] is False
        assert rec["false_completion"] is False
        assert rec["sentinel_intact"] is True
    finally:
        harness.cleanup()


@pytest.mark.asyncio
async def test_multistep_mission_recovers_and_completes():
    """E8: True single-mission multi-step recovery through MissionRunner."""
    harness = MissionBoundaryE2EHarness()
    try:
        rec = await harness.run_e8_multistep_mission_recovery()
        assert rec["result"] == "PASS"
        assert rec["mission_id"] == "m_gate15_9_e8_single"
        assert rec["steps_completed"] == 3
        assert rec["steps_total"] == 3
        assert rec["mission_is_complete"] is True
        assert rec["task_states"]["t1_read"] == "COMPLETED"
        assert rec["task_states"]["t2_fix"] == "COMPLETED"
        assert rec["task_states"]["t3_verify"] == "COMPLETED"
        assert rec["pytest_passed"] is True
        assert rec["sentinel_intact"] is True
    finally:
        harness.cleanup()
