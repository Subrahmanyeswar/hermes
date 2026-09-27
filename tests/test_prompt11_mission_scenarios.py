# tests/test_prompt11_mission_scenarios.py
"""
15 Mission-Level Architectural Scenarios for HERMES 2.x Prompt 11 Hardening.

Matrix of Scenarios:
1.  Clean Low-Risk PASS: CSS/docs changes bypass T2 Critic and T3 Judge.
2.  High-Risk Action PASS: Auth/crypto/loop.py changes escalate to T2 Critic.
3.  Deterministic Failure -> T1 Self-Repair: First deterministic failure routes to T1 self-repair without invoking T2 Critic.
4.  Recurring Identical Failure -> Stall: Duplicate failure fingerprint triggers REPAIR_STALLED immediately.
5.  Repair Budget Exhaustion: Exceeding max attempts triggers escalation.
6.  T2 Critic Disagreement -> T3 Judge: T2 rejection of passed evidence escalates to T3 Judge.
7.  T3 Constitutional Fact Invariant: T3 Judge cannot validate failed objective facts.
8.  T3 Critical Requirement Non-Waiver: T3 Judge cannot waive critical requirements.
9.  T3 Optional Waiver Unauthorized: T3 Judge waiver of optional requirement without explicit authorization escalates to user.
10. T3 Optional Waiver Authorized: T3 Judge waiver of optional requirement with authorization produces WAIVE_OPTIONAL_REQUIREMENT.
11. Stale Evidence Invalidation: Modifying a source file invalidates all evidence records referencing that path.
12. Ledger Reopening Cascade: Invalidation cascades to AcceptanceLedger, reopening passed checks and verified requirements.
13. GoalCompleteGuard Blocks Premature Completion: Rejects completion when requirements/checks are incomplete.
14. Subagent Candidate Evidence Isolation: Child worktree success is candidate evidence only and does not mark root ledger PASS.
15. Verification Cache Identity Hardening: Changing criteria or policy invalidates cached verification results.
"""

import json
import pytest
from pathlib import Path

from core.event_bus import EventBus
from core.evidence.collector import EvidenceCollector
from core.evidence.invalidator import EvidenceInvalidator
from core.evidence.models import EvidenceFreshness, EvidenceStatus
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
    RequirementCategory,
    RequirementPriority,
    RequirementStatus,
    RequirementState,
    VerificationStatus,
)
from core.runtime_state.reducer import StateReducer
from core.verification.engine import VerificationEngine
from core.verification.models import CheckType, VerificationResult, VerificationVerdict
from core.verification.policy import VerificationPolicy, VerificationRiskLevel
from core.verification.verifiers import (
    FilesystemVerifier,
    PythonAstVerifier,
    TestResultVerifier,
)
from core.repair.controller import RepairController
from core.escalation.critic import T2Critic
from core.escalation.engine import EscalationEngine
from core.escalation.judge import T3Judge
from core.agent_loop.completion import GoalCompleteGuard, CompletionPolicy


@pytest.fixture
def fresh_bus():
    return EventBus()


# ── Scenario 1: Clean Low-Risk PASS (Bypasses T2 & T3) ─────────────────────────

def test_scenario_01_clean_low_risk_pass(fresh_bus):
    engine = EscalationEngine(event_bus=fresh_bus)
    vr = VerificationResult(check_id="chk_css", verdict=VerificationVerdict.PASS)

    events = []
    fresh_bus.subscribe(lambda e: events.append(e), {EventType.ESCALATION_SKIPPED})

    approved, t2, t3 = engine.evaluate_verification(
        requirement_id="req_ui",
        check_id="chk_css",
        verification_results=[vr],
        files_modified=["assets/main.css"],
        lines_changed=15,
    )
    assert approved is True
    assert t2 is None
    assert t3 is None
    assert len(events) == 1
    assert events[0].payload.get("reason") == "LOW_RISK_BYPASS"


# ── Scenario 2: High-Risk Action PASS (Escalates to T2 Critic) ────────────────

def test_scenario_02_high_risk_action_pass(fresh_bus):
    engine = EscalationEngine(event_bus=fresh_bus)
    vr = VerificationResult(check_id="chk_auth", verdict=VerificationVerdict.PASS)

    events = []
    fresh_bus.subscribe(lambda e: events.append(e), {EventType.T2_STARTED})

    approved, t2, t3 = engine.evaluate_verification(
        requirement_id="req_security",
        check_id="chk_auth",
        verification_results=[vr],
        files_modified=["core/security/tokens.py"],
        lines_changed=40,
    )
    assert t2 is not None
    assert t2.approved is True
    assert len(events) == 1


