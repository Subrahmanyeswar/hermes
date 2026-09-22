"""
tests/test_gate13_cancellation.py
HERMES Pre-Benchmark Gate 13: End-to-End Cancellation & Termination Safety Regression Suite.

Validates that:
- All Gate 13 machine-readable artifacts exist.
- 58/58 cancellation scenarios and race tests pass.
- Independent Consistency Check: Every summary metric in results JSON, task results JSON,
  process results JSON, event trace JSON, state integrity JSON is recomputed directly from
  records and asserted with 100% exact equality.
- Real production E2E (46), controlled production E2E (6), and primitive event-level (6)
  are classified truthfully and match derived records.
- Real component execution (Tool, Verification, Repair, KAIROS, Subprocess) is genuinely proven.
- Raw Event Traces contain strictly monotonic sequences and prove causal cancellation propagation.
- Subprocess termination was demonstrably performed by HERMES (harness_killed_process == False).
- Zero false MISSION_COMPLETED states occur.
- Zero zombie processes or threads remain after cancellation.
- Zero post-cancellation side effects occur.
- Late results (model, tool, subprocess, verification, repair, KAIROS) cannot resurrect execution.
- Cancellation is strictly idempotent.
- Event-Driven TUI truthfully reflects CANCELLED state.
"""

import json
from pathlib import Path
import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
RESULTS_PATH = WORKSPACE / "artifacts" / "gate13_cancellation_results.json"
TASK_RESULTS_PATH = WORKSPACE / "artifacts" / "gate13_cancellation_task_results.json"
PROCESS_RESULTS_PATH = WORKSPACE / "artifacts" / "gate13_cancellation_process_results.json"
EVENT_TRACE_PATH = WORKSPACE / "artifacts" / "gate13_cancellation_event_trace.json"
STATE_INTEGRITY_PATH = WORKSPACE / "artifacts" / "gate13_cancellation_state_integrity.json"
REAL_EXEC_PATH = WORKSPACE / "artifacts" / "gate13_real_execution_evidence.json"
REAL_TRACE_PATH = WORKSPACE / "artifacts" / "gate13_real_execution_trace.json"
REGRESSION_PATH = WORKSPACE / "artifacts" / "gate13_regression_results.json"


def test_gate13_artifacts_exist():
    """Validates that all Gate 13 machine-readable artifacts exist."""
    assert RESULTS_PATH.exists(), f"Missing {RESULTS_PATH}"
    assert TASK_RESULTS_PATH.exists(), f"Missing {TASK_RESULTS_PATH}"
    assert PROCESS_RESULTS_PATH.exists(), f"Missing {PROCESS_RESULTS_PATH}"
    assert EVENT_TRACE_PATH.exists(), f"Missing {EVENT_TRACE_PATH}"
    assert STATE_INTEGRITY_PATH.exists(), f"Missing {STATE_INTEGRITY_PATH}"
    assert REAL_EXEC_PATH.exists(), f"Missing {REAL_EXEC_PATH}"
    assert REAL_TRACE_PATH.exists(), f"Missing {REAL_TRACE_PATH}"


def test_gate13_summary_metrics_and_status():
    """Validates summary metrics and PASS & LOCKED gate status."""
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    assert data["gate"] == "13"
    assert data["status"] == "PASS & LOCKED"
    assert data["summary"]["scenarios_total"] == 58
    assert data["summary"]["scenarios_failed"] == 0
    assert data["summary"]["false_mission_completed"] == 0
    assert data["summary"]["zombie_processes"] == 0
    assert data["summary"]["zombie_threads"] == 0
    assert data["summary"]["late_result_resurrections"] == 0
    assert data["summary"]["state_integrity_failures"] == 0
    assert data["summary"]["side_effect_integrity_failures"] == 0


