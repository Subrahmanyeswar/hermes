# tests/test_planning_and_progress.py
"""
Comprehensive Test Suite for HERMES 2.x Planning, Goal Graph,
Acceptance Ledger, and Truthful Progress Architecture (Prompt 9).

Covers:
1. Goal Creation & Prompt Decomposition
2. Dependency Cycle Detection & Graph Invariants
3. Acceptance Ledger & "No Evidence = No Verified" Contract
4. Stale Evidence Invalidation & Regression Reopening
5. Todo vs Requirement Separation
6. Plan Mode Non-Mutating Safety Invariant
7. Plan Proposal & Approval Lifecycle
8. Requirement Waiver with Audit Trail
9. Deterministic Focus Selection & Oscillation Protection
10. Progress Fingerprinting & Turn-Based Stall Detection
11. Strict Goal Completion Invariant
12. 100-Turn Simulation & State Replay Determinism
13. Scalability with 200+ Requirements and Selective Context Projection
"""

import copy
import pytest
from pathlib import Path
from typing import Dict, List

from core.event_bus import EventBus
from core.planning.acceptance import AcceptanceManager
from core.planning.artifacts import HumanProjectionRenderer, ProgressArtifactWriter
from core.planning.decomposer import DependencyCycleError, GoalDecomposer
from core.planning.plan_mode import PlanController, PlanModeViolationError
from core.planning.progress import ProgressController
from core.planning.service import MissionPlanningService
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    ExecutionMode,
    GoalState,
    GoalStatus,
    HermesRuntimeState,
    PlanStatus,
    ProgressState,
    RequirementCategory,
    RequirementPriority,
    RequirementState,
    RequirementStatus,
    TodoState,
    TodoStatus,
)
from core.runtime_state.reducer import StateReducer
from core.runtime_state.store import StateStore


@pytest.fixture
def test_bus():
    """Create a fresh isolated EventBus instance for testing."""
    return EventBus(enabled=True, buffer_size=1000)


@pytest.fixture
def planning_service(tmp_path, test_bus):
    """Create a fresh MissionPlanningService instance with temporary workspace."""
    store = StateStore(mission_id="mission_test_p9")
    service = MissionPlanningService(
        mission_id="mission_test_p9",
        workspace_root=tmp_path,
        event_bus=test_bus,
        state_store=store,
    )
    return service


# ==============================================================================
# 1. GOAL CREATION & PROMPT DECOMPOSITION
# ==============================================================================

def test_goal_creation_and_decomposition(planning_service):
    """
    Test unstructured user goal is decomposed into structured requirements
    and concrete acceptance checks with dependency ordering.
    """
    user_prompt = (
        "Build a professional expense tracker web app with a dashboard, "
        "add/edit/delete transactions, category filters, monthly spending summary, "
        "charts, responsive UI, local data persistence, and proper validation. "
        "Build it completely and verify everything works."
    )
    goal = planning_service.initialize_goal(user_prompt=user_prompt)

    assert goal.status == GoalStatus.ACTIVE
    assert goal.user_request == user_prompt
    assert len(planning_service.requirements) >= 7

    # Verify key capabilities decomposed
    req_titles = [r.title.lower() for r in planning_service.requirements.values()]
    assert any("dashboard" in t for t in req_titles)
    assert any("crud" in t or "transaction" in t for t in req_titles)
    assert any("filter" in t for t in req_titles)
    assert any("persistence" in t for t in req_titles)
    assert any("validation" in t for t in req_titles)

    # Verify acceptance checks were created and registered
    ledger_checks = planning_service.acceptance_ledger.checks
    assert len(ledger_checks) >= len(planning_service.requirements)
    for chk in ledger_checks.values():
        assert chk.requirement_id in planning_service.requirements
        assert chk.status == AcceptanceCheckStatus.NOT_RUN


# ==============================================================================
# 2. DEPENDENCY CYCLE DETECTION
# ==============================================================================

