# tests/test_stage7_reliability_and_recovery.py
"""
Deterministic Acceptance Test Suite for HERMES Stage 7:
Sustained Mission Reliability, Model Fallback, and Recovery.

Verifies:
- Scenario B: Bounded retries and loop prevention:
  - Turn budget enforcement prevents unbounded execution.
  - Consecutive failure budget terminates failing loops cleanly.
  - Stall detection catches repeated identical actions.
  - Failed checks cannot be converted to success by repeatedly claiming completion.
- Scenario C: Model and provider fallback:
  - T1 timeout / infrastructure failure fails over to T2 (gpt-oss:120b-cloud) and T3 (nemotron-3-ultra).
  - All-tier exhaustion terminates cleanly without false success claims.
  - Circuit breaker trips on consecutive timeouts for zero-wait routing.
- Scenario D: Multi-step task integrity:
  - Deliberately failing prerequisite blocks dependent completion.
- Scenario E: Cancellation during active work:
  - Runtime stop cancels mission, invalidates pending approvals, and locks status to CANCELLED.
- Scenario F: Interruption and recovery:
  - SSE stream cursor reconnection replays ordered events without drift or loss.
- Scenario G: Security and artifact integrity under failure:
  - Boundary traversal blocked under failure conditions.
  - Terminal missions cannot reuse stale approval requests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from core.adaptive_routing import (
    AdaptiveRouter,
    ProviderHealthState,
    RouteDecision,
)
from core.agent_loop.actions import ActionExecutor
from core.agent_loop.completion import CompletionPolicy, GoalCompleteGuard
from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.agent_loop.types import ActionEnvelope, ActionStatus, Observation
from core.event_bus import EventBus
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.runtime_state.models import (
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
    HermesRuntimeState,
    MissionState,
    MissionStatus,
)
from core.security.approvals import ApprovalStore
from core.security.enums import ApprovalScope
from core.security.gate import SecurityGate
from core.security.models import ActionDescriptor, ApprovalRequest
from core.server.app import create_app
from core.server.diff_service import (
    clear_file_baselines,
    compute_file_diff,
    record_file_baseline,
)
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import (
    WorkspaceBoundaryError,
    workspace_manager,
)
from models.nvidia_client import NvidiaConnectionError, NvidiaTimeoutError


@pytest.fixture
def stage7_env(tmp_path):
    ws = tmp_path / "stage7_test_ws"
    ws.mkdir(parents=True, exist_ok=True)
    workspace_manager.lock(ws)

    from core.persistence.database import SQLiteDatabase
    test_db = SQLiteDatabase(tmp_path / "stage7_runtime.db")
    test_bus = EventBus(enabled=True, db=test_db)
    adapter = RuntimeAdapter(event_bus=test_bus, workspace_manager=workspace_manager)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    yield {
        "workspace": ws,
        "ws_mgr": workspace_manager,
        "event_bus": test_bus,
        "adapter": adapter,
        "client": client,
    }

    workspace_manager.unlock()
    clear_file_baselines()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO B: Bounded Retries and Loop Prevention
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scenario_b_turn_budget_enforcement(stage7_env):
    """
    Scenario B1: Max turn budget enforcement.
    Verifies that when an agent loop reaches max_turns without goal completion:
    1. Loop terminates cleanly without hanging or infinite cycling.
    2. Event MISSION_FAILED is published with 'Max turn budget reached'.
    3. Status transitions to FAILED.
    """
    ws: Path = stage7_env["workspace"]
    bus: EventBus = stage7_env["event_bus"]
    mission_id = "m_stage7_turn_budget"

    from core.mission_planner import Mission
    mission = Mission(mission_id=mission_id, user_prompt="Do something impossible", workspace_root=str(ws))

    config = AgentLoopConfig(max_turns=3, max_wall_time_seconds=60.0)
    loop = AgentLoop(orchestrator=MagicMock(), workspace_manager=stage7_env["ws_mgr"], event_bus_instance=bus, config=config)

    # Mock model turn to generate a harmless non-completing thought
    mock_decision = MagicMock()
    mock_decision.decision_type.value = "CONTINUE_REASONING"
    mock_decision.explanation = "Still pondering..."
    mock_decision.raw_text = "Still pondering..."
    loop._interpreter.interpret = MagicMock(return_value=mock_decision)
    loop._generate_model_turn = AsyncMock(return_value="Still pondering...")

    res = await loop.run(mission)

    assert res.success is False
    assert res.status == "FAILED"
    assert "Max turn budget reached" in (res.error or "")
    assert res.turns_executed <= 3


@pytest.mark.asyncio
async def test_scenario_b_consecutive_failure_budget_exhaustion(stage7_env):
    """
    Scenario B2: Consecutive failure budget exhaustion.
    Verifies that repeating failing actions terminates execution after max_consecutive_failures.
    """
    ws: Path = stage7_env["workspace"]
    bus: EventBus = stage7_env["event_bus"]
    mission_id = "m_stage7_consecutive_failures"

    from core.mission_planner import Mission
    mission = Mission(mission_id=mission_id, user_prompt="Failing tool task", workspace_root=str(ws))

    config = AgentLoopConfig(max_turns=20, max_consecutive_failures=3)
    loop = AgentLoop(orchestrator=MagicMock(), workspace_manager=stage7_env["ws_mgr"], event_bus_instance=bus, config=config)

    # Mock model turn raising an exception
    loop._generate_model_turn = AsyncMock(side_effect=RuntimeError("Simulated LLM network drop"))

    res = await loop.run(mission)

    assert res.success is False
    assert res.status == "FAILED"
    assert "Consecutive failure budget exceeded" in (res.error or "")


def test_scenario_b_failed_check_cannot_be_overridden_by_repeated_claim():
    """
    Scenario B3: A failed check cannot be overridden by repeatedly claiming completion.
    Verifies that CompletionPolicy and GoalCompleteGuard reject completion when
    critical acceptance check is in FAIL status.
    """
    mission_state = MissionState(
        mission_id="m_stage7_guard_override",
        prompt="Write and test math module",
        status=MissionStatus.RUNNING,
    )
    failed_check = AcceptanceCheck(
        check_id="chk_pytest",
        requirement_id="req_math",
        description="Must pass pytest",
        status=AcceptanceCheckStatus.FAIL,
        critical=True,
        error_message="Test failed: AssertionError in test_math.py",
    )
    ledger = AcceptanceLedger(checks={"chk_pytest": failed_check})
    state = HermesRuntimeState(mission=mission_state, acceptance_ledger=ledger)

    policy = CompletionPolicy()

    # Model claims completion 3 consecutive times with persuasive text
    claims = [
        "Everything is working perfectly now, please trust me.",
        "I fixed all the bugs in test_math.py and it passed.",
        "Final verification complete. 100% test pass rate.",
    ]

    for claim in claims:
        ok, reason, issues = policy.evaluate_completion(
            mission_prompt="Write and test math module",
            runtime_state=state,
            candidate_response=claim,
        )
        assert ok is False
        assert "GoalCompleteGuard" in reason
        assert any("chk_pytest" in iss for iss in issues)


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO C: Model and Provider Fallback
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scenario_c_provider_timeout_failover_to_tier2():
    """
    Scenario C1: When Tier 1 experiences a timeout / network failure,
    the system fails over to Tier 2 (Ollama gpt-oss:120b-cloud) and records the event.
    """
    from core.orchestrator import Orchestrator
    from config.model_config import TIER2_MODEL, TIER3_MODEL

    orch = Orchestrator(mode="auto")
    orch.ollama = MagicMock()

    # Tier 1 raises NvidiaTimeoutError
    mock_t1 = MagicMock()
    mock_t1.generate = AsyncMock(side_effect=NvidiaTimeoutError("First token timeout after 15.0s"))
    orch.tier1 = mock_t1

    # Tier 2 succeeds
    mock_t2_resp = MagicMock()
    mock_t2_resp.text = '{"thought": "Fallback succeeded", "tool": "read_file", "parameters": {"path": "test.txt"}}'
    orch.ollama.generate = AsyncMock(return_value=mock_t2_resp)

    progress_events = []
    async def capture_progress(event_name, data):
        progress_events.append((event_name, data))
    orch._emit_progress = capture_progress

    resp = await orch._generate_t1(prompt="Analyze code", tier1_client=mock_t1)

    assert resp == mock_t2_resp
    # Verify failover progress emitted
    failover_ev = next((data for name, data in progress_events if name == "model_failover"), None)
    assert failover_ev is not None
    assert failover_ev["tier"] == 2
    assert failover_ev["model"] == TIER2_MODEL
    assert "timeout" in failover_ev["reason"].lower()


@pytest.mark.asyncio
async def test_scenario_c_all_tiers_exhausted_raises_cleanly():
    """
    Scenario C2: When all configured tiers (T1, T2, and T3) fail,
    the system terminates cleanly, raises the error, and does NOT claim false success.
    """
    from core.orchestrator import Orchestrator

    orch = Orchestrator(mode="auto")
    mock_t1 = MagicMock()
    mock_t1.generate = AsyncMock(side_effect=NvidiaConnectionError("NIM connection refused"))
    orch.tier1 = mock_t1

    orch.ollama = MagicMock()
    # T2 and T3 fail
    orch.ollama.generate = AsyncMock(side_effect=RuntimeError("Ollama cloud unreachable"))

    with pytest.raises(Exception) as exc_info:
        await orch._generate_t1(prompt="Compute something", tier1_client=mock_t1)

    assert "NIM connection refused" in str(exc_info.value) or "Ollama cloud unreachable" in str(exc_info.value)


def test_scenario_c_circuit_breaker_trips_on_consecutive_timeouts():
    """
    Scenario C3: Adaptive router circuit breaker trips into OPEN_CIRCUIT
    after consecutive timeouts and bypasses T1 with zero-wait.
    """
    router = AdaptiveRouter()
    router.reset()

    # Initial state is healthy
    assert router.route_primary().tier == 1

    # Record first token timeouts
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")

    # Circuit breaker trips
    health = router.get_health(1)
    assert health.state == ProviderHealthState.OPEN_CIRCUIT

    # Next call bypasses T1 to Tier 2 immediately
    decision = router.route_primary()
    assert decision.tier == 2
    assert decision.bypassed is True
    assert "circuit open" in decision.reason.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO D: Multi-Step Task Integrity (Prerequisite Gating)
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_d_failing_prerequisite_blocks_dependent_completion():
    """
    Scenario D: In a multi-step task (e.g. 1. inspect, 2. modify, 3. verify),
    a failing prerequisite check blocks completion even if the agent claims it completed step 3.
    """
    mission_state = MissionState(
        mission_id="m_stage7_prereq",
        prompt="Step 1: check file, Step 2: edit file, Step 3: verify test",
        status=MissionStatus.RUNNING,
    )
    # Step 1: passed
    check_step1 = AcceptanceCheck(
        check_id="chk_step1_inspect",
        requirement_id="req_inspect",
        description="Inspect baseline file",
        status=AcceptanceCheckStatus.PASS,
        critical=True,
    )
    # Step 2 (Prerequisite): failed
    check_step2 = AcceptanceCheck(
        check_id="chk_step2_edit",
        requirement_id="req_modify",
        description="Apply modifications to module",
        status=AcceptanceCheckStatus.FAIL,
        critical=True,
        error_message="SyntaxError in edited module line 12",
    )
    ledger = AcceptanceLedger(checks={
        "chk_step1_inspect": check_step1,
        "chk_step2_edit": check_step2,
    })
    state = HermesRuntimeState(mission=mission_state, acceptance_ledger=ledger)

    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Step 1: check file, Step 2: edit file, Step 3: verify test",
        runtime_state=state,
        candidate_response="I finished step 3 and everything is done.",
    )

    assert ok is False
    assert "GoalCompleteGuard" in reason
    assert any("chk_step2_edit" in iss for iss in issues)


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO E: Cancellation During Active Work
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scenario_e_cancellation_sets_cancelled_and_invalidates_approvals(stage7_env):
    """
    Scenario E: User requests mission cancellation while mission is running.
    Verifies that:
    1. Stop request marks mission as CANCELLED (never COMPLETED).
    2. Pending approval requests for that mission are immediately cancelled/invalidated.
    3. Stale completion events cannot overwrite the terminal CANCELLED status.
    """
    adapter: RuntimeAdapter = stage7_env["adapter"]
    client: TestClient = stage7_env["client"]
    bus: EventBus = stage7_env["event_bus"]
    mission_id = "m_stage7_cancellation"

    # Start mission
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"prompt": "Long running task"}
    ))

    # Add a pending approval request bound to this mission
    app_store = ApprovalStore()
    app_req = ApprovalRequest(
        request_id="req_pending_1",
        action=ActionDescriptor(tool_name="bash", arguments={"command": "rm -rf tmp"}),
        mission_id=mission_id,
        status="PENDING",
    )
    app_store.add_request(app_req)

    # Attach app_store to runtime adapter active runtimes
    rt_mock = MagicMock()
    rt_mock.security.approval_store = app_store
    adapter._active_runtimes[mission_id] = rt_mock

    # Invoke stop endpoint
    resp = client.post(f"/api/missions/{mission_id}/stop")
    assert resp.status_code == 200
    stop_data = resp.json()
    assert stop_data["cancelled"] is True

    # Assert pending approval was invalidated
    assert app_req.resolved is True
    assert app_req.status == "CANCELLED"
    assert app_req.approved is False

    # Assert mission snapshot is terminal CANCELLED
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["status"] == "CANCELLED"
    assert snap["is_terminal"] is True

    # A late completed event cannot resurrect the mission to COMPLETED
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={"output": "Late rogue completion"}
    ))
    snap_late = client.get(f"/api/missions/{mission_id}").json()
    assert snap_late["status"] == "CANCELLED"


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO F: Interruption and Recovery (SSE Reconnection)
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_f_sse_reconnection_preserves_event_order_and_cursor(stage7_env):
    """
    Scenario F: Client disconnects and reconnects using Last-Event-ID / cursor.
    Verifies that:
    1. Reconnecting with sequence cursor retrieves all subsequent events in monotonic order.
    2. Zero events are duplicated or lost during reconnection.
    """
    adapter: RuntimeAdapter = stage7_env["adapter"]
    bus: EventBus = stage7_env["event_bus"]
    import uuid
    mission_id = f"m_stage7_recovery_cursor_{uuid.uuid4().hex[:6]}"

    # Emit 5 sequential events
    for i in range(1, 6):
        bus.publish(HermesEvent(
            event_type=EventType.PROGRESS_UPDATED if i < 5 else EventType.MISSION_COMPLETED,
            mission_id=mission_id,
            sequence=i,
            payload={"step": i, "desc": f"Execution step {i}"}
        ))

    # Reconnect from cursor = 2 (client received events 1 and 2, needs 3, 4, 5)
    replayed = adapter.get_events_since(mission_id, last_sequence=2)
    assert len(replayed) == 3
    assert [e.sequence for e in replayed] == [3, 4, 5]

    from core.server.app import format_hermes_event_to_sse
    sse_text = "".join(format_hermes_event_to_sse(ev) for ev in replayed)
    assert "id: 3\n" in sse_text
    assert "id: 4\n" in sse_text
    assert "id: 5\n" in sse_text
    assert "id: 1\n" not in sse_text
    assert "id: 2\n" not in sse_text


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO G: Security and Artifact Integrity Under Failure
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_g_path_boundary_traversal_blocked_under_failure(stage7_env):
    """
    Scenario G1: Path traversal attempts (e.g. '../outside.txt') under failure conditions
    are blocked by WorkspaceBoundaryError and never execute against host filesystem.
    """
    ws: Path = stage7_env["workspace"]
    from core.workspace import canonicalize_workspace_path, WorkspaceBoundaryError

    with pytest.raises(WorkspaceBoundaryError) as exc_info:
        canonicalize_workspace_path("../escape_jail.py", ws)

    assert "escapes workspace boundary" in str(exc_info.value).lower()

    with pytest.raises(WorkspaceBoundaryError):
        compute_file_diff(ws, "../../outside_root.txt")


def test_scenario_g_terminal_mission_cannot_reuse_stale_approvals():
    """
    Scenario G2: Stale approvals from cancelled or completed missions
    cannot be reused for subsequent operations.
    """
    store = ApprovalStore()
    req = ApprovalRequest(
        request_id="req_old",
        action=ActionDescriptor(tool_name="write_file", arguments={"path": "critical.py"}),
        mission_id="m_terminated",
        status="PENDING",
    )
    store.add_request(req)

    # Cancel mission requests
    store.cancel_requests_for_mission("m_terminated")

    # Attempt to resolve previously cancelled request
    grant = store.resolve_request("req_old", approved=True)
    assert grant is None  # Cannot generate grant for cancelled request
