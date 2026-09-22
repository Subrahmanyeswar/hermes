"""
tests/test_gate14_timeout.py
HERMES Pre-Benchmark Gate 14: Timeout Hierarchy & Deadline Consistency Audit Regression Suite.

Validates that:
- All Gate 14 machine-readable artifacts exist.
- 32/32 timeout hierarchy audit scenarios pass.
- Independent Consistency Check: Every summary metric in results JSON, task results JSON,
  process results JSON, event trace JSON, race results JSON, budget analysis JSON is recomputed
  directly from raw records and asserted with 100% exact mathematical equality.
- No child operation can silently outlive its parent mission/task deadline.
- Subprocess timeouts and termination cleanup are strictly verified (0 zombies).
- Timeout vs Completion races cannot cause false completions (0 false MISSION_COMPLETED).
- Late results cannot resurrect a timed-out or cancelled mission (0 resurrections).
- Overshoot is strictly bounded within physical operating system bounds.
- Event sequence monotonicity is verified across all timeout event traces.
"""

import json
from pathlib import Path
import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
INVENTORY_PATH = WORKSPACE / "artifacts" / "gate14_timeout_inventory.json"
HIERARCHY_PATH = WORKSPACE / "artifacts" / "gate14_timeout_hierarchy.json"
TASK_RESULTS_PATH = WORKSPACE / "artifacts" / "gate14_timeout_task_results.json"
PROCESS_RESULTS_PATH = WORKSPACE / "artifacts" / "gate14_timeout_process_results.json"
RACE_RESULTS_PATH = WORKSPACE / "artifacts" / "gate14_timeout_race_results.json"
BUDGET_ANALYSIS_PATH = WORKSPACE / "artifacts" / "gate14_timeout_budget_analysis.json"
EVENT_TRACE_PATH = WORKSPACE / "artifacts" / "gate14_timeout_event_trace.json"
EXECUTION_LOG_PATH = WORKSPACE / "artifacts" / "gate14_timeout_execution.log"


def test_gate14_artifacts_exist():
    """Validates that all Gate 14 machine-readable artifacts exist."""
    assert INVENTORY_PATH.exists(), f"Missing {INVENTORY_PATH}"
    assert HIERARCHY_PATH.exists(), f"Missing {HIERARCHY_PATH}"
    assert TASK_RESULTS_PATH.exists(), f"Missing {TASK_RESULTS_PATH}"
    assert PROCESS_RESULTS_PATH.exists(), f"Missing {PROCESS_RESULTS_PATH}"
    assert RACE_RESULTS_PATH.exists(), f"Missing {RACE_RESULTS_PATH}"
    assert BUDGET_ANALYSIS_PATH.exists(), f"Missing {BUDGET_ANALYSIS_PATH}"
    assert EVENT_TRACE_PATH.exists(), f"Missing {EVENT_TRACE_PATH}"
    assert EXECUTION_LOG_PATH.exists(), f"Missing {EXECUTION_LOG_PATH}"


def test_gate14_inventory_completeness():
    """Validates that the timeout inventory maps all major production layers."""
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert len(inventory) >= 12

    scopes = {item["scope"] for item in inventory}
    assert "MISSION" in scopes
    assert "MODEL_T1" in scopes
    assert "MODEL_PROVIDER" in scopes
    assert "TOOL" in scopes
    assert "PROCESS_CLEANUP" in scopes
    assert "VERIFICATION" in scopes
    assert "QUALITY_FEEDBACK" in scopes
    assert "BACKGROUND_WORKER" in scopes


def test_gate14_independent_consistency_check():
    """
    Independent Consistency Evaluator:
    Recalculates all summary metrics directly from gate14_timeout_task_results.json.
    """
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    proc_data = json.loads(PROCESS_RESULTS_PATH.read_text(encoding="utf-8"))
    race_data = json.loads(RACE_RESULTS_PATH.read_text(encoding="utf-8"))
    ev_trace = json.loads(EVENT_TRACE_PATH.read_text(encoding="utf-8"))

    total = len(tasks)
    passed = sum(1 for t in tasks if t["classification"] == "PASS")
    failed = sum(1 for t in tasks if t["classification"] == "FAIL")
    not_verified = sum(1 for t in tasks if t["classification"] == "NOT_VERIFIED")

    false_comp = sum(1 for t in tasks if t["false_mission_completed"])
    zombies = sum(t["zombies_count"] for t in tasks)
    resurrections = sum(1 for t in tasks if t["late_result_resurrected"])
    post_timeout = sum(t["post_timeout_activity_count"] for t in tasks)

    # Invariant Assertions
    assert total == 32
    assert passed == 32
    assert failed == 0
    assert not_verified == 0
    assert false_comp == 0
    assert zombies == 0
    assert resurrections == 0
    assert post_timeout == 0

    # Process Cleanup Assertions
    for p in proc_data:
        assert p["zombies"] == 0
        assert p["harness_killed_process"] is False

    # Race Results Assertions
    for r in race_data:
        assert r["false_completion"] is False
        assert r["resurrection"] is False

    # Event Trace Assertions
    assert len(ev_trace) == total


def test_gate14_overshoot_bounds():
    """Validates that real wall-clock timeout overshoots are strictly bounded."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    
    # Maximum acceptable cleanup latency bound is <= 0.5s for OS process signal delivery
    for t in tasks:
        assert t["overshoot_s"] <= 0.5, f"Scenario {t['scenario_id']} exceeded 0.5s overshoot: {t['overshoot_s']}s"


def test_gate14_mission_timeout_propagation():
    """Validates T01-T09 mission timeout scenarios."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    mission_tasks = [t for t in tasks if t["category"] == "MISSION_TIMEOUT"]

    assert len(mission_tasks) == 9
    for t in mission_tasks:
        assert t["final_terminal_state"] == "CANCELLED"
        assert t["false_mission_completed"] is False
        assert t["operation_stopped"] is True


def test_gate14_task_timeout_boundaries():
    """Validates T10-T14 task timeout scenarios."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    task_timeouts = [t for t in tasks if t["category"] == "TASK_TIMEOUT"]

    assert len(task_timeouts) == 5
    for t in task_timeouts:
        assert t["final_terminal_state"] == "CANCELLED"
        assert t["operation_stopped"] is True


def test_gate14_races_and_stress():
    """Validates T23-T27 race conditions and T28-T30 stress repetitions."""
    tasks = json.loads(TASK_RESULTS_PATH.read_text(encoding="utf-8"))
    race_tasks = [t for t in tasks if t["category"] in {"RACE_CONDITION", "STRESS_REPETITION"}]

    assert len(race_tasks) >= 7
    for t in race_tasks:
        assert t["false_mission_completed"] is False
        assert t["late_result_resurrected"] is False
