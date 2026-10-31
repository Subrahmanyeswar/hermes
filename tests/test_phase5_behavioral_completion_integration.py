"""
tests/test_phase5_behavioral_completion_integration.py
======================================================
HERMES Phase 5 Final Integration Gate:
Behavioral Failure -> Acceptance Ledger -> Completion Policy -> AgentLoop -> Mission Terminal State.

Verifies:
1. Gate A & B: Real FunctionalEvaluator failure propagates into AcceptanceLedger,
   CompletionPolicy, and the actual AgentLoop completion-candidate pathway, strictly
   rejecting completion (accepted=False, MISSION_COMPLETED suppressed, repair events emitted)
   even when structural syntax/files pass.
2. Gate B (Positive Control): Behavioral pass allows AgentLoop completion candidate acceptance
   (accepted=True, MISSION_COMPLETED emitted, reducer transitions to COMPLETED).
3. Gate C: Terminal-state protection, repair budget cap, and event integrity (no false MISSION_COMPLETED).
4. Gate D: Accurate identification of SimulatedBrowserDriver in prior tests, and real-browser
   CDP execution using CdpBrowserDriver against live DevServer.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest
import httpx
import websockets

from core.evaluation.functional.evaluator import FunctionalEvaluator
from core.evaluation.functional.models import (
    CheckLayer,
    CheckStatus,
    FunctionalCheck,
    FunctionalRequirement,
)
from core.agent_loop.completion import CompletionPolicy, GoalCompleteGuard
from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.event_bus import EventBus
from core.runtime_state.store import StateStore
from core.mission_planner import Mission
from models.provider import NormalizedModelResponse
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    FailureClass,
    HermesRuntimeState,
    MissionState,
    MissionStatus,
)
from core.repair import RepairController
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.reducer import StateReducer
from core.workspace import WorkspaceManager
from core.browser.manager import BrowserManager, CdpBrowserDriver, SimulatedBrowserDriver
from core.browser.dev_server import DevServerManager


@pytest.mark.asyncio
async def test_gate_b_behavioral_failure_propagates_to_completion_rejection(tmp_path: Path):
    """
    GATE B Negative Integration Test:
    - Syntactically valid implementation exists physically in workspace.
    - Real FunctionalEvaluator executes a test harness behavioral check.
    - The check FAILS (assertion failure: 2 + 2 != 5).
    - Failure propagates into AcceptanceLedger.
    - CompletionPolicy evaluates the state and REJECTS completion (accepted=False).
    - Unmet reasons accurately identify the failing acceptance check.
    - The real AgentLoop processes the completion candidate:
      * Suppresses EventType.MISSION_COMPLETED
      * Emits EventType.AGENT_COMPLETION_CANDIDATE
      * Emits EventType.VERIFICATION_NEEDS_IMPROVEMENT
      * Emits EventType.AGENT_REPAIR_REQUESTED
    - Applying events through StateReducer ensures mission is NOT MissionStatus.COMPLETED.
    - Structural presence does not override behavioral failure.
    """
    workspace_dir = tmp_path / "behavioral_fail_workspace"
    workspace_dir.mkdir()

    # 1. Physical source files with valid syntax but incorrect behavior
    calc_py = """def add(a, b):
    # Intentional bug: returns wrong sum
    return a + b + 1
"""
    test_py = """import sys
from calc import add

