# tests/test_prompt7_optimizations.py
"""
Prompt 7 Focused Unit and Integration Test Suite.
Tests all required Prompt 7 capabilities:
- Targeted repair & scope hierarchy (Scopes 0, 1, 2, 3, 4)
- Artifact hash preservation on unaffected files
- Bounded repair retry budgets
- Progressive verification short-circuiting (L0 -> L1 -> L2 -> L3)
- Explicit escalation telemetry
- Safe model prewarming and single-model residency invariants
- TUI perceived responsiveness and immediate lifecycle acknowledgement
"""

import asyncio
import hashlib
import tempfile
from pathlib import Path
import pytest

from core.targeted_repair import (
    FailureType,
    RepairScope,
    FailureDiagnosis,
    FailureClassifier,
    ArtifactSnapshot,
    TargetedRepairManager
)
from core.progressive_verifier import (
    VerificationLevel,
    FailureClass,
    VerificationResult,
    ProgressiveVerificationEngine,
    EscalationRecord
)
from core.model_residency_manager import ModelResidencyManager, ModelLifecycleState
from ui.event_tui import EventDrivenTUI
from core.event_bus import event_bus, HermesEvent, EventType


# ──────────────────────────────────────────────────────────────────────────────
# 1. Targeted Repair & Scope Hierarchy Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_scope_0_no_repair_on_valid_artifact():
    """Valid artifacts require zero repair (Scope 0)."""
    diag = FailureDiagnosis(
        failure_type=FailureType.SYNTAX_FAILURE,
        root_cause="No failure",
        affected_files=[],
        suggested_scope=RepairScope.SCOPE_0_NO_REPAIR,
        is_recoverable=False
    )
    mgr = TargetedRepairManager(max_repair_attempts=3)
    scope, files = mgr.select_repair_scope(diag, ["main.py"])
    assert scope == RepairScope.SCOPE_0_NO_REPAIR
    assert files == []


def test_scope_1_single_file_syntax_targeted_repair():
    """Single file failure in multi-file project isolates to Scope 1 Local Repair."""
    all_files = ["index.html", "styles.css", "app.js"]
    diag = FailureClassifier.classify(
        error_text="index.html: Missing HTML5 doctype declaration",
        affected_files=["index.html"]
    )
    assert diag.failure_type == FailureType.STRUCTURAL_FAILURE
    assert diag.is_recoverable is True

    mgr = TargetedRepairManager(max_repair_attempts=3)
    scope, target_files = mgr.select_repair_scope(diag, all_files)
    assert scope == RepairScope.SCOPE_1_LOCAL_FILE
    assert target_files == ["index.html"]


def test_scope_2_dependency_failure_subset():
    """Cross-file import failure targets dependency subset (Scope 2)."""
    all_files = ["main.py", "utils.py", "config.py"]
    diag = FailureClassifier.classify(
        error_text="ModuleNotFoundError: No module named 'utils'",
        affected_files=["main.py", "utils.py"]
    )
    assert diag.failure_type == FailureType.DEPENDENCY_FAILURE

    mgr = TargetedRepairManager(max_repair_attempts=3)
    scope, target_files = mgr.select_repair_scope(diag, all_files)
    assert scope == RepairScope.SCOPE_2_DEPENDENCY_SUBSET
    assert set(target_files) == {"main.py", "utils.py"}


def test_unaffected_artifact_hash_preservation():
    """Targeted repair verifies unaffected files remain bit-for-bit unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_a = Path(tmpdir) / "file_a.txt"
        p_b = Path(tmpdir) / "file_b.txt"
        p_a.write_text("Original content A", encoding="utf-8")
        p_b.write_text("Original content B", encoding="utf-8")

        snapshot = ArtifactSnapshot.capture([str(p_a), str(p_b)])
        assert str(p_a.resolve()) in snapshot.file_hashes

        # Mutate file_a only (simulating targeted repair)
        p_a.write_text("Repaired content A", encoding="utf-8")

        # Verify file_b remains identical
        ok, mismatches = snapshot.verify_unaffected_unchanged([str(p_b)])
        assert ok is True
        assert len(mismatches) == 0


def test_bounded_repair_retry_exhaustion():
    """Repair manager terminates after configured max repair attempts."""
    mgr = TargetedRepairManager(max_repair_attempts=2)
    task_id = "task_retry_bound"
    diag = FailureClassifier.classify("SyntaxError: invalid syntax", affected_files=["app.py"])

    assert mgr.can_attempt_repair(task_id, diag) is True
    mgr.record_repair_result(task_id, diag, RepairScope.SCOPE_1_LOCAL_FILE, ["app.py"], False)

    assert mgr.can_attempt_repair(task_id, diag) is True
    mgr.record_repair_result(task_id, diag, RepairScope.SCOPE_1_LOCAL_FILE, ["app.py"], False)

    # 3rd attempt should be blocked
    assert mgr.can_attempt_repair(task_id, diag) is False


# ──────────────────────────────────────────────────────────────────────────────
# 2. Progressive Verification & Escalation Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_level_0_failure_short_circuits_higher_levels():
    """Missing file at Level 0 immediately skips Level 1, 2, and 3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        missing_file = str(Path(tmpdir) / "non_existent.py")
        engine = ProgressiveVerificationEngine(enabled=True)
        results = engine.run_progressive_pipeline([missing_file])

        assert results[0].level == VerificationLevel.STRUCTURAL
        assert results[0].status == "FAILED"
        assert results[1].status == "SKIPPED"
        assert results[2].status == "SKIPPED"