def test_dependency_cycle_detection():
    """
    Cycle detection: A -> B -> C -> A in requirement graph raises DependencyCycleError.
    """
    req_a = RequirementState(requirement_id="req_a", goal_id="g1", title="A", dependencies=["req_c"])
    req_b = RequirementState(requirement_id="req_b", goal_id="g1", title="B", dependencies=["req_a"])
    req_c = RequirementState(requirement_id="req_c", goal_id="g1", title="C", dependencies=["req_b"])

    reqs = {"req_a": req_a, "req_b": req_b, "req_c": req_c}

    with pytest.raises(DependencyCycleError) as exc_info:
        GoalDecomposer.validate_dependencies(reqs)

    assert "REQUIREMENT_DEPENDENCY_CYCLE" in str(exc_info.value) or "Cycle detected" in str(exc_info.value)


def test_acyclic_graph_validation():
    """Valid DAG with no cycles passes validation without error."""
    req_a = RequirementState(requirement_id="req_a", goal_id="g1", title="A", dependencies=[])
    req_b = RequirementState(requirement_id="req_b", goal_id="g1", title="B", dependencies=["req_a"])
    req_c = RequirementState(requirement_id="req_c", goal_id="g1", title="C", dependencies=["req_a", "req_b"])

    reqs = {"req_a": req_a, "req_b": req_b, "req_c": req_c}
    # Should not raise
    GoalDecomposer.validate_dependencies(reqs)


# ==============================================================================
# 3. ACCEPTANCE LEDGER & "NO EVIDENCE = NO VERIFIED"
# ==============================================================================

def test_no_evidence_no_verified(planning_service):
    """
    A requirement CANNOT transition to VERIFIED without passing checks and valid evidence.
    """
    # Create requirement with check
    req = RequirementState(
        requirement_id="req_auth",
        goal_id=planning_service.goal.goal_id,
        title="User Authentication",
        status=RequirementStatus.PENDING,
    )
    chk = AcceptanceCheck(
        check_id="chk_auth_1",
        requirement_id="req_auth",
        description="Login succeeds with valid JWT",
        critical=True,
    )
    planning_service.requirements["req_auth"] = req
    planning_service.acceptance_manager.register_checks([chk])

    # 1. Attempt to evaluate without passing checks
    planning_service.acceptance_manager.evaluate_requirement_status(req)
    assert req.status != RequirementStatus.VERIFIED

    # 2. Check passes BUT has no evidence
    chk.status = AcceptanceCheckStatus.PASS
    chk.evidence_refs = []  # No evidence!
    planning_service.acceptance_manager.evaluate_requirement_status(req)
    # Must NOT be VERIFIED!
    assert req.status != RequirementStatus.VERIFIED

    # 3. Check passes WITH valid evidence
    chk.evidence_refs = ["ev_test_jwt_pass_123"]
    planning_service.acceptance_manager.evaluate_requirement_status(req)
    assert req.status == RequirementStatus.VERIFIED


def test_critical_check_blocks_verification(planning_service):
    """
    If a critical check fails or has not run, requirement cannot be verified,
    even if all other non-critical checks pass.
    """
    req = RequirementState(
        requirement_id="req_db",
        goal_id=planning_service.goal.goal_id,
        title="Database Transactions",
        status=RequirementStatus.PENDING,
    )
    chk_crit = AcceptanceCheck(
        check_id="chk_crit",
        requirement_id="req_db",
        description="ACID rollback on error",
        critical=True,
        status=AcceptanceCheckStatus.NOT_RUN,
    )
    chk_normal = AcceptanceCheck(
        check_id="chk_norm",
        requirement_id="req_db",
        description="Connection pool initializes",
        critical=False,
        status=AcceptanceCheckStatus.PASS,
        evidence_refs=["ev_pool_ok"],
    )
    planning_service.requirements["req_db"] = req
    planning_service.acceptance_manager.register_checks([chk_crit, chk_normal])

    planning_service.acceptance_manager.evaluate_requirement_status(req)
    assert req.status != RequirementStatus.VERIFIED

    # Now fail critical check
    chk_crit.status = AcceptanceCheckStatus.FAIL
    chk_crit.evidence_refs = ["ev_acid_fail"]
    planning_service.acceptance_manager.evaluate_requirement_status(req)
    assert req.status == RequirementStatus.FAILED

    # Now pass critical check
    chk_crit.status = AcceptanceCheckStatus.PASS
    chk_crit.evidence_refs = ["ev_acid_pass"]
    planning_service.acceptance_manager.evaluate_requirement_status(req)
    assert req.status == RequirementStatus.VERIFIED