res = add(2, 2)
assert res == 4, f"AssertionError: Expected 4, got {res}"
"""
    (workspace_dir / "calc.py").write_text(calc_py, encoding="utf-8")
    (workspace_dir / "test_calc.py").write_text(test_py, encoding="utf-8")

    # 2. Run REAL FunctionalEvaluator
    fe = FunctionalEvaluator(workspace_root=workspace_dir)
    chk_test = FunctionalCheck(
        check_id="chk_calc_behavior",
        name="Addition Correctness Test",
        layer=CheckLayer.TESTS,
        expected=f'"{sys.executable}" test_calc.py',
    )
    req = FunctionalRequirement(
        req_id="req_calc_math",
        title="Mathematical Correctness",
        checks=[chk_test],
    )

    res = await fe.evaluate_suite(task_id="task_calc_01", requirements=[req])

    # Assert real evaluator executed and produced controlled failure
    assert res.status == CheckStatus.FAIL, "Evaluator must report FAIL for defective behavior"
    assert chk_test.status == CheckStatus.FAIL
    assert "AssertionError" in chk_test.actual

    # 3. Connect evaluator result into AcceptanceLedger (Production Dataflow)
    acc_check = AcceptanceCheck(
        check_id=chk_test.check_id,
        requirement_id=req.req_id,
        description=chk_test.name,
        verification_method="TESTS",
        status=AcceptanceCheckStatus.FAIL,
        error_message=chk_test.actual[:200],
    )
    ledger = AcceptanceLedger(
        goal_id="goal_calc",
        checks={acc_check.check_id: acc_check},
        requirement_checks={req.req_id: [acc_check.check_id]},
    )

    # 4. Evaluate CompletionPolicy directly with this real failure
    wm = WorkspaceManager()
    wm.lock(workspace_dir)

    runtime_state = HermesRuntimeState(
        mission=MissionState(mission_id="mission_calc_fail", status=MissionStatus.RUNNING),
        acceptance_ledger=ledger,
    )

    policy = CompletionPolicy()
    accepted, reason, unmet = policy.evaluate_completion(
        mission_prompt="Implement calculator with passing unit tests",
        workspace=wm,
        runtime_state=runtime_state,
        acceptance_ledger=ledger,
        written_files=["calc.py", "test_calc.py"],
        strict_requirements=True,
    )

    # Assert completion is strictly REJECTED
    assert accepted is False, "CompletionPolicy must NOT approve completion when behavioral check fails"
    assert any("chk_calc_behavior" in u for u in unmet)
    assert "FAILED" in reason or any("FAILED" in u for u in unmet)

    # Verify GoalCompleteGuard directly rejects
    guard_ok, guard_reason, guard_unmet = GoalCompleteGuard.evaluate(
        state=runtime_state,
        ledger=ledger,
        strict_requirements=True,
    )
    assert guard_ok is False
    assert any("chk_calc_behavior has FAILED" in u for u in guard_unmet)

    # 5. Drive the real AgentLoop completion-candidate pathway
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))
    state_store = StateStore(mission_id="mission_calc_fail")
    state_store.get_state().acceptance_ledger = ledger

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    async def mock_gen(*args, **kwargs):
        return NormalizedModelResponse(
            text="I have finished the calculator completely. All tasks done.",
            tool_calls=[]
        )
    mock_orch._generate_t1 = mock_gen

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=wm,
        event_bus_instance=bus,
        state_store_instance=state_store,
        config=AgentLoopConfig(max_turns=1),
    )
    loop._written_files = ["calc.py", "test_calc.py"]

    mission = Mission(
        mission_id="mission_calc_fail",
        user_prompt="Implement calculator with passing unit tests",
        acceptance_criteria=[chk_test.name],
    )

    loop_res = await loop.run(mission)
    assert loop_res.success is False
    assert loop_res.status != "COMPLETED"

    emitted_types = [e.event_type for e in events]
    assert EventType.AGENT_COMPLETION_CANDIDATE in emitted_types
    assert EventType.VERIFICATION_NEEDS_IMPROVEMENT in emitted_types
    assert EventType.AGENT_REPAIR_REQUESTED in emitted_types
    assert EventType.MISSION_COMPLETED not in emitted_types

    # Reducer verification: state never becomes COMPLETED
    reduced_state = HermesRuntimeState(
        mission=MissionState(mission_id="mission_calc_fail", status=MissionStatus.RUNNING)
    )
    for evt in events:
        reduced_state = StateReducer.reduce(reduced_state, evt)
    assert reduced_state.mission.status != MissionStatus.COMPLETED


@pytest.mark.asyncio
async def test_gate_b_positive_control_allows_completion(tmp_path: Path):
    """
    GATE B Positive Control:
    - Same workspace structure, but implementation is corrected.
    - Real FunctionalEvaluator executes test harness and PASSES.
    - AcceptanceLedger marks check as PASS.
    - CompletionPolicy approves completion (accepted=True).
    - Real AgentLoop approves completion candidate:
      * Emits EventType.AGENT_COMPLETION_CANDIDATE
      * Emits EventType.VERIFICATION_COMPLETED
      * Emits EventType.MISSION_COMPLETED
    - Applying events through StateReducer transitions mission to MissionStatus.COMPLETED.
    """
    workspace_dir = tmp_path / "behavioral_pass_workspace"
    workspace_dir.mkdir()

    # Corrected math
    calc_py = """def add(a, b):
    return a + b
"""
    test_py = """import sys
from calc import add