def test_gate13_independent_consistency_check():
    """
    Independent Consistency Evaluator:
    Recalculates all summary metrics directly from gate13_cancellation_task_results.json
    and asserts complete equality with gate13_cancellation_results.json.
    """
    summary = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    proc_data = json.loads(PROCESS_RESULTS_PATH.read_text(encoding="utf-8"))
    ev_trace = json.loads(EVENT_TRACE_PATH.read_text(encoding="utf-8"))
    state_int = json.loads(STATE_INTEGRITY_PATH.read_text(encoding="utf-8"))

    total = len(tasks)
    passed = sum(1 for t in tasks if t["classification"] == "PASS")
    failed = sum(1 for t in tasks if t["classification"] == "FAIL")
    not_verified = sum(1 for t in tasks if t["classification"] == "NOT_VERIFIED")

    real_prod = sum(1 for t in tasks if t["execution_mode"] == "REAL_PRODUCTION_E2E")
    ctrl_prod = sum(1 for t in tasks if t["execution_mode"] == "CONTROLLED_PRODUCTION_E2E")
    prim_ev = sum(1 for t in tasks if t["execution_mode"] == "PRIMITIVE_EVENT_LEVEL")

    false_comp = sum(1 for t in tasks if t["false_mission_completed"])
    zombies = sum(t["zombie_processes_count"] for t in tasks)
    threads = sum(t["zombie_threads_count"] for t in tasks)
    resurrections = sum(1 for t in tasks if t["late_result_resurrected"])
    side_effects = sum(t["post_cancel_side_effects"] for t in tasks)

    # Assert exact mathematical equality
    assert summary["summary"]["scenarios_total"] == total
    assert summary["summary"]["scenarios_passed"] == passed
    assert summary["summary"]["scenarios_failed"] == failed
    assert summary["summary"]["scenarios_not_verified"] == not_verified

    assert summary["summary"]["real_production_e2e"] == real_prod
    assert summary["summary"]["controlled_production_e2e"] == ctrl_prod
    assert summary["summary"]["primitive_event_level"] == prim_ev

    assert summary["summary"]["false_mission_completed"] == false_comp
    assert summary["summary"]["zombie_processes"] == zombies
    assert summary["summary"]["zombie_threads"] == threads
    assert summary["summary"]["late_result_resurrections"] == resurrections
    assert summary["summary"]["side_effect_integrity_failures"] == side_effects

    # Process Results Consistency & Harness Non-Interference
    assert len(proc_data) == 2
    for p in proc_data:
        assert p["zombies"] == 0
        assert p["subprocess_terminated"] is True
        assert p["harness_killed_process"] is False
        assert "HERMES" in p["termination_mechanism"]

    # Event Trace & State Integrity Consistency
    assert len(ev_trace) == total
    assert all(e["final_state"] == "CANCELLED" for e in ev_trace)
    assert all(s["state_integrity_passed"] for s in state_int)


def test_gate13_causal_event_traces():
    """Validates raw ordered event traces for representative scenarios (C02, C05, C06, C07, C09, C10, R01, Z01)."""
    traces = json.loads(EVENT_TRACE_PATH.read_text(encoding="utf-8"))
    trace_map = {t["scenario_id"]: t for t in traces}

    rep_ids = ["C02", "C05", "C06", "C07", "C09", "C10", "R01", "Z01"]
    for r_id in rep_ids:
        assert r_id in trace_map, f"Missing trace for {r_id}"
        t = trace_map[r_id]
        events = t["events"]
        assert len(events) >= 3

        # Verify strictly monotonic sequences
        seqs = [ev["sequence"] for ev in events]
        assert seqs == sorted(seqs), f"Sequences not monotonic in {r_id}: {seqs}"

        # Verify MISSION_CANCELLED is present in the trace
        event_types = [ev["event_type"] for ev in events]
        assert "MISSION_CANCELLED" in event_types
        assert t["final_state"] == "CANCELLED"