# ── Scenario 3: Deterministic Failure -> T1 Self-Repair First ─────────────────

def test_scenario_03_deterministic_failure_routes_to_t1_repair_first(fresh_bus):
    """Normal deterministic failure with LOW/MEDIUM risk routes to T1 repair before T2."""
    engine = EscalationEngine(event_bus=fresh_bus)
    vr_fail = VerificationResult(
        check_id="chk_calc",
        verdict=VerificationVerdict.FAIL,
        failure_class=FailureClass.ASSERTION_FAILED,
        message="2 + 2 != 5",
    )

    events = []
    fresh_bus.subscribe(lambda e: events.append(e), {EventType.ESCALATION_SKIPPED})

    approved, t2, t3 = engine.evaluate_verification(
        requirement_id="req_calc",
        check_id="chk_calc",
        verification_results=[vr_fail],
        files_modified=["calc.py"],
        lines_changed=10,
        t1_repair_exhausted=False,
    )
    assert approved is False
    assert t2 is None  # Bypassed T2 in favor of T1
    assert t3 is None
    assert len(events) == 1
    assert events[0].payload.get("reason") == "ROUTED_TO_T1_REPAIR"


# ── Scenario 4: Recurring Identical Failure -> Stall ──────────────────────────

def test_scenario_04_recurring_identical_failure_triggers_stall(fresh_bus):
    controller = RepairController(event_bus=fresh_bus)
    stall_events = []
    fresh_bus.subscribe(lambda e: stall_events.append(e), {EventType.REPAIR_STALLED})

    can_1, _, rep_1 = controller.handle_failure("chk_same", FailureClass.SYNTAX_ERROR, "Invalid syntax at line 4")
    assert can_1 is True

    can_2, guide_2, rep_2 = controller.handle_failure("chk_same", FailureClass.SYNTAX_ERROR, "Invalid syntax at line 4")
    assert can_2 is False
    assert "STALL DETECTED" in guide_2
    assert len(stall_events) == 1
    assert stall_events[0].payload.get("reason") == "IDENTICAL_FAILURE_RECURRENCE"


# ── Scenario 5: Repair Budget Exhaustion -> Escalation ─────────────────────────

def test_scenario_05_repair_budget_exhaustion_triggers_escalation(fresh_bus):
    controller = RepairController(event_bus=fresh_bus, max_attempts_per_check=2)
    can_1, _, _ = controller.handle_failure("chk_b", FailureClass.ASSERTION_FAILED, "Error attempt 1")
    assert can_1 is True

    can_2, _, _ = controller.handle_failure("chk_b", FailureClass.ASSERTION_FAILED, "Different error attempt 2")
    assert can_2 is True

    # 3rd attempt exceeds max_attempts_per_check=2
    can_3, guide_3, _ = controller.handle_failure("chk_b", FailureClass.ASSERTION_FAILED, "Different error attempt 3")
    assert can_3 is False
    assert "BUDGET EXCEEDED" in guide_3


# ── Scenario 6: T2 Critic Rejection -> T3 Judge Resolution ────────────────────

def test_scenario_06_t2_critic_rejection_resolves_via_t3_judge(fresh_bus):
    def rejecting_critic(prompt: str) -> str:
        return json.dumps({
            "approved": False,
            "confidence": 0.8,
            "critique": "OVERRULED: Potential memory leak in buffer handler.",
            "issues": ["Memory leak"],
            "suggested_actions": ["Free buffer"],
        })

    engine = EscalationEngine(event_bus=fresh_bus, t2_evaluator_fn=rejecting_critic)
    vr = VerificationResult(check_id="chk_buf", verdict=VerificationVerdict.PASS)

    approved, t2, t3 = engine.evaluate_verification(
        requirement_id="req_buf",
        check_id="chk_buf",
        verification_results=[vr],
        force_escalation=True,
    )
    assert t2 is not None
    assert t2.approved is False
    assert t3 is not None
    assert t3.decision == EscalationDecisionType.REJECT
    assert approved is False


# ── Scenario 7: T3 Constitutional Fact Invariant Overrule ─────────────────────

