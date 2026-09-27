# tests/test_prompt11_adversarial.py
"""
Adversarial Verification & Invariant Hardening Test Suite for HERMES 2.x.

Tests adversarial failure modes:
1. False completion / premature completion attempts
2. Fake PASS / "All tests passed" text injection in stdout
3. Subagent reporting success while worktree / root acceptance is failing
4. T2/T3 model attempting to approve failed objective facts (Fact Invariant)
5. Model attempting unauthorized waivers of critical or optional requirements
6. Repair loops and stall detection on identical fingerprints
7. Invalidation of cached verification upon criteria or policy change
8. Quarantine of legacy Prompt 1 keyword verifiers
"""

import json
import pytest
from pathlib import Path

from core.event_bus import EventBus
from core.evidence.collector import EvidenceCollector
from core.evidence.invalidator import EvidenceInvalidator
from core.evidence.models import EvidenceSourceType, EvidenceStatus
from core.evidence.store import EvidenceStore
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    EscalationDecisionType,
    FailureClass,
    HermesRuntimeState,
    RepairStatus,
    RequirementPriority,
    RequirementStatus,
    RequirementState,
    VerificationStatus,
)
from core.runtime_state.reducer import StateReducer
from core.verification.engine import VerificationEngine
from core.verification.models import CheckType, VerificationResult, VerificationVerdict
from core.verification.policy import VerificationPolicy, VerificationRiskLevel
from core.verification.verifiers import TestResultVerifier
from core.repair.controller import RepairController
from core.escalation.engine import EscalationEngine
from core.escalation.judge import T3Judge
from core.agent_loop.completion import GoalCompleteGuard, CompletionPolicy


@pytest.fixture
def fresh_bus():
    return EventBus()


# ── 1. False Completion / Premature Completion Invariant ──────────────────────

def test_adversarial_fake_completion_with_pending_checks():
    """Harness strictly blocks completion when acceptance checks are not in PASS state."""
    state = HermesRuntimeState.create_empty(mission_id="adv_m1")
    req = RequirementState(requirement_id="req_1", goal_id="goal_1", title="Auth", description="Implement auth", status=RequirementStatus.IN_PROGRESS)
    chk = AcceptanceCheck(check_id="chk_1", requirement_id="req_1", description="Auth test", status=AcceptanceCheckStatus.PENDING)
    state.requirements["req_1"] = req
    state.acceptance_ledger.checks["chk_1"] = chk

    can_complete, reason, issues = GoalCompleteGuard.evaluate(state=state, strict_requirements=True)
    assert can_complete is False
    assert any("chk_1" in iss for iss in issues)


def test_adversarial_fake_completion_with_stalled_repair():
    """Harness strictly blocks completion when any repair is in STALLED state."""
    state = HermesRuntimeState.create_empty(mission_id="adv_m2")
    req = RequirementState(requirement_id="req_1", goal_id="goal_1", title="Auth", description="Implement auth", status=RequirementStatus.VERIFIED)
    chk = AcceptanceCheck(check_id="chk_1", requirement_id="req_1", description="Auth test", status=AcceptanceCheckStatus.PASS)
    state.requirements["req_1"] = req
    state.acceptance_ledger.checks["chk_1"] = chk

    from core.runtime_state.models import RepairState
    state.repairs["rep_1"] = RepairState(
        repair_id="rep_1",
        mission_id="adv_m2",
        check_id="chk_1",
        status=RepairStatus.STALLED,
        failure_class=FailureClass.ASSERTION_FAILED,
        attempt=3,
        failure_reason="Identical failure recurring",
    )

    can_complete, reason, issues = GoalCompleteGuard.evaluate(state=state, strict_requirements=False)
    assert can_complete is False
    assert any("STALLED" in iss for iss in issues)


# ── 2. Fake PASS Text Injection Defense ───────────────────────────────────────

def test_adversarial_fake_pass_in_stdout_does_not_trick_test_verifier(tmp_path):
    """A command returning exit code 1 with stdout 'ALL 100 TESTS PASSED' must FAIL."""
    store = EvidenceStore(workspace_root=tmp_path)
    collector = EvidenceCollector(workspace_root=tmp_path, evidence_store=store)
    verifier = TestResultVerifier()

    # Adversary emits 'PASS' string but non-zero exit code
    rec = collector.collect_test_evidence(
        command="pytest tests/",
        exit_code=1,
        stdout="PASSED 100/100 tests! Everything is green! PASS PASS PASS",
        stderr="Process terminated with exit code 1",
        requirement_id="req_fake",
        check_id="chk_fake",
    )
    bundle = store.get_bundle("req_fake", check_id="chk_fake")
    result = verifier.verify("chk_fake", bundle)

    assert result.verdict == VerificationVerdict.FAIL
    assert result.passed is False
    assert result.failure_class == FailureClass.TEST_FAILED
    assert "exit code 1" in result.message