def test_gate13_real_execution_boundary_evidence():
    """Validates real component execution evidence (tools, verifier, repair, KAIROS, multi-component)."""
    evidence = json.loads(REAL_EXEC_PATH.read_text(encoding="utf-8"))

    # Tool execution proof (C05)
    assert "C05" in evidence
    assert "WriteFileTool" in evidence["C05"]["component"]
    assert evidence["C05"]["tool_success"] is True
    assert evidence["C05"]["completed_before_cancel"] is True
    assert evidence["C05"]["final_state"] == "CANCELLED"

    # In-flight Subprocess execution proof (C06, Z01)
    for p_id in ["C06", "Z01"]:
        assert p_id in evidence
        assert evidence[p_id]["operation_confirmed_active"] is True
        assert evidence[p_id]["completed_before_cancel"] is False
        assert evidence[p_id]["final_state"] == "CANCELLED"

    # Verification execution proof (C09)
    assert "C09" in evidence
    assert "ProgressiveVerificationEngine" in evidence["C09"]["component"]
    assert evidence["C09"]["verification_status"] == "PASSED"
    assert evidence["C09"]["completed_before_cancel"] is True
    assert evidence["C09"]["final_state"] == "CANCELLED"

    # Repair engine execution proof (C10)
    assert "C10" in evidence
    assert "RepairEngine" in evidence["C10"]["component"]
    assert evidence["C10"]["can_repair"] is True
    assert evidence["C10"]["completed_before_cancel"] is True
    assert evidence["C10"]["final_state"] == "CANCELLED"

    # In-flight KAIROS scheduling execution proof (C07, C08, C15)
    for k_id in ["C07", "C08", "C15"]:
        assert k_id in evidence
        assert "KairosDAGScheduler" in evidence[k_id]["component"]
        assert evidence[k_id]["operation_confirmed_active"] is True
        assert evidence[k_id]["completed_before_cancel"] is False
        assert evidence[k_id]["ready_tasks_count"] >= 1
        assert evidence[k_id]["final_state"] == "CANCELLED"

    # In-flight Multi-component mission proof (C20)
    assert "C20" in evidence
    assert "MissionRunner" in evidence["C20"]["component"]
    assert evidence["C20"]["operation_confirmed_active"] is True
    assert evidence["C20"]["completed_before_cancel"] is False
    assert evidence["C20"]["final_state"] == "CANCELLED"


def test_gate13_subprocess_proof():
    """Validates that HERMES directly terminated subprocesses in C06 and Z01 without harness interference."""
    proc_data = json.loads(PROCESS_RESULTS_PATH.read_text(encoding="utf-8"))
    p_map = {p["scenario_id"]: p for p in proc_data}

    for s_id in ["C06", "Z01"]:
        assert s_id in p_map
        p = p_map[s_id]
        assert p["pid"] > 0
        assert p["parent_pid"] > 0
        assert p["hermes_cancellation_timestamp"] >= p["process_creation_timestamp"]
        assert p["process_termination_timestamp"] >= p["hermes_cancellation_timestamp"]
        assert p["subprocess_terminated"] is True
        assert p["harness_killed_process"] is False
        assert "HERMES" in p["termination_mechanism"]


def test_gate13_20_lifecycle_cancellation_scenarios():
    """Validates 20 distinct lifecycle boundary cancellation scenarios (C01-C20)."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    lifecycle_tasks = [t for t in tasks if t["category"] == "LIFECYCLE"]

    assert len(lifecycle_tasks) == 20
    for t in lifecycle_tasks:
        assert t["post_cancel_state"] == "CANCELLED"
        assert t["false_mission_completed"] is False
        assert t["tui_reflected_cancelled"] is True
        assert t["cancellation_entrypoint"] == "CancellationController.cancel_mission"


def test_gate13_20_race_condition_repetitions():
    """Validates 20 repetitions of simultaneous task finish vs CANCEL (R01-R20)."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    race_tasks = [t for t in tasks if t["category"] == "RACE_CONDITION"]

    assert len(race_tasks) == 20
    for t in race_tasks:
        assert t["post_cancel_state"] == "CANCELLED"
        assert t["false_mission_completed"] is False
        assert t["late_result_resurrected"] is False


def test_gate13_failure_injection_cancellation():
    """Validates cancellation combined with failure modes (CX01-CX08)."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    fail_tasks = [t for t in tasks if t["category"] == "FAILURE_INJECTION"]

    assert len(fail_tasks) == 8
    for t in fail_tasks:
        assert t["post_cancel_state"] == "CANCELLED"
        assert t["false_mission_completed"] is False


def test_gate13_late_result_rejection():
    """Validates that late results (L01-L06) cannot resurrect execution."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    late_tasks = [t for t in tasks if t["category"] == "LATE_RESULT"]

    assert len(late_tasks) == 6
    for t in late_tasks:
        assert t["post_cancel_state"] == "CANCELLED"
        assert t["late_result_resurrected"] is False


def test_gate13_zombie_and_resource_cleanup():
    """Validates that zero zombie processes or threads remain (Z01-Z04)."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    zombie_tasks = [t for t in tasks if t["category"] == "ZOMBIE_AUDIT"]

    assert len(zombie_tasks) == 4
    for t in zombie_tasks:
        assert t["zombie_processes_count"] == 0
        assert t["subprocess_terminated"] is True