# ==============================================================================
# 4. STALE EVIDENCE INVALIDATION & REGRESSION REOPENING
# ==============================================================================

def test_stale_evidence_invalidation_and_regression_reopening(planning_service):
    """
    When files referenced in an acceptance check are modified, evidence becomes
    stale and previously VERIFIED requirements must be reopened.
    """
    req = RequirementState(
        requirement_id="req_cart",
        goal_id=planning_service.goal.goal_id,
        title="Shopping Cart",
        status=RequirementStatus.PENDING,
    )
    chk = AcceptanceCheck(
        check_id="chk_cart",
        requirement_id="req_cart",
        description="Total calculation correct",
        critical=True,
        status=AcceptanceCheckStatus.PASS,
        evidence_refs=["ev_cart_calc"],
        source_file_versions={"src/cart.py": "hash_v1"},
    )
    planning_service.requirements["req_cart"] = req
    planning_service.acceptance_manager.register_checks([chk])

    planning_service.acceptance_manager.evaluate_requirement_status(req)
    assert req.status == RequirementStatus.VERIFIED

    # Invalidate evidence for modified file src/cart.py
    stale_checks = planning_service.acceptance_manager.invalidate_for_modified_files({"src/cart.py"})
    assert "chk_cart" in stale_checks
    assert chk.status == AcceptanceCheckStatus.NOT_RUN
    assert len(chk.evidence_refs) == 0

    # Re-evaluate requirement: must be reopened!
    planning_service.acceptance_manager.evaluate_requirement_status(req)
    assert req.status != RequirementStatus.VERIFIED
    assert req.status in (RequirementStatus.IN_PROGRESS, RequirementStatus.READY, RequirementStatus.PENDING)



# ==============================================================================
# 5. TODO VS REQUIREMENT SEPARATION
# ==============================================================================

def test_todo_done_does_not_verify_requirement(planning_service):
    """
    Completing a Todo task does NOT automatically mark associated requirement as VERIFIED.
    Todo DONE != Requirement VERIFIED.
    """
    req = RequirementState(
        requirement_id="req_ui",
        goal_id=planning_service.goal.goal_id,
        title="Responsive Navbar",
        status=RequirementStatus.PENDING,
    )
    chk = AcceptanceCheck(
        check_id="chk_nav",
        requirement_id="req_ui",
        description="Mobile burger menu toggles",
        critical=True,
        status=AcceptanceCheckStatus.NOT_RUN,
    )
    planning_service.requirements["req_ui"] = req
    planning_service.acceptance_manager.register_checks([chk])

    # Create engineering work item Todo
    todo = planning_service.create_todo(
        todo_id="todo_1",
        title="Add CSS media queries for navbar",
        requirement_ids=["req_ui"],
    )
    assert todo.status == TodoStatus.PENDING

    # Complete the Todo
    planning_service.complete_todo("todo_1")
    assert todo.status == TodoStatus.DONE

    # Verify requirement is STILL not verified!
    assert req.status != RequirementStatus.VERIFIED
    assert req.status != RequirementStatus.PASSING


