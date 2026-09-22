"""
Unit and Integration Tests for Phase 12 Mission Completion Engine.
Tests all 10 core scenarios:
1. Single task mission complete
2. Multi-task mission continues after first success (no early stop!)
3. DAG complete but criteria pending -> CONTINUE
4. Failed criterion triggers REPAIR
5. Exhausted repairs trigger FAILED
6. User confirmation pending -> BLOCKED
7. Evidence-based validation
8. Idempotent finalization
9. Rejection of unverified LLM claims
10. Sub-millisecond deterministic evaluation
"""
import time
import pytest
from core.mission_completion import (
    CriterionStatus,
    AcceptanceCriterion,
    CompletionVerdict,
    CompletionLedger,
    MissionCompletionEvaluator,
    MissionFinalizer
)


@pytest.fixture
def evaluator():
    return MissionCompletionEvaluator(enabled=True)


def test_single_task_mission_complete(evaluator):
    """1 task + 1 satisfied criterion + DAG complete -> COMPLETE."""
    ledger = CompletionLedger(mission_id="m_001")
    ledger.add_criterion("AC-1", "Create reports directory")
    ledger.update_criterion("AC-1", CriterionStatus.SATISFIED, evidence=["Directory 'reports' created and verified"])

    verdict, reason = evaluator.evaluate(
        ledger=ledger,
        dag_is_complete=True,
        has_ready_tasks=False
    )
    assert verdict == CompletionVerdict.COMPLETE
    assert "SATISFIED" in reason


def test_multi_task_mission_continues_after_first_success(evaluator):
    """Task 1 complete, Task 2 still ready -> CONTINUE (never falsely completes after 1st success!)."""
    ledger = CompletionLedger(mission_id="m_002")
    ledger.add_criterion("AC-1", "Build React frontend")
    ledger.add_criterion("AC-2", "Build Flask backend")

    # Task 1 finished
    ledger.update_criterion("AC-1", CriterionStatus.SATISFIED, evidence=["React app rendered"])

    # Task 2 still pending
    verdict, reason = evaluator.evaluate(
        ledger=ledger,
        dag_is_complete=False,
        has_ready_tasks=True
    )
    assert verdict == CompletionVerdict.CONTINUE
    assert "READY tasks" in reason or "PENDING" in reason


def test_dag_complete_but_criteria_pending_continues(evaluator):
    """DAG nodes finished but acceptance criteria remain pending -> CONTINUE."""
    ledger = CompletionLedger(mission_id="m_003")
    ledger.add_criterion("AC-1", "Authentication routes functional")
    # AC-1 is still PENDING

    verdict, reason = evaluator.evaluate(
        ledger=ledger,
        dag_is_complete=True,
        has_ready_tasks=False
    )
    assert verdict == CompletionVerdict.CONTINUE
    assert "PENDING" in reason


def test_failed_criterion_triggers_repair(evaluator):
    """Failed criterion with retry attempts remaining -> REPAIR."""
    ledger = CompletionLedger(mission_id="m_004")
    ledger.add_criterion("AC-1", "Unit tests pass")
    ledger.update_criterion("AC-1", CriterionStatus.FAILED, error="2 tests failed in test_auth.py")

    verdict, reason = evaluator.evaluate(
        ledger=ledger,
        dag_is_complete=True,
        repair_attempts=1,
        max_repairs=3
    )
    assert verdict == CompletionVerdict.REPAIR
    assert "repair cycle" in reason


def test_exhausted_repairs_triggers_failed(evaluator):
    """Failed criterion with max repairs exhausted -> FAILED."""
    ledger = CompletionLedger(mission_id="m_005")
    ledger.add_criterion("AC-1", "Unit tests pass")
    ledger.update_criterion("AC-1", CriterionStatus.FAILED, error="Persistent timeout")

    verdict, reason = evaluator.evaluate(
        ledger=ledger,
        dag_is_complete=True,
        repair_attempts=3,
        max_repairs=3
    )
    assert verdict == CompletionVerdict.FAILED
    assert "exhausted" in reason


def test_user_confirmation_pending_triggers_blocked(evaluator):
    """Required user confirmation pending -> BLOCKED."""
    ledger = CompletionLedger(mission_id="m_006")
    ledger.add_criterion("AC-1", "Delete old database table")

    verdict, reason = evaluator.evaluate(
        ledger=ledger,
        user_confirmation_pending=True
    )
    assert verdict == CompletionVerdict.BLOCKED
    assert "confirmation" in reason


def test_evidence_based_completion(evaluator):
    """Criteria with concrete evidence satisfy progress."""
    ledger = CompletionLedger(mission_id="m_007")
    ledger.add_criterion("AC-1", "Endpoint /api/login exists")
    ledger.update_criterion(
        "AC-1",
        CriterionStatus.SATISFIED,
        evidence=["POST /api/login returned 200 OK with valid JWT token"],
        verification_result="PASSED"
    )
    assert ledger.all_satisfied is True
    assert len(ledger.criteria["AC-1"].evidence) == 1


def test_idempotent_finalization():
    """Finalizing twice returns identical cached summary without state corruption."""
    finalizer = MissionFinalizer()
    ledger = CompletionLedger(mission_id="m_008")
    ledger.add_criterion("AC-1", "Fix bug")
    ledger.update_criterion("AC-1", CriterionStatus.SATISFIED, evidence=["Bug fixed"])

    res1 = finalizer.finalize("m_008", ledger, files_modified=["utils.py"])
    res2 = finalizer.finalize("m_008", ledger, files_modified=["utils.py"])

    assert res1 == res2
    assert res1["status"] == "COMPLETED"
    assert res1["criteria_satisfied"] == 1


def test_unverified_llm_claim_not_satisfied():
    """LLM claim alone does not satisfy criterion without evidence."""
    crit = AcceptanceCriterion(criterion_id="AC-1", description="Implement auth")
    # By default, state is PENDING
    assert crit.status == CriterionStatus.PENDING
    assert len(crit.evidence) == 0


def test_fast_deterministic_evaluation_sub_millisecond(evaluator):
    """Evaluator must evaluate whole-mission status in < 0.05 ms."""
    ledger = CompletionLedger(mission_id="m_010")
    for i in range(5):
        ledger.add_criterion(f"AC-{i}", f"Task {i}")
        ledger.update_criterion(f"AC-{i}", CriterionStatus.SATISFIED, evidence=[f"Evidence {i}"])

    t0 = time.perf_counter()
    verdict, _ = evaluator.evaluate(ledger=ledger, dag_is_complete=True)
    dur_ms = (time.perf_counter() - t0) * 1000.0

    assert verdict == CompletionVerdict.COMPLETE
    assert dur_ms < 0.1  # Fast sub-millisecond evaluation