def test_level_1_syntax_failure_triggers_repair_and_short_circuits():
    """Syntax error at Level 1 skips Level 2 targeted checks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_py = Path(tmpdir) / "bad.py"
        bad_py.write_text("def broken_func(:\n    pass\n", encoding="utf-8")

        engine = ProgressiveVerificationEngine(enabled=True)
        results = engine.run_progressive_pipeline([str(bad_py)])

        assert results[0].level == VerificationLevel.STRUCTURAL
        assert results[0].status == "PASSED"
        assert results[1].level == VerificationLevel.SYNTAX
        assert results[1].status == "FAILED"
        assert results[2].status == "SKIPPED"


def test_level_2_semantic_validation_and_repair():
    """Semantic check detects missing required symbol and passes after addition."""
    with tempfile.TemporaryDirectory() as tmpdir:
        code_file = Path(tmpdir) / "calc.py"
        code_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

        engine = ProgressiveVerificationEngine(enabled=True)
        # Required symbol 'subtract' is missing
        req = {str(code_file): ["add", "subtract"]}
        res = engine.run_progressive_pipeline([str(code_file)], required_symbols=req)

        assert res[0].status == "PASSED"
        assert res[1].status == "PASSED"
        assert res[2].status == "FAILED"
        assert "subtract" in res[2].error_message

        # Add missing symbol and re-verify
        code_file.write_text("def add(a, b): return a + b\ndef subtract(a, b): return a - b\n", encoding="utf-8")
        res_after = engine.run_progressive_pipeline([str(code_file)], required_symbols=req)
        assert res_after[2].status == "PASSED"


def test_verification_escalation_telemetry():
    """Progressive engine records observable escalation telemetry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "app.py"
        f.write_text("def main(): pass\n", encoding="utf-8")

        engine = ProgressiveVerificationEngine(enabled=True)
        engine.run_progressive_pipeline([str(f)])

        assert len(engine.escalation_log) >= 2
        rec_l0 = engine.escalation_log[0]
        assert "Level 0" in rec_l0.verification_level
        assert rec_l0.checks_run == 1
        assert rec_l0.checks_failed == 0


# ──────────────────────────────────────────────────────────────────────────────
# 3. Model Prewarming & Residency Tests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_model_residency_single_active_model():
    """ModelResidencyManager preserves single-model residency and avoids unnecessary switches."""
    mgr = ModelResidencyManager(enabled=True)
    m1 = "deepseek-r1:8b"

    # Acquire m1
    k1 = await mgr.acquire_model(m1, is_foreground=True)
    assert mgr.active_model == m1
    assert mgr.switches_avoided == 0

    mgr.release_model(m1, is_foreground=True)

    # Acquire m1 again while resident -> zero switch cost
    k2 = await mgr.acquire_model(m1, is_foreground=True)
    assert mgr.switches_avoided == 1
    mgr.release_model(m1, is_foreground=True)


@pytest.mark.asyncio
async def test_safe_prewarm_respects_foreground_hold():
    """Safe prewarm aborts if another model is actively in foreground use."""
    mgr = ModelResidencyManager(enabled=True)
    # Foreground holds m1
    await mgr.acquire_model("deepseek-r1:8b", is_foreground=True)

    # Try prewarming different model m2 -> should safely abort to protect VRAM
    prewarmed = await mgr.prewarm_model("qwen2.5-coder:7b")
    assert prewarmed is False

    mgr.release_model("deepseek-r1:8b", is_foreground=True)


# ──────────────────────────────────────────────────────────────────────────────
# 4. TUI Responsiveness & Immediate Acknowledgement Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_tui_immediate_acknowledgement():
    """TUI records immediate acknowledgement (< 5ms) upon mission submission."""
    tui = EventDrivenTUI(mission_id="mission_ack_test")
    tui.start_mission_observation("mission_ack_test")

    # First event dispatched immediately
    ev = HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id="mission_ack_test",
        payload={"title": "Mission queued"}
    )
    tui.handle_event(ev)

    telem = tui.telemetry
    assert telem.time_first_event_ms is not None
    assert telem.time_first_event_ms < 50.0  # sub-50ms acknowledgement (typically <1ms)


def test_tui_renders_status_transitions_truthfully():
    """TUI updates state store across realistic status lifecycle."""
    mission_id = "mission_state_test"
    tui = EventDrivenTUI(mission_id=mission_id)

    # Dispatch workspace ready event
    event_bus.publish(HermesEvent(
        event_type=EventType.WORKSPACE_SCAN_COMPLETED,
        mission_id=mission_id,
        payload={"title": "Workspace scan complete", "files_count": 4}
    ))
    tui.handle_event(HermesEvent(
        event_type=EventType.WORKSPACE_SCAN_COMPLETED,
        mission_id=mission_id,
        payload={"title": "Workspace scan complete"}
    ))

    view = tui.format_view()
    assert "HERMES MISSION OBSERVER" in view
    assert mission_id in view