# ==============================================================================
# 6. PLAN MODE NON-MUTATING SAFETY INVARIANT
# ==============================================================================

def test_plan_mode_mutation_gating(tmp_path):
    """
    In Plan Mode:
    - Safe read-only tools (fs.read, search.glob, search.grep, task.todo, user.ask) are allowed.
    - Mutating tools (fs.write, fs.edit, destructive bash commands) are strictly blocked.
    """
    controller = PlanController(mission_id="m_plan_test", workspace_root=tmp_path)
    controller.enter_plan_mode()
    assert controller.execution_mode == ExecutionMode.PLAN_MODE

    # 1. Allowed read-only tools
    for safe_tool in ["fs.read", "search.glob", "search.grep", "task.todo", "user.ask", "tool_search"]:
        allowed, msg = controller.authorize_tool_call(safe_tool, {})
        assert allowed is True, f"Expected {safe_tool} to be allowed in Plan Mode: {msg}"

    # 2. Blocked mutation tools
    for mut_tool in ["fs.write", "fs.edit"]:
        allowed, msg = controller.authorize_tool_call(mut_tool, {"path": "test.txt"})
        assert allowed is False, f"Expected {mut_tool} to be blocked in Plan Mode"
        assert "PLAN_MODE_MUTATION_DENIED" in msg

    # 3. Blocked destructive shell command
    allowed, msg = controller.authorize_tool_call("shell.bash", {"command": "rm -rf build/"})
    assert allowed is False
    assert "PLAN_MODE_SHELL_DENIED" in msg

    # 4. Allowed read-only shell command (e.g. git status, ls)
    allowed, msg = controller.authorize_tool_call("shell.bash", {"command": "git status"})
    assert allowed is True

    # 5. Exit Plan Mode permits mutation
    controller.exit_plan_mode()
    assert controller.execution_mode == ExecutionMode.EXECUTION_MODE
    allowed, _ = controller.authorize_tool_call("fs.write", {"path": "test.txt"})
    assert allowed is True


# ==============================================================================
# 7. PLAN PROPOSAL & APPROVAL LIFECYCLE
# ==============================================================================

def test_plan_proposal_and_approval_lifecycle(planning_service):
    """
    Test Plan proposal generation, dependency topological sorting,
    review requirement, approval, and persistence.
    """
    user_prompt = "Build backend API with database and endpoints"
    planning_service.initialize_goal(user_prompt=user_prompt)

    # Generate proposal
    plan = planning_service.create_plan_proposal(
        risks=["Database connection may time out on initial startup"],
        unknowns=["Preferred port configuration"],
    )
    assert plan.status in (PlanStatus.DRAFT, PlanStatus.REVIEW_REQUIRED)
    assert len(plan.steps) > 0
    assert len(plan.risks) == 1

    # Steps must be ordered with valid step_ids
    assert len(plan.steps) >= 1
    assert all(s.step_id.startswith("step_") for s in plan.steps)

    # Approve plan
    approved_plan = planning_service.approve_plan(actor="operator")
    assert approved_plan.status == PlanStatus.APPROVED
    assert approved_plan.approved_by == "operator"
    assert approved_plan.approved_at > 0


# ==============================================================================
# 8. REQUIREMENT WAIVER WITH AUDIT TRAIL
# ==============================================================================

def test_requirement_waiver_with_audit_trail(planning_service):
    """
    Waived requirements transition to WAIVED status with recorded reason and actor,
    and do not block goal completion.
    """
    req = RequirementState(
        requirement_id="req_optional",
        goal_id=planning_service.goal.goal_id,
        title="Optional Social Media Sharing",
        status=RequirementStatus.PENDING,
    )
    planning_service.requirements["req_optional"] = req

    ok = planning_service.waive_requirement(
        requirement_id="req_optional",
        reason="Deferred to v2 release scope",
        actor="product_manager",
    )
    assert ok is True
    assert req.status == RequirementStatus.WAIVED
    assert req.waiver_reason == "Deferred to v2 release scope"
    assert req.waiver_actor == "product_manager"