res = add(2, 2)
assert res == 4, f"AssertionError: Expected 4, got {res}"
"""
    (workspace_dir / "calc.py").write_text(calc_py, encoding="utf-8")
    (workspace_dir / "test_calc.py").write_text(test_py, encoding="utf-8")

    fe = FunctionalEvaluator(workspace_root=workspace_dir)
    chk_test = FunctionalCheck(
        check_id="chk_calc_pass",
        name="Addition Correctness Test",
        layer=CheckLayer.TESTS,
        expected=f'"{sys.executable}" test_calc.py',
    )
    req = FunctionalRequirement(
        req_id="req_calc_math_pass",
        title="Mathematical Correctness",
        checks=[chk_test],
    )

    res = await fe.evaluate_suite(task_id="task_calc_02", requirements=[req])
    assert res.status == CheckStatus.PASS
    assert chk_test.status == CheckStatus.PASS

    acc_check = AcceptanceCheck(
        check_id=chk_test.check_id,
        requirement_id=req.req_id,
        description=chk_test.name,
        verification_method="TESTS",
        status=AcceptanceCheckStatus.PASS,
    )
    ledger = AcceptanceLedger(
        goal_id="goal_calc",
        checks={acc_check.check_id: acc_check},
        requirement_checks={req.req_id: [acc_check.check_id]},
    )

    wm = WorkspaceManager()
    wm.lock(workspace_dir)

    runtime_state = HermesRuntimeState(
        mission=MissionState(mission_id="mission_calc_pass", status=MissionStatus.RUNNING),
        acceptance_ledger=ledger,
    )

    policy = CompletionPolicy()
    accepted, reason, unmet = policy.evaluate_completion(
        mission_prompt="Implement calculator with passing unit tests",
        workspace=wm,
        runtime_state=runtime_state,
        acceptance_ledger=ledger,
        written_files=["calc.py", "test_calc.py"],
        strict_requirements=False,
    )

    assert accepted is True, f"CompletionPolicy must approve valid passing implementation. Reason: {reason}"
    assert len(unmet) == 0

    # Drive real AgentLoop completion candidate pathway for positive control
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))
    state_store = StateStore(mission_id="mission_calc_pass")
    state_store.get_state().acceptance_ledger = ledger

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    async def mock_gen(*args, **kwargs):
        return NormalizedModelResponse(
            text="I have finished the calculator. Everything is verified.",
            tool_calls=[]
        )
    mock_orch._generate_t1 = mock_gen

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=wm,
        event_bus_instance=bus,
        state_store_instance=state_store,
        config=AgentLoopConfig(max_turns=2),
    )
    loop._written_files = ["calc.py", "test_calc.py"]

    mission = Mission(
        mission_id="mission_calc_pass",
        user_prompt="Write a python script calc.py",
    )

    loop_res = await loop.run(mission)
    assert loop_res.success is True
    assert loop_res.status == "COMPLETED"

    emitted_types = [e.event_type for e in events]
    assert EventType.AGENT_COMPLETION_CANDIDATE in emitted_types
    assert EventType.VERIFICATION_COMPLETED in emitted_types
    assert EventType.MISSION_COMPLETED in emitted_types

    # Reducer verification: status becomes COMPLETED
    reduced_state = HermesRuntimeState(
        mission=MissionState(mission_id="mission_calc_pass", status=MissionStatus.RUNNING)
    )
    for evt in events:
        reduced_state = StateReducer.reduce(reduced_state, evt)
    assert reduced_state.mission.status == MissionStatus.COMPLETED


@pytest.mark.asyncio
async def test_gate_c_terminal_state_protection_and_repair_budget():
    """
    GATE C:
    - Verifies that rejection emits VERIFICATION_NEEDS_IMPROVEMENT / AGENT_REPAIR_REQUESTED.
    - State reducer does NOT transition to MissionStatus.COMPLETED.
    - RepairController bounds retry attempts strictly (capped budget).
    - When budget is exhausted, can_retry is False and mission cannot be marked completed.
    """
    state = HermesRuntimeState(
        mission=MissionState(mission_id="test_term_01", status=MissionStatus.RUNNING)
    )

    # 1. State reducer on VERIFICATION_NEEDS_IMPROVEMENT
    event_needs_imp = HermesEvent(
        event_id="evt_01",
        mission_id="test_term_01",
        timestamp=100.0,
        event_type=EventType.VERIFICATION_NEEDS_IMPROVEMENT,
        payload={"verdict": "NEEDS_IMPROVEMENT", "issues": ["Assertion failure in test_calc.py"]},
    )
    state = StateReducer.reduce(state, event_needs_imp)
    assert state.mission.status == MissionStatus.RUNNING
    assert state.mission.status != MissionStatus.COMPLETED

    # 2. RepairController bounded retry enforcement
    repair_ctrl = RepairController()
    repair_ctrl.mission_id = "test_term_01"

    # Attempt 1
    can_retry1, guidance1, rep_id1 = repair_ctrl.handle_failure(
        check_id="chk_calc_behavior",
        failure_class=FailureClass.ASSERTION_FAILED,
        error_message="Expected 4, got 5",
        task_id="turn_1",
    )
    assert can_retry1 is True
    assert rep_id1 is not None

    # Attempt 2
    can_retry2, guidance2, rep_id2 = repair_ctrl.handle_failure(
        check_id="chk_calc_behavior",
        failure_class=FailureClass.ASSERTION_FAILED,
        error_message="Expected 4, got 5",
        task_id="turn_2",
    )
    # Consecutive identical failure fingerprint triggers immediate stall detection
    assert can_retry2 is False, "Identical consecutive failure must trigger stall / can_retry=False"

    # Verify that MISSION_COMPLETED event is rejected if mission was aborted/failed
    event_failed = HermesEvent(
        event_id="evt_fail",
        mission_id="test_term_01",
        timestamp=105.0,
        event_type=EventType.MISSION_FAILED,
        payload={"error": "Exhausted repair budget on behavioral failure"},
    )
    state = StateReducer.reduce(state, event_failed)
    assert state.mission.status == MissionStatus.FAILED

    # Terminal state immutability: late MISSION_COMPLETED cannot overwrite FAILED
    late_completed = HermesEvent(
        event_id="evt_late",
        mission_id="test_term_01",
        timestamp=110.0,
        event_type=EventType.MISSION_COMPLETED,
        payload={"reason": "Late completed event"},
    )
    state = StateReducer.reduce(state, late_completed)
    assert state.mission.status == MissionStatus.FAILED, "Terminal state FAILED must be immutable"


def test_gate_d_audit_existing_test_used_simulated_browser():
    """
    GATE D Identification:
    Inspects tests/test_phase5_behavioral_acceptance.py and proves that
    the existing web test explicitly instantiated SimulatedBrowserDriver.
    """
    target_file = Path("tests/test_phase5_behavioral_acceptance.py")
    assert target_file.exists(), "test_phase5_behavioral_acceptance.py must exist"
    code = target_file.read_text(encoding="utf-8")

    assert "sim_driver = SimulatedBrowserDriver()" in code, (
        "Evidence confirms test_phase5_behavioral_acceptance.py explicitly instantiates SimulatedBrowserDriver"
    )
    assert "bm.driver = sim_driver" in code, (
        "Evidence confirms SimulatedBrowserDriver was assigned directly to BrowserManager"
    )


@pytest.mark.asyncio
async def test_gate_d_real_browser_cdp_execution(tmp_path: Path):
    """
    GATE D Real Browser Verification:
    Executes a real headless Chromium/Edge browser instance via CdpBrowserDriver,
    navigates to a live DevServer, evaluates a DOM click event over the CDP WebSocket,
    and observes real DOM mutation.
    """
    workspace = tmp_path / "cdp_web_workspace"
    workspace.mkdir()

    html = """<!DOCTYPE html>
