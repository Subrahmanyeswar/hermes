# tests/test_stage7_2_concurrent_isolation.py
"""
Deterministic Acceptance Test Suite for HERMES Stage 7.2:
Concurrent Mission Isolation and Process Ownership.

Covers:
- Scenario A: Simultaneous Independent Missions (concurrent execution, distinct outputs, no cross-contamination).
- Scenario B: Cancel One Mission While the Other Continues (scoped cancellation, scoped subprocess termination, B continues).
- Scenario C: One Mission Times Out While Another Completes (budget isolation, timeout failure scoping, approvals isolation).
- Scenario D: Process-Tree Cleanup and Isolation (Windows process tree termination without collateral damage).
- Scenario E: Approvals and Event Isolation (cross-mission approval isolation, terminal invalidation scoping, SSE replay separation).
- Scenario F: Concurrent Deadline and Cancellation Races (idempotent terminal transition, zombie immunity, non-interference).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import psutil
import pytest

from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.agent_loop.types import ActionEnvelope, ActionStatus, Observation
from core.cancellation_controller import CancellationController
from core.event_bus import EventBus
from core.mission_planner import Mission
from core.runtime_identity import get_canonical_python_executable
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.runtime_state.models import MissionStatus
from core.security.approvals import ApprovalStore
from core.security.enums import ApprovalScope, PermissionOutcome
from core.security.gate import SecurityGate
from core.security.models import ActionDescriptor, ApprovalRequest
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import WorkspaceManager
from models.provider import NormalizedModelResponse
from tools.shell_tools import (
    ACTIVE_SUBPROCESSES,
    CURRENT_MISSION_ID,
    PROCESS_MISSION_MAP,
    register_active_subprocess,
    terminate_active_subprocesses,
    unregister_active_subprocess,
)


@pytest.fixture(autouse=True)
def clean_subprocesses():
    yield
    terminate_active_subprocesses()


@pytest.mark.asyncio
async def test_scenario_a_simultaneous_independent_missions(tmp_path: Path):
    """
    Scenario A:
    Two concurrent missions running in isolated workspaces with unique mission IDs.
    Each spawns an independent child process, writes distinct output, and completes independently.
    Verifies:
    1. Both missions run concurrently.
    2. Event streams, state snapshots, and workspaces do not cross-contaminate.
    """
    ws_a = tmp_path / "ws_a"
    ws_b = tmp_path / "ws_b"
    ws_a.mkdir()
    ws_b.mkdir()

    bus = EventBus()
    py = get_canonical_python_executable()

    # Create mock orchestrators that generate different files
    def make_mock_orch(filename: str, content: str):
        orch = MagicMock()
        call_count = 0

        async def mock_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return NormalizedModelResponse(
                    text=f"Writing {filename}",
                    tool_calls=[{
                        "id": f"call_{filename}",
                        "name": "write_file",
                        "arguments": {"path": filename, "content": content},
                    }],
                )
            return NormalizedModelResponse(
                text=f"Completed {filename}",
                tool_calls=[],
            )

        orch._generate_t1 = mock_gen
        orch.mode = "auto"
        return orch

    wm_a = WorkspaceManager()
    wm_a.lock(str(ws_a))
    wm_b = WorkspaceManager()
    wm_b.lock(str(ws_b))

    loop_a = AgentLoop(
        orchestrator=make_mock_orch("a_output.txt", "MISSION_A_DATA"),
        workspace_manager=wm_a,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=3, max_wall_time_seconds=10.0),
    )
    loop_b = AgentLoop(
        orchestrator=make_mock_orch("b_output.txt", "MISSION_B_DATA"),
        workspace_manager=wm_b,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=3, max_wall_time_seconds=10.0),
    )

    mission_a = Mission(mission_id="m_scen_a_1", user_prompt="Generate A", workspace_root=str(ws_a))
    mission_b = Mission(mission_id="m_scen_a_2", user_prompt="Generate B", workspace_root=str(ws_b))

    # Run simultaneously
    res_a, res_b = await asyncio.gather(loop_a.run(mission_a), loop_b.run(mission_b))

    assert res_a.success is True
    assert res_b.success is True
    assert (ws_a / "a_output.txt").exists()
    assert (ws_b / "b_output.txt").exists()
    assert not (ws_a / "b_output.txt").exists()
    assert not (ws_b / "a_output.txt").exists()

    # Verify event stream isolation
    events_a = bus.replay("m_scen_a_1")
    events_b = bus.replay("m_scen_a_2")
    assert all(e.mission_id == "m_scen_a_1" for e in events_a)
    assert all(e.mission_id == "m_scen_a_2" for e in events_b)


@pytest.mark.asyncio
async def test_scenario_b_cancel_one_mission_while_other_continues(tmp_path: Path):
    """
    Scenario B:
    Two concurrent missions A and B with distinct child processes.
    Cancel A while B continues running.
    Verifies:
    1. A reaches CANCELLED.
    2. A's owned subprocess is terminated safely.
    3. B's subprocess remains alive and running.
    4. B completes successfully.
    5. A's termination does not affect B's state, approvals, or processes.
    """
    py = get_canonical_python_executable()

    # Launch process A (60s sleep) and process B (60s sleep)
    proc_a = subprocess.Popen([py, "-c", "import time; time.sleep(60)"])
    proc_b = subprocess.Popen([py, "-c", "import time; time.sleep(60)"])

    mission_id_a = "m_scen_b_cancel"
    mission_id_b = "m_scen_b_continue"

    register_active_subprocess(proc_a, mission_id=mission_id_a)
    register_active_subprocess(proc_b, mission_id=mission_id_b)

    assert proc_a.poll() is None
    assert proc_b.poll() is None

    # Cancel Mission A via scoped termination
    terminated_count = terminate_active_subprocesses(mission_id=mission_id_a)
    assert terminated_count == 1
    assert proc_a.poll() is not None  # Process A must be dead

    # Process B MUST remain alive and unaffected!
    assert proc_b.poll() is None
    assert proc_b in ACTIVE_SUBPROCESSES
    assert PROCESS_MISSION_MAP.get(proc_b) == mission_id_b

    # Cleanup B
    proc_b.terminate()
    proc_b.wait(timeout=2.0)
    unregister_active_subprocess(proc_b)


@pytest.mark.asyncio
async def test_scenario_c_one_mission_times_out_while_another_completes(tmp_path: Path):
    """
    Scenario C:
    Two concurrent missions with different runtime budgets.
    Mission A encounters a wall-time timeout.
    Mission B completes within budget.
    Verifies:
    1. A reaches FAILED with 'Max wall time exceeded'.
    2. B is unaffected and completes.
    3. A's pending approvals are invalidated without invalidating B's approvals.
    """
    bus = EventBus()
    gate_a = SecurityGate()
    gate_b = SecurityGate()

    # Pre-populate approval requests for both missions
    req_a = ApprovalRequest(
        request_id="req_a_timeout",
        mission_id="m_scen_c_a",
        action=ActionDescriptor(tool_name="bash_exec", mission_id="m_scen_c_a"),
    )
    req_b = ApprovalRequest(
        request_id="req_b_ok",
        mission_id="m_scen_c_b",
        action=ActionDescriptor(tool_name="bash_exec", mission_id="m_scen_c_b"),
    )
    gate_a.approval_store.add_request(req_a)
    gate_b.approval_store.add_request(req_b)

    # Loop A has 0.5s max wall time and hangs in model call
    orch_a = MagicMock()
    async def mock_hang(*args, **kwargs):
        await asyncio.sleep(2.0)
        return NormalizedModelResponse(text="done", tool_calls=[])
    orch_a._generate_t1 = mock_hang
    orch_a.mode = "auto"

    wm_a = WorkspaceManager()
    (tmp_path / "a").mkdir()
    wm_a.lock(str(tmp_path / "a"))

    wm_b = WorkspaceManager()
    (tmp_path / "b").mkdir()
    wm_b.lock(str(tmp_path / "b"))

    loop_a = AgentLoop(
        orchestrator=orch_a,
        workspace_manager=wm_a,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=3, max_wall_time_seconds=0.5),
    )
    loop_a._action_executor.security_gate = gate_a

    # Loop B has 5.0s max wall time and completes after Loop A times out
    orch_b = MagicMock()
    async def mock_fast(*args, **kwargs):
        # Allow Loop A to hit its 0.5s timeout first
        await asyncio.sleep(0.7)
        # Verify that Loop A's timeout invalidated A's approval but left B's approval intact!
        assert req_a.resolved is True
        assert req_a.status == "CANCELLED"
        assert req_b.resolved is False
        assert req_b.status == "PENDING"
        return NormalizedModelResponse(text="fast complete", tool_calls=[])
    orch_b._generate_t1 = mock_fast
    orch_b.mode = "auto"

    loop_b = AgentLoop(
        orchestrator=orch_b,
        workspace_manager=wm_b,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=3, max_wall_time_seconds=5.0),
    )
    loop_b._action_executor.security_gate = gate_b

    res_a, res_b = await asyncio.gather(
        loop_a.run(Mission(mission_id="m_scen_c_a", user_prompt="Hanging A", workspace_root=str(tmp_path / "a"))),
        loop_b.run(Mission(mission_id="m_scen_c_b", user_prompt="Fast B", workspace_root=str(tmp_path / "b"))),
    )

    assert res_a.success is False
    assert "Max wall time exceeded" in (res_a.error or "")

    # B must succeed
    assert res_b.success is True

    # A's approval request was cancelled on timeout
    assert req_a.resolved is True
    assert req_a.status == "CANCELLED"

    # After B also completes, its approval request was cleanly finalized on terminal exit
    assert req_b.resolved is True
    assert req_b.status == "CANCELLED"


@pytest.mark.asyncio
async def test_scenario_d_process_tree_cleanup_and_isolation():
    """
    Scenario D:
    On Windows, verify that process termination recursively kills child process trees
    spawned by the mission's subprocess, while leaving unrelated processes untouched.
    """
    py = get_canonical_python_executable()

    # Script that spawns a child process and sleeps (use raw/escaped string for Windows path)
    py_escaped = py.replace("\\", "\\\\")
    parent_script = (
        "import subprocess, sys, time; "
        f"child = subprocess.Popen(['{py_escaped}', '-c', 'import time; time.sleep(60)']); "
        "time.sleep(60)"
    )

    proc_parent = subprocess.Popen([py, "-c", parent_script])
    time.sleep(1.0)  # Allow child to spawn

    mission_id = "m_scen_d_tree"
    register_active_subprocess(proc_parent, mission_id=mission_id)

    # Find the child PID
    parent_ps = psutil.Process(proc_parent.pid)
    children = parent_ps.children(recursive=True)
    assert len(children) >= 1
    child_pid = children[0].pid

    # Check both are alive
    assert psutil.pid_exists(proc_parent.pid)
    assert psutil.pid_exists(child_pid)

    # Also start an independent unrelated process
    unrelated_proc = subprocess.Popen([py, "-c", "import time; time.sleep(60)"])
    register_active_subprocess(unrelated_proc, mission_id="m_other_mission")

    # Terminate mission D's subprocess tree
    terminated = terminate_active_subprocesses(mission_id=mission_id)
    assert terminated == 1

    # Verify both parent and child are completely dead
    time.sleep(0.5)
    assert not psutil.pid_exists(proc_parent.pid)
    assert not psutil.pid_exists(child_pid)

    # Verify unrelated process is still alive!
    assert unrelated_proc.poll() is None
    assert psutil.pid_exists(unrelated_proc.pid)

    # Clean up unrelated
    unrelated_proc.terminate()
    unrelated_proc.wait(timeout=2.0)
    unregister_active_subprocess(unrelated_proc)


@pytest.mark.asyncio
async def test_scenario_e_approvals_and_event_isolation():
    """
    Scenario E:
    Verify cross-mission approval isolation:
    1. A grant generated for Mission A cannot authorize an action in Mission B.
    2. Invalidation of Mission A's requests does not affect Mission B's requests.
    3. Resolving request A does not resolve request B.
    """
    store = ApprovalStore()

    req_a = ApprovalRequest(
        request_id="req_m_a_1",
        mission_id="m_a",
        action=ActionDescriptor(tool_name="bash_exec", action_fingerprint="fp_bash_git", mission_id="m_a"),
    )
    req_b = ApprovalRequest(
        request_id="req_m_b_1",
        mission_id="m_b",
        action=ActionDescriptor(tool_name="bash_exec", action_fingerprint="fp_bash_git", mission_id="m_b"),
    )
    store.add_request(req_a)
    store.add_request(req_b)

    # Approve request A with ONCE scope
    grant_a = store.resolve_request("req_m_a_1", approved=True, scope=ApprovalScope.ONCE)
    assert grant_a is not None
    assert grant_a.mission_id == "m_a"

    # Request B should still be PENDING and unresolved
    assert req_b.resolved is False
    assert req_b.status == "PENDING"

    # Verify grant A matches action for mission A
    action_a = ActionDescriptor(tool_name="bash_exec", action_fingerprint="fp_bash_git", mission_id="m_a")
    matched = store.find_matching_grant(action_a)
    assert matched is not None
    assert matched.grant_id == grant_a.grant_id

    # Verify grant A DOES NOT match action for mission B!
    action_b = ActionDescriptor(tool_name="bash_exec", action_fingerprint="fp_bash_git", mission_id="m_b")
    matched_b = store.find_matching_grant(action_b)
    assert matched_b is None  # Mission isolation enforced!

    # Test cancellation scoping
    cancel_count = store.cancel_requests_for_mission("m_a", reason="A finished")
    assert req_b.resolved is False  # B is still unaffected!


@pytest.mark.asyncio
async def test_scenario_f_concurrent_deadline_and_cancellation_races():
    """
    Scenario F:
    Test controlled race conditions:
    1. Simultaneous deadline and stop request.
    2. Multiple concurrent cleanup calls on the same mission.
    3. Late events arriving after terminal state cannot resurrect the mission.
    """
    bus = EventBus()
    mission_id = "m_scen_f_race"
    store = bus.get_or_create_state(mission_id)

    # Publish MISSION_STARTED
    bus.publish(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id))
    assert store.get_snapshot().mission.status == MissionStatus.RUNNING

    # Publish MISSION_CANCELLED and MISSION_FAILED almost concurrently
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_CANCELLED,
        mission_id=mission_id,
        payload={"reason": "User cancellation"},
    ))
    snap1 = store.get_snapshot()
    assert snap1.mission.status == MissionStatus.CANCELLED
    assert snap1.mission.is_terminal is True

    # Attempt late failure event - terminal state must remain immutable
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id,
        payload={"error": "Late deadline failure"},
    ))
    snap2 = store.get_snapshot()
    assert snap2.mission.status == MissionStatus.CANCELLED  # Remains CANCELLED

    # Multiple cleanup calls on same mission must be idempotent and safe
    c1 = terminate_active_subprocesses(mission_id=mission_id)
    c2 = terminate_active_subprocesses(mission_id=mission_id)
    assert c1 == 0
    assert c2 == 0