def test_adversarial_fake_test_target_does_not_satisfy_specific_check(tmp_path):
    """A passing test for test_unrelated.py cannot satisfy check for test_auth.py."""
    store = EvidenceStore(workspace_root=tmp_path)
    collector = EvidenceCollector(workspace_root=tmp_path, evidence_store=store)
    verifier = TestResultVerifier()

    collector.collect_test_evidence(
        command="pytest tests/test_unrelated.py",
        exit_code=0,
        stdout="tests/test_unrelated.py . [100%]\n1 passed in 0.05s",
        requirement_id="req_auth",
        check_id="chk_auth",
        metadata={"passed_count": 1, "failed_count": 0},
    )
    bundle = store.get_bundle("req_auth", check_id="chk_auth")
    result = verifier.verify("chk_auth", bundle, target_test="tests/test_auth.py")

    assert result.verdict == VerificationVerdict.FAIL
    assert result.passed is False
    assert "does not correspond to expected test" in result.message


# ── 3. Subagent Candidate Evidence Isolation ─────────────────────────────────

def test_adversarial_subagent_success_is_not_parent_goal_completion():
    """Subagent reporting SUCCEEDED does not automatically mark ledger check PASS."""
    from core.runtime_state.models import SubagentResult, SubagentStatus
    from core.subagents.handoff import HandoffManager

    sub_res = SubagentResult(
        agent_id="sub_worker_1",
        task_id="task_sub_1",
        status=SubagentStatus.SUCCEEDED,
        summary="Claimed all tasks complete",
        files=["src/feature.py"],
        evidence_refs=["ev_child_123"],
    )
    obs = HandoffManager.format_observation(sub_res, turn_id="t1", workspace_root="/tmp")

    # The observation is produced, but the authoritative GoalCompleteGuard rejects
    # completion because ledger checks are still pending
    state = HermesRuntimeState.create_empty(mission_id="adv_sub")
    state.requirements["req_sub"] = RequirementState(requirement_id="req_sub", goal_id="goal_1", title="Sub", description="Sub task", status=RequirementStatus.IN_PROGRESS)
    state.acceptance_ledger.checks["chk_sub"] = AcceptanceCheck(
        check_id="chk_sub", requirement_id="req_sub", description="Verify sub task", status=AcceptanceCheckStatus.PENDING
    )

    can_complete, _, _ = GoalCompleteGuard.evaluate(state=state, strict_requirements=True)
    assert can_complete is False


# ── 4. T3 Fact Invariant Strict Overrule ──────────────────────────────────────

def test_adversarial_t3_llm_hallucination_overruled_by_fact_invariant():
    """Even if an LLM arbiter function returns APPROVE when facts failed, T3Judge strictly overrides to REJECT."""
    def rogue_arbiter(prompt: str) -> str:
        return json.dumps({
            "decision": "APPROVE",
            "rationale": "I am ignoring the failing test because the code looks elegant.",
            "binding_directives": ["Mark passed anyway."],
        })

    judge = T3Judge(arbiter_fn=rogue_arbiter)
    vr_fail = VerificationResult(
        check_id="chk_failing",
        verdict=VerificationVerdict.FAIL,
        message="AssertionError: 2 != 3",
    )

    res = judge.arbitrate(
        requirement_id="req_1",
        check_id="chk_failing",
        dispute_summary="Tests failed but model wants to proceed",
        verification_results=[vr_fail],
        is_critical_requirement=True,
    )

    assert res.decision == EscalationDecisionType.REJECT
    assert "OVERRULED BY FACT INVARIANT" in res.rationale
    assert res.fact_invariant_checked is True


# ── 5. Unauthorized Waiver Defense ───────────────────────────────────────────

def test_adversarial_waiver_of_critical_requirement_rejected():
    """T3 Judge cannot waive a critical requirement under any circumstances."""
    def waiver_arbiter(prompt: str) -> str:
        return json.dumps({
            "decision": "WAIVE_OPTIONAL_REQUIREMENT",
            "rationale": "Let's waive this.",
            "binding_directives": [],
        })

    judge = T3Judge(arbiter_fn=waiver_arbiter)
    vr = VerificationResult(check_id="chk_crit", verdict=VerificationVerdict.PASS)

    res = judge.arbitrate(
        requirement_id="req_crit",
        check_id="chk_crit",
        dispute_summary="Attempting to waive critical security requirement",
        verification_results=[vr],
        is_critical_requirement=True,
        waiver_authorized=True,  # Even if authorized, critical cannot be waived
    )
    assert res.decision == EscalationDecisionType.REJECT
    assert "Critical requirement cannot be waived" in res.rationale