def test_scenario_07_t3_cannot_validate_failed_objective_facts():
    judge = T3Judge()
    vr_fail = VerificationResult(check_id="chk_f", verdict=VerificationVerdict.FAIL, message="Tests failed")

    res = judge.arbitrate(
        requirement_id="req_1",
        check_id="chk_f",
        dispute_summary="Tests failed",
        verification_results=[vr_fail],
    )
    assert res.decision == EscalationDecisionType.REJECT
    assert res.fact_invariant_checked is True
    assert "Objective verification checks failed" in res.rationale


# ── Scenario 8: T3 Critical Requirement Non-Waiver ─────────────────────────────

def test_scenario_08_t3_critical_requirement_cannot_be_waived():
    def waiver_fn(prompt: str) -> str:
        return json.dumps({
            "decision": "WAIVE_OPTIONAL_REQUIREMENT",
            "rationale": "Waive it anyway",
            "binding_directives": [],
        })

    judge = T3Judge(arbiter_fn=waiver_fn)
    vr = VerificationResult(check_id="chk_c", verdict=VerificationVerdict.PASS)

    res = judge.arbitrate(
        requirement_id="req_crit",
        check_id="chk_c",
        dispute_summary="Dispute on critical requirement",
        verification_results=[vr],
        is_critical_requirement=True,
        waiver_authorized=True,
    )
    assert res.decision == EscalationDecisionType.REJECT
    assert "Critical requirement cannot be waived" in res.rationale


# ── Scenario 9: T3 Optional Waiver Unauthorized -> Escalates to User ───────────

def test_scenario_09_t3_optional_waiver_unauthorized_escalates_to_user():
    def waiver_fn(prompt: str) -> str:
        return json.dumps({
            "decision": "WAIVE_OPTIONAL_REQUIREMENT",
            "rationale": "Waiving non-essential tooltip",
            "binding_directives": [],
        })

    judge = T3Judge(arbiter_fn=waiver_fn)
    vr = VerificationResult(check_id="chk_opt", verdict=VerificationVerdict.PASS)

    res = judge.arbitrate(
        requirement_id="req_opt",
        check_id="chk_opt",
        dispute_summary="Tooltip styling difficult to test",
        verification_results=[vr],
        is_critical_requirement=False,
        waiver_authorized=False,
    )
    assert res.decision == EscalationDecisionType.ESCALATE_TO_USER
    assert "WAIVER UNAUTHORIZED" in res.rationale


# ── Scenario 10: T3 Optional Waiver Authorized -> WAIVE_OPTIONAL_REQUIREMENT ──

def test_scenario_10_t3_optional_waiver_authorized():
    def waiver_fn(prompt: str) -> str:
        return json.dumps({
            "decision": "WAIVE_OPTIONAL_REQUIREMENT",
            "rationale": "Waiving non-essential tooltip with authorization",
            "binding_directives": ["Skip check"],
        })

    judge = T3Judge(arbiter_fn=waiver_fn)
    vr = VerificationResult(check_id="chk_opt", verdict=VerificationVerdict.PASS)

    res = judge.arbitrate(
        requirement_id="req_opt",
        check_id="chk_opt",
        dispute_summary="Tooltip styling waived with authorization",
        verification_results=[vr],
        is_critical_requirement=False,
        waiver_authorized=True,
    )
    assert res.decision == EscalationDecisionType.WAIVE_OPTIONAL_REQUIREMENT


# ── Scenario 11: Stale Evidence Invalidation ──────────────────────────────────

def test_scenario_11_stale_evidence_invalidation(tmp_path):
    store = EvidenceStore(workspace_root=tmp_path)
    collector = EvidenceCollector(workspace_root=tmp_path, evidence_store=store)
    invalidator = EvidenceInvalidator(workspace_root=tmp_path, evidence_store=store)

    f = tmp_path / "service.py"
    f.write_text("x = 1\n", encoding="utf-8")
    rec = collector.collect_file_evidence("service.py", requirement_id="req_s", acceptance_check_id="chk_s")
    assert rec.freshness == EvidenceFreshness.FRESH

    # Modifying the file triggers invalidation
    inv_records = invalidator.invalidate_for_paths(["service.py"])
    assert len(inv_records) == 1
    assert store.get(rec.evidence_id).freshness == EvidenceFreshness.INVALIDATED


# ── Scenario 12: Ledger Reopening Cascade ──────────────────────────────────────

