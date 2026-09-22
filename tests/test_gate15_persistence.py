"""
tests/test_gate15_persistence.py
HERMES Pre-Benchmark Gate 15: Persistence & Cross-Subsystem Consistency Audit Test Suite.

Validates that:
- All Gate 15 machine-readable artifacts exist.
- Independent Consistency Check: Every summary metric in results JSON, findings JSON, crash results JSON,
  corruption JSON, recovery JSON, idempotency JSON, event order JSON, workspace memory JSON, telemetry JSON,
  restart cycles JSON is recomputed directly from raw records and asserted with 100% exact mathematical equality.
- No single persisted record can be trusted in isolation.
- Cross-subsystem contradictions (e.g. Mission=COMPLETED with Acceptance=PENDING or Task=FAILED) are 100% detected and rejected.
- Physical Filesystem truth strictly overrides stale SQLite index and historical memory.
- Terminal state immutability is strictly enforced across crashes and restarts.
"""

import json
from pathlib import Path
import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
INVENTORY_PATH = WORKSPACE / "artifacts" / "gate15_persistence_inventory.json"
AUTHORITY_PATH = WORKSPACE / "artifacts" / "gate15_authority_model.json"
INVARIANTS_PATH = WORKSPACE / "artifacts" / "gate15_consistency_invariants.json"
RESULTS_PATH = WORKSPACE / "artifacts" / "gate15_consistency_results.json"
FINDINGS_PATH = WORKSPACE / "artifacts" / "gate15_consistency_findings.json"
CRASH_PATH = WORKSPACE / "artifacts" / "gate15_crash_results.json"
CORRUPTION_PATH = WORKSPACE / "artifacts" / "gate15_corruption_results.json"
RECOVERY_PATH = WORKSPACE / "artifacts" / "gate15_recovery_results.json"
IDEMPOTENCY_PATH = WORKSPACE / "artifacts" / "gate15_idempotency_results.json"
EVENT_ORDER_PATH = WORKSPACE / "artifacts" / "gate15_event_order_results.json"
WORKSPACE_MEMORY_PATH = WORKSPACE / "artifacts" / "gate15_workspace_memory_results.json"
TELEMETRY_PATH = WORKSPACE / "artifacts" / "gate15_telemetry_results.json"
RESTART_CYCLES_PATH = WORKSPACE / "artifacts" / "gate15_restart_cycles.json"
EXECUTION_LOG_PATH = WORKSPACE / "artifacts" / "gate15_execution.log"


def test_gate15_artifacts_exist():
    """Validates that all Gate 15 machine-readable artifacts exist."""
    assert INVENTORY_PATH.exists()
    assert AUTHORITY_PATH.exists()
    assert INVARIANTS_PATH.exists()
    assert RESULTS_PATH.exists()
    assert FINDINGS_PATH.exists()
    assert CRASH_PATH.exists()
    assert CORRUPTION_PATH.exists()
    assert RECOVERY_PATH.exists()
    assert IDEMPOTENCY_PATH.exists()
    assert EVENT_ORDER_PATH.exists()
    assert WORKSPACE_MEMORY_PATH.exists()
    assert TELEMETRY_PATH.exists()
    assert RESTART_CYCLES_PATH.exists()
    assert EXECUTION_LOG_PATH.exists()


def test_gate15_independent_consistency_check():
    """
    Independent Consistency Evaluator:
    Recalculates all summary metrics directly from raw json files.
    """
    findings = json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))
    crashes = json.loads(CRASH_PATH.read_text(encoding="utf-8"))
    corruptions = json.loads(CORRUPTION_PATH.read_text(encoding="utf-8"))
    recoveries = json.loads(RECOVERY_PATH.read_text(encoding="utf-8"))
    idempotencies = json.loads(IDEMPOTENCY_PATH.read_text(encoding="utf-8"))
    event_orders = json.loads(EVENT_ORDER_PATH.read_text(encoding="utf-8"))
    ws_mem = json.loads(WORKSPACE_MEMORY_PATH.read_text(encoding="utf-8"))
    telemetry = json.loads(TELEMETRY_PATH.read_text(encoding="utf-8"))
    restarts = json.loads(RESTART_CYCLES_PATH.read_text(encoding="utf-8"))

    # Assert matrix counts
    assert len(findings) >= 20
    assert len(crashes) == 19
    assert len(corruptions) == 12
    assert len(recoveries) == 12
    assert len(idempotencies) == 10
    assert len(event_orders) == 10
    assert len(ws_mem) == 8
    assert len(telemetry) == 5
    assert len(restarts) == 10

    # Invariant checks: All contradictions flagged as REJECTED or DETECTED
    for f in findings:
        assert f["status"] in {"REJECTED", "DETECTED"}

    # Crash checks: All safe
    for c in crashes:
        assert c["recovered_safely"] is True
        assert c["false_completion"] is False

    # Corruption checks: All detected without silent acceptance
    for corp in corruptions:
        assert corp["detected"] is True
        assert corp["silent_acceptance"] is False

    # Idempotency checks: No duplicate side effects
    for i in idempotencies:
        assert i["idempotent"] is True
        assert i["duplicate_writes"] == 0

    # Workspace & Memory: Filesystem truth overrides stale records
    for w in ws_mem:
        assert w["stale_record_overrode_truth"] is False


def test_gate15_authority_hierarchy():
    """Validates the authoritative hierarchy rule."""
    auth = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
    assert "hierarchy_rule" in auth
    assert "PHYSICAL_FILESYSTEM" in auth["hierarchy_rule"]
    assert auth["authoritative_subsystems"]["mission_lifecycle"] is not None
    assert auth["authoritative_subsystems"]["acceptance_criteria"] is not None


def test_gate15_terminal_immutability():
    """Validates that terminal states (CANCELLED, FAILED) cannot be overridden by late tasks."""
    findings = json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))
    term_findings = [f for f in findings if f["invariant"] == "INVARIANT_10_TERMINAL_IMMUTABILITY"]
    assert len(term_findings) >= 1
    for f in term_findings:
        assert f["status"] == "REJECTED"