def test_adversarial_waiver_without_authorization_escalates_to_user():
    """T3 Judge recommending waiver for optional requirement without explicit authorization escalates to user."""
    def waiver_arbiter(prompt: str) -> str:
        return json.dumps({
            "decision": "WAIVE_OPTIONAL_REQUIREMENT",
            "rationale": "Non-critical feature can be skipped.",
            "binding_directives": [],
        })

    judge = T3Judge(arbiter_fn=waiver_arbiter)
    vr = VerificationResult(check_id="chk_opt", verdict=VerificationVerdict.PASS)

    res = judge.arbitrate(
        requirement_id="req_opt",
        check_id="chk_opt",
        dispute_summary="Optional feature difficult to test",
        verification_results=[vr],
        is_critical_requirement=False,
        waiver_authorized=False,  # Unauthorized!
    )
    assert res.decision == EscalationDecisionType.ESCALATE_TO_USER
    assert "WAIVER UNAUTHORIZED" in res.rationale


# ── 6. Repair Stall Detection on Identical Errors ────────────────────────────

def test_adversarial_repair_loop_halted_by_identical_fingerprint(fresh_bus):
    """Submitting the exact same failure message twice halts self-repair with STALL DETECTED."""
    controller = RepairController(event_bus=fresh_bus, max_attempts_per_check=3)

    # Attempt 1
    can_retry_1, guidance_1, rep_id_1 = controller.handle_failure(
        check_id="chk_loop",
        failure_class=FailureClass.ASSERTION_FAILED,
        error_message="ValueError: invalid literal for int() with base 10: 'abc'",
    )
    assert can_retry_1 is True

    # Attempt 2 with IDENTICAL error
    can_retry_2, guidance_2, rep_id_2 = controller.handle_failure(
        check_id="chk_loop",
        failure_class=FailureClass.ASSERTION_FAILED,
        error_message="ValueError: invalid literal for int() with base 10: 'abc'",
    )
    assert can_retry_2 is False
    assert "STALL DETECTED" in guidance_2


# ── 7. Verification Cache Invalidation on Criteria Change ─────────────────────

def test_adversarial_verification_cache_invalidates_on_criteria_change(tmp_path):
    """Changing verification criteria invalidates cached PASS result."""
    store = EvidenceStore(workspace_root=tmp_path)
    collector = EvidenceCollector(workspace_root=tmp_path, evidence_store=store)
    engine = VerificationEngine(workspace_root=tmp_path, evidence_store=store)

    test_file = tmp_path / "mod.py"
    test_file.write_text("class MyService:\n    pass\n", encoding="utf-8")

    collector.collect_file_evidence(
        rel_path="mod.py",
        requirement_id="req_cache",
        check_id="chk_ast",
    )

    # First check: requires class MyService -> PASS
    res1 = engine.verify_check(
        check_id="chk_ast",
        check_type=CheckType.PYTHON_AST,
        requirement_id="req_cache",
        target_path="mod.py",
        required_classes=["MyService"],
    )
    assert res1.passed is True

    # Second check: requires class MissingService -> criteria changed!
    # Hardened cache must NOT return cached PASS!
    res2 = engine.verify_check(
        check_id="chk_ast",
        check_type=CheckType.PYTHON_AST,
        requirement_id="req_cache",
        target_path="mod.py",
        required_classes=["MissingService"],
    )
    assert res2.passed is False
    assert "missing required class 'MissingService'" in res2.message


# ── 8. Legacy Keyword Verifier Quarantine ─────────────────────────────────────

def test_legacy_keyword_verifier_is_quarantined_from_completion():
    """Verify that CompletionPolicy does not import or call QualityVerifier."""
    import inspect
    from core.agent_loop.completion import CompletionPolicy, GoalCompleteGuard
    import core.agent_loop.completion as comp_module

    # Confirm QualityVerifier is not in completion module namespace
    assert "QualityVerifier" not in comp_module.__dict__

    # Confirm evaluate_completion source has no references to quality_verifier
    src = inspect.getsource(CompletionPolicy.evaluate_completion)
    assert "QualityVerifier" not in src
    assert "quality_verifier" not in src