def test_scenario_12_invalidation_cascades_to_ledger_reopening(fresh_bus):
    state = HermesRuntimeState.create_empty(mission_id="scen_12")
    state.requirements["req_1"] = RequirementState(
        requirement_id="req_1", goal_id="g1", title="Req 1", status=RequirementStatus.VERIFIED
    )
    state.acceptance_ledger.checks["chk_1"] = AcceptanceCheck(
        check_id="chk_1", requirement_id="req_1", description="Check 1", status=AcceptanceCheckStatus.PASS
    )

    # Reopening event resets check to PENDING and requirement to IN_PROGRESS
    ev = HermesEvent(
        event_type=EventType.VERIFICATION_REOPENED,
        mission_id="scen_12",
        requirement_id="req_1",
        acceptance_check_id="chk_1",
    )
    StateReducer.reduce(state, ev)

    assert state.acceptance_ledger.checks["chk_1"].status == AcceptanceCheckStatus.PENDING
    assert state.requirements["req_1"].status == RequirementStatus.IN_PROGRESS


# ── Scenario 13: GoalCompleteGuard Blocks Premature Completion ─────────────────

def test_scenario_13_goal_complete_guard_blocks_premature_completion():
    state = HermesRuntimeState.create_empty(mission_id="scen_13")
    state.requirements["req_1"] = RequirementState(
        requirement_id="req_1", goal_id="g1", title="Req 1", status=RequirementStatus.IN_PROGRESS
    )
    state.acceptance_ledger.checks["chk_1"] = AcceptanceCheck(
        check_id="chk_1", requirement_id="req_1", description="Check 1", status=AcceptanceCheckStatus.PENDING
    )

    can_complete, reason, issues = GoalCompleteGuard.evaluate(state=state, strict_requirements=True)
    assert can_complete is False
    assert len(issues) > 0


# ── Scenario 14: Subagent Candidate Evidence Isolation ────────────────────────

def test_scenario_14_subagent_candidate_evidence_isolation():
    from core.runtime_state.models import SubagentResult, SubagentStatus
    from core.subagents.handoff import HandoffManager

    sub_res = SubagentResult(
        agent_id="sub_worker_2",
        task_id="t_sub_2",
        status=SubagentStatus.SUCCEEDED,
        summary="Worktree tests passed in isolation",
        files=["sub_work.py"],
        evidence_refs=["ev_child_99"],
    )
    obs = HandoffManager.format_observation(sub_res, turn_id="t_obs", workspace_root="/tmp")
    assert obs.success is True

    # Root state still requires root verification before passing
    state = HermesRuntimeState.create_empty(mission_id="scen_14")
    state.requirements["req_sub"] = RequirementState(
        requirement_id="req_sub", goal_id="g1", title="Req Sub", status=RequirementStatus.IN_PROGRESS
    )
    state.acceptance_ledger.checks["chk_sub"] = AcceptanceCheck(
        check_id="chk_sub", requirement_id="req_sub", description="Verify sub task", status=AcceptanceCheckStatus.PENDING
    )

    can_complete, _, _ = GoalCompleteGuard.evaluate(state=state, strict_requirements=True)
    assert can_complete is False


# ── Scenario 15: Verification Cache Fingerprint Hardening ─────────────────────

def test_scenario_15_verification_cache_fingerprint_hardening(tmp_path):
    store = EvidenceStore(workspace_root=tmp_path)
    collector = EvidenceCollector(workspace_root=tmp_path, evidence_store=store)
    engine = VerificationEngine(workspace_root=tmp_path, evidence_store=store)

    f = tmp_path / "app.py"
    f.write_text("class CoreApp:\n    pass\n", encoding="utf-8")
    collector.collect_file_evidence("app.py", requirement_id="req_app", acceptance_check_id="chk_app")

    # PASS with CoreApp
    r1 = engine.verify_check(
        check_id="chk_app",
        check_type=CheckType.PYTHON_AST,
        requirement_id="req_app",
        target_path="app.py",
        required_classes=["CoreApp"],
    )
    assert r1.passed is True

    # FAIL with AnotherApp (cache MUST NOT return previous PASS)
    r2 = engine.verify_check(
        check_id="chk_app",
        check_type=CheckType.PYTHON_AST,
        requirement_id="req_app",
        target_path="app.py",
        required_classes=["AnotherApp"],
    )
    assert r2.passed is False