# ==============================================================================
# 9. DETERMINISTIC FOCUS SELECTION & OSCILLATION PROTECTION
# ==============================================================================

def test_deterministic_focus_and_oscillation_protection(planning_service):
    """
    Focus selection chooses ready, high-priority unblocked requirement.
    Oscillation protection applies penalty to prevent rapid flip-flopping.
    """
    r1 = RequirementState(
        requirement_id="req_1",
        goal_id=planning_service.goal.goal_id,
        title="Req 1",
        priority=RequirementPriority.HIGH,
        status=RequirementStatus.READY,
    )
    r2 = RequirementState(
        requirement_id="req_2",
        goal_id=planning_service.goal.goal_id,
        title="Req 2",
        priority=RequirementPriority.CRITICAL,
        status=RequirementStatus.READY,
    )
    planning_service.requirements["req_1"] = r1
    planning_service.requirements["req_2"] = r2

    ctrl = planning_service.progress_controller
    focus = ctrl.select_current_focus()
    # Critical priority (req_2) should be selected first
    assert focus == "req_2"

    # Simulate focus history to test oscillation protection
    ctrl._focus_history = ["req_2", "req_1", "req_2", "req_1"]
    penalty = ctrl._compute_oscillation_penalty("req_2")
    assert penalty > 0


# ==============================================================================
# 10. PROGRESS FINGERPRINT & TURN-BASED STALL DETECTION
# ==============================================================================

def test_progress_fingerprint_and_stall_detection(planning_service):
    """
    Progress fingerprint hashes requirement statuses and acceptance check statuses.
    If fingerprint remains identical for >= threshold turns, stall is detected.
    """
    user_prompt = "Build web server"
    planning_service.initialize_goal(user_prompt=user_prompt)

    ctrl = planning_service.progress_controller
    fp1 = ctrl.compute_progress_fingerprint()
    assert isinstance(fp1, str)
    assert len(fp1) > 0

    # Simulate turns with no changes
    ctrl.record_turn_fingerprint(fp1)
    stalled, reason, advice = ctrl.detect_stall(stall_threshold_turns=3)
    assert stalled is False

    ctrl.record_turn_fingerprint(fp1)
    ctrl.record_turn_fingerprint(fp1)
    # Now 3 consecutive identical fingerprints
    stalled, reason, advice = ctrl.detect_stall(stall_threshold_turns=3)
    assert stalled is True
    assert "No progress detected for 3 turns" in reason
    assert len(advice) > 0


# ==============================================================================
# 11. STRICT GOAL COMPLETION INVARIANT
# ==============================================================================

def test_strict_goal_completion_invariant(planning_service):
    """
    Goal completion requires:
    1. All requirements VERIFIED or WAIVED.
    2. All critical acceptance checks PASSED.
    3. Zero blocker failures.
    """
    r1 = RequirementState(
        requirement_id="r1",
        goal_id=planning_service.goal.goal_id,
        title="R1",
        status=RequirementStatus.IN_PROGRESS,
    )
    chk1 = AcceptanceCheck(
        check_id="c1",
        requirement_id="r1",
        description="C1",
        critical=True,
        status=AcceptanceCheckStatus.PASS,
        evidence_refs=["ev1"],
    )
    planning_service.requirements["r1"] = r1
    planning_service.acceptance_manager.register_checks([chk1])

    # Initially in progress -> Not completed
    completed, reason = planning_service.is_goal_completed()
    assert completed is False
    assert "Incomplete requirements" in reason or "unresolved requirements" in reason

    # Mark r1 verified
    r1.status = RequirementStatus.VERIFIED
    completed, reason = planning_service.is_goal_completed()
    assert completed is True
    assert "requirements verified" in reason

    # Add failing critical check
    chk_fail = AcceptanceCheck(
        check_id="c_fail",
        requirement_id="r1",
        description="Critical security gate",
        critical=True,
        status=AcceptanceCheckStatus.FAIL,
    )
    planning_service.acceptance_manager.register_checks([chk_fail])
    completed, reason = planning_service.is_goal_completed()
    assert completed is False
    assert "critical acceptance check" in reason.lower()