<html>
<head><title>CDP Integration App</title></head>
<body>
    <div id="status">Initial</div>
    <button id="action-btn" onclick="document.getElementById('status').textContent = 'Mutated via CDP'">Click Me</button>
</body>
</html>"""
    (workspace / "index.html").write_text(html, encoding="utf-8")

    dsm = DevServerManager()
    server_info = await dsm.start_static_server(workspace)
    assert server_info.is_alive
    assert server_info.port > 0

    bm = BrowserManager(prefer_cdp=True)
    launched = await bm.launch(headless=True)

    try:
        assert launched is True, "Browser launch must succeed"
        assert isinstance(bm.driver, CdpBrowserDriver), (
            f"Expected CdpBrowserDriver, got {bm.driver.__class__.__name__}"
        )

        nav = await bm.navigate(f"{server_info.url}/index.html")
        assert nav.success is True
        assert server_info.url in nav.url

        # Interact via real CDP WebSocket DevTools Protocol
        cdp_port = bm.driver.port
        assert cdp_port is not None and cdp_port > 0

        async with httpx.AsyncClient(timeout=5.0) as client:
            targets_resp = await client.get(f"http://127.0.0.1:{cdp_port}/json")
            assert targets_resp.status_code == 200
            targets = targets_resp.json()
            page_target = next(
                t for t in targets if t.get("type") == "page" and server_info.url in t.get("url", "")
            )
            ws_url = page_target.get("webSocketDebuggerUrl")
            assert ws_url is not None

            async with websockets.connect(ws_url) as ws:
                # Verify initial title via Runtime.evaluate
                await ws.send(json.dumps({
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "document.title"}
                }))
                title_resp = json.loads(await ws.recv())
                assert title_resp.get("result", {}).get("result", {}).get("value") == "CDP Integration App"

                # Trigger click via Runtime.evaluate
                await ws.send(json.dumps({
                    "id": 2,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "document.getElementById('action-btn').click()"}
                }))
                click_resp = json.loads(await ws.recv())
                assert "result" in click_resp

                # Read updated DOM text content
                await ws.send(json.dumps({
                    "id": 3,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "document.getElementById('status').textContent"}
                }))
                eval_resp = json.loads(await ws.recv())
                mutated_value = eval_resp.get("result", {}).get("result", {}).get("value")
                assert mutated_value == "Mutated via CDP", (
                    f"Expected 'Mutated via CDP', got {mutated_value}"
                )

    finally:
        await bm.close()
        dsm.stop_all()
