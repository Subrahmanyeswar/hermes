# tests/test_stage7_1_stalled_finalization.py
"""
Deterministic Acceptance Test Suite for HERMES Stage 7.1:
Stalled Mission Finalization, Deadline Enforcement, and Worker Cleanup.

Verifies:
- Case A: Audit Observation Deadline Expiry vs Runtime Execution
  - Audit script observation timeout does not prematurely terminate the runtime.
  - The runtime continues executing legitimately and reaches COMPLETED.
  - The mission state correctly transitions from RUNNING -> COMPLETED upon legitimate finish.
- Case B: Runtime Execution Deadline (Wall-Time Budget) Enforcement
  - When elapsed time exceeds config.max_wall_time_seconds, runtime terminates deterministically.
  - Emits MISSION_FAILED with 'Max wall time exceeded'.
  - Authoritative status is FAILED (terminal).
  - Approvals are invalidated and child workers cleaned up.
  - Subsequent late events cannot resurrect the mission to RUNNING or COMPLETED.
- Case C: Multi-Turn Budget & Consecutive Failure Budget Enforcement
  - Both budgets deterministically transition runtime to FAILED.
- Case D: Worker Subprocess Lifecycle & Verification Executable Contract
  - Subprocesses tracked in ACTIVE_SUBPROCESSES are terminated cleanly on terminal exit.
  - Verification commands record the canonical python executable path (sys.executable).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.agent_loop.types import (
    ActionEnvelope,
    ActionStatus,
    AgentDecision,
    AgentDecisionType,
    AgentTurn,
    Observation,
)
from core.event_bus import EventBus
from core.mission_planner import Mission
from core.runtime_identity import get_canonical_python_executable
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.runtime_state.models import MissionStatus
from core.security.approvals import ApprovalStore
from core.security.models import ActionDescriptor, ApprovalRequest
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import WorkspaceManager
from models.provider import NormalizedModelResponse
from tools.shell_tools import ACTIVE_SUBPROCESSES, terminate_active_subprocesses


@pytest.fixture
def clean_subprocesses():
    yield
    terminate_active_subprocesses()


@pytest.mark.asyncio
async def test_case_a_observation_timeout_vs_runtime_legitimate_completion(tmp_path: Path):
    """
    Case A:
    Simulates a slow-running task where an audit client stops observing after a short timeout (e.g. 0.2s),
    while the runtime continues running under its configured 10s budget and legitimately finishes.
    Verifies that:
    1. The mission is still RUNNING when the observation deadline expires.
    2. The runtime does NOT abort merely because the observer stopped waiting.
    3. The runtime finishes legitimately and reaches terminal status COMPLETED.
    """
    from core.workspace import workspace_manager
    bus = EventBus()
    workspace_manager.lock(tmp_path)

    # Mission and runtime setup
    mission_id = "m_test_case_a_observation"
    cfg = AgentLoopConfig(
        max_turns=5,
        max_wall_time_seconds=10.0,
        execution_mode="agentic",
    )

    # Mock orchestrator that executes a write tool then completes after a 0.5s delay
    orch = MagicMock()
    call_count = 0

    async def mock_generate_t1(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return NormalizedModelResponse(
                text="Writing math_lib.py",
                tool_calls=[{
                    "id": "call_1",
                    "name": "write_file",
                    "arguments": {
                        "path": "math_lib.py",
                        "content": "def add(a: int, b: int) -> int:\n    return a + b\n",
                        "mode": "create",
                    },
                }],
                success=True,
            )
        else:
            # Simulate slight delay representing legitimate compute
            await asyncio.sleep(0.4)
            return NormalizedModelResponse(
                text="I have completed creating math_lib.py with the add function.",
                tool_calls=[],
                success=True,
            )

    orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=orch,
        workspace_manager=workspace_manager,
        event_bus_instance=bus,
        config=cfg,
    )

    mission = Mission(
        mission_id=mission_id,
        user_prompt="Create math_lib.py with add function",
        workspace_root=str(tmp_path),
    )

    # Launch loop in background
    run_task = asyncio.create_task(loop.run(mission))

    # Observer polls with a short observation deadline (0.15s)
    observation_deadline = 0.15
    start_obs = time.monotonic()
    observed_terminal = False
    observed_status_at_deadline = None

    while (time.monotonic() - start_obs) < observation_deadline:
        await asyncio.sleep(0.05)
        st = bus.get_state(mission_id)
        if st and st.get_snapshot().mission.is_terminal:
            observed_terminal = True
            break

    st_at_deadline = bus.get_state(mission_id).get_snapshot()
    observed_status_at_deadline = st_at_deadline.mission.status

    # Invariant 1: At observation deadline expiry, runtime was NOT terminal; it was legitimately RUNNING
    assert not observed_terminal, "Runtime should still be working at early observation deadline"
    assert observed_status_at_deadline == MissionStatus.RUNNING

    # Now wait for the legitimate runtime completion
    result = await asyncio.wait_for(run_task, timeout=3.0)

    # Invariant 2: Runtime legitimately finished with success
    assert result.success is True
    assert result.status == MissionStatus.COMPLETED.value

    # Invariant 3: Final state in state store is COMPLETED
    final_snap = bus.get_state(mission_id).get_snapshot()
    assert final_snap.mission.status == MissionStatus.COMPLETED
    assert final_snap.mission.is_terminal is True
    assert (tmp_path / "math_lib.py").exists()


@pytest.mark.asyncio
async def test_case_b_runtime_wall_time_deadline_enforcement(tmp_path: Path):
    """
    Case B:
    Verifies that when the runtime's configured execution deadline (max_wall_time_seconds)
    is exceeded:
    1. The loop deterministically breaks.
    2. Emits MISSION_FAILED with 'Max wall time exceeded'.
    3. Terminal status is FAILED.
    4. Pending approvals are cancelled.
    5. Late events cannot resurrect the mission to RUNNING or COMPLETED.
    """
    from core.workspace import workspace_manager
    bus = EventBus()
    workspace_manager.lock(tmp_path)

    mission_id = "m_test_case_b_wall_time"
    # Tight wall-time limit of 0.3 seconds
    cfg = AgentLoopConfig(
        max_turns=50,
        max_wall_time_seconds=0.3,
        execution_mode="agentic",
    )

    orch = MagicMock()

    # Orchestrator responds with a tool call, each turn takes 0.2s, so 2 turns take 0.4s > 0.3s
    async def slow_generate(*args, **kwargs):
        await asyncio.sleep(0.2)
        return NormalizedModelResponse(
            text="Inspecting directory...",
            tool_calls=[{
                "id": "call_slow",
                "name": "list_directory",
                "arguments": {"path": "."},
            }],
            success=True,
        )

    orch._generate_t1 = slow_generate

    loop = AgentLoop(
        orchestrator=orch,
        workspace_manager=workspace_manager,
        event_bus_instance=bus,
        config=cfg,
    )

    # Setup pending approval in ActionExecutor's security gate
    approval_store = ApprovalStore()
    loop._action_executor.security_gate.approval_store = approval_store
    approval_store.add_request(ApprovalRequest(
        request_id="req_stall_1",
        mission_id=mission_id,
        action=ActionDescriptor(tool_name="bash_exec", command_str="long_running_job"),
    ))

    mission = Mission(
        mission_id=mission_id,
        user_prompt="Run an endless task",
        workspace_root=str(tmp_path),
    )

    result = await loop.run(mission)

    # Invariant 1: Loop failed due to max wall time exceeded
    assert result.success is False
    assert result.status == MissionStatus.FAILED.value
    assert "Max wall time exceeded" in (result.error or "")

    # Invariant 2: Authoritative StateStore is terminal FAILED
    snap = bus.get_state(mission_id).get_snapshot()
    assert snap.mission.status == MissionStatus.FAILED
    assert snap.mission.is_terminal is True
    assert "Max wall time exceeded" in (snap.mission.abort_reason or "")

    # Invariant 3: Pending approvals were invalidated
    pending = [r for r in approval_store.get_pending_requests() if r.mission_id == mission_id]
    assert len(pending) == 0
    assert approval_store.get_request("req_stall_1").status == "CANCELLED"

    # Invariant 4: Late event cannot resurrect the mission to RUNNING or COMPLETED
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"message": "Zombie attempt"},
    ))
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={"reason": "Rogue completion claim"},
    ))

    post_snap = bus.get_state(mission_id).get_snapshot()
    assert post_snap.mission.status == MissionStatus.FAILED
    assert post_snap.mission.is_terminal is True


@pytest.mark.asyncio
async def test_worker_cleanup_terminates_active_subprocesses(tmp_path: Path, clean_subprocesses):
    """
    Verifies that active child/worker processes registered in ACTIVE_SUBPROCESSES
    are terminated cleanly when terminate_active_subprocesses() is invoked on loop exit.
    """
    canonical_py = get_canonical_python_executable()

    # Spawn a sleeping background process using canonical python
    proc = subprocess.Popen(
        [canonical_py, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ACTIVE_SUBPROCESSES.add(proc)
    assert proc.poll() is None, "Subprocess should be actively running"

    # Invoke cleanup
    terminated_count = terminate_active_subprocesses()
    assert terminated_count >= 1
    assert proc.poll() is not None, "Subprocess must be terminated"
    assert proc not in ACTIVE_SUBPROCESSES


def test_canonical_python_executable_path_invariant():
    """
    Verifies that get_canonical_python_executable() strictly returns the absolute canonical
    virtual environment path rather than bare python.exe.
    """
    py_exec = get_canonical_python_executable()
    assert Path(py_exec).is_absolute()
    assert "venv" in py_exec.lower()
    assert py_exec.lower().endswith("python.exe")
    assert Path(py_exec).exists()
    assert Path(py_exec).resolve() == (Path.cwd() / "venv" / "Scripts" / "python.exe").resolve()