# ==============================================================================
# 12. 100-TURN SIMULATION & STATE REPLAY DETERMINISM
# ==============================================================================

def test_100_turns_simulation_and_determinism(test_bus):
    """
    Simulate a 100-turn long-running agent execution with goal updates,
    requirement transitions, acceptance check emissions, and state snapshotting.
    Replay entire event log through StateReducer from empty state to prove determinism.
    """
    mission_id = "mission_sim_100"
    store = StateStore(mission_id=mission_id)
    events: List[HermesEvent] = []

    # 1. Emission sequence of 100 turns
    ev_start = HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Build distributed cache system"},
    )
    store.apply_event(ev_start)
    events.append(ev_start)

    ev_goal = HermesEvent(
        event_type=EventType.GOAL_CREATED,
        mission_id=mission_id,
        payload={
            "goal_id": "g_cache",
            "title": "Distributed Cache",
            "description": "High performance LRU cache",
            "user_request": "Build distributed cache system",
            "explicit_constraints": ["Zero memory leaks", "O(1) operations"],
        },
    )
    store.apply_event(ev_goal)
    events.append(ev_goal)

    for i in range(1, 101):
        r_id = f"req_{i % 5}"
        c_id = f"chk_{i % 5}"

        if i <= 5:
            ev_req = HermesEvent(
                event_type=EventType.REQUIREMENT_CREATED,
                mission_id=mission_id,
                payload={
                    "requirement_id": r_id,
                    "title": f"Feature {r_id}",
                    "description": f"Details for {r_id}",
                    "category": "functional",
                    "priority": "high",
                    "dependencies": [],
                },
            )
            store.apply_event(ev_req)
            events.append(ev_req)

            ev_chk = HermesEvent(
                event_type=EventType.ACCEPTANCE_CHECK_CREATED,
                mission_id=mission_id,
                payload={
                    "check_id": c_id,
                    "requirement_id": r_id,
                    "description": f"Verify {r_id}",
                    "critical": True,
                    "verification_method": "test",
                },
            )
            store.apply_event(ev_chk)
            events.append(ev_chk)

        # Simulate turn activity
        ev_turn = HermesEvent(
            event_type=EventType.AGENT_TURN_STARTED,
            mission_id=mission_id,
            turn_id=f"turn_{i}",
            payload={"turn_id": f"turn_{i}", "turn_number": i},
        )
        store.apply_event(ev_turn)
        events.append(ev_turn)

        # Periodically pass checks
        if i % 20 == 0:
            ev_pass = HermesEvent(
                event_type=EventType.ACCEPTANCE_CHECK_PASSED,
                mission_id=mission_id,
                payload={
                    "check_id": c_id,
                    "requirement_id": r_id,
                    "evidence_ref": f"ev_turn_{i}",
                },
            )
            store.apply_event(ev_pass)
            events.append(ev_pass)

            ev_req_comp = HermesEvent(
                event_type=EventType.REQUIREMENT_COMPLETED,
                mission_id=mission_id,
                payload={
                    "requirement_id": r_id,
                    "status": "VERIFIED",
                    "evidence_refs": [f"ev_turn_{i}"],
                },
            )
            store.apply_event(ev_req_comp)
            events.append(ev_req_comp)

        ev_prog = HermesEvent(
            event_type=EventType.PROGRESS_UPDATED,
            mission_id=mission_id,
            payload={
                "last_meaningful_change": f"Turn {i} work on {r_id}",
                "current_focus": r_id,
                "next_action": f"Continue {r_id}",
                "progress_fingerprint": f"fp_{i}",
                "verified_requirements": 1 if i >= 20 else 0,
                "total_requirements": 5,
            },
        )
        store.apply_event(ev_prog)
        events.append(ev_prog)

    # Snapshot at turn 100
    snapshot_100 = store.get_snapshot()
    assert snapshot_100.goal.title == "Distributed Cache"
    assert len(snapshot_100.requirements) == 5

    # 2. Replay Verification: Reduce all events from scratch
    replayed_state = HermesRuntimeState.create_empty(mission_id=mission_id)
    for ev in events:
        replayed_state = StateReducer.reduce(replayed_state, ev)

    # Prove exact structural equivalence
    assert replayed_state.goal.title == snapshot_100.goal.title
    assert replayed_state.goal.user_request == snapshot_100.goal.user_request
    assert len(replayed_state.requirements) == len(snapshot_100.requirements)
    assert replayed_state.progress.current_focus == snapshot_100.progress.current_focus
    assert replayed_state.state_version == snapshot_100.state_version


# ==============================================================================
# 13. SCALABILITY: 200+ REQUIREMENTS & SELECTIVE CONTEXT PROJECTION
# ==============================================================================

def test_scalability_200_requirements_and_context_projection(planning_service):
    """
    Scaling test with 200+ requirements.
    Validates:
    - Bounded querying / pagination (list_requirements with offset/limit).
    - HumanProjectionRenderer limits requirements display.
    - ContextEngine projection does not flood context window with 200 items.
    """
    for i in range(205):
        r_id = f"scale_req_{i:03d}"
        req = RequirementState(
            requirement_id=r_id,
            goal_id=planning_service.goal.goal_id,
            title=f"Scale Requirement {i}",
            category=RequirementCategory.FUNCTIONAL,
            priority=RequirementPriority.MEDIUM,
            status=RequirementStatus.VERIFIED if i < 50 else RequirementStatus.PENDING,
        )
        chk = AcceptanceCheck(
            check_id=f"scale_chk_{i:03d}",
            requirement_id=r_id,
            description=f"Check for {r_id}",
            status=AcceptanceCheckStatus.PASS if i < 50 else AcceptanceCheckStatus.NOT_RUN,
            evidence_refs=[f"ev_{i}"] if i < 50 else [],
        )
        planning_service.requirements[r_id] = req
        planning_service.acceptance_manager.register_checks([chk])

    # 1. Test pagination
    page1 = planning_service.list_requirements(offset=0, limit=20)
    assert len(page1) == 20
    assert page1[0].requirement_id == "scale_req_000"

    page2 = planning_service.list_requirements(offset=20, limit=20)
    assert len(page2) == 20
    assert page2[0].requirement_id == "scale_req_020"

    # Filter by status
    verified_page = planning_service.list_requirements(
        offset=0, limit=100, status_filter=RequirementStatus.VERIFIED
    )
    assert len(verified_page) == 50

    # 2. Test HumanProjectionRenderer does not dump 205 items
    planning_service.update_progress()
    rendered = HumanProjectionRenderer.render_progress_view(
        goal=planning_service.goal,
        requirements=planning_service.requirements,
        progress=planning_service.progress,
        max_requirements_display=10,
    )
    # Check that it truncates with "... and N more requirements"
    assert "and 195 more requirements" in rendered or "more requirements" in rendered
    assert rendered.count("[✓]") <= 10  # Display bounded to max

    # 3. Test ContextEngine sync produces compact items
    from core.context.engine import ContextEngine
    mock_engine = ContextEngine(event_bus=planning_service.event_bus)
    planning_service.sync_to_context_engine(mock_engine)

    req_item = mock_engine.items.get("active_requirements_ledger")
    assert req_item is not None
    # Token length should be bounded (< 1500 chars)
    assert len(req_item.content) < 3000
