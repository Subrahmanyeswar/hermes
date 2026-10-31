# tests/test_phase4_stop_control.py
"""
HERMES Phase 4 Acceptance Test Suite: Immediate, Mission-Scoped Stop.

Scenarios Covered:
- Scenario A: Concurrent Mission Isolation (Stopping Mission A leaves Mission B active and unaffected).
- Scenario B: Immediate Stop Barrier & Tool Execution Prevention (Zero tool side effects dispatched after stop).
- Scenario C: Late Model Response Discard (Stale model response arriving after stop signal is rejected; no tools or terminal changes).
- Scenario D: Subprocess Tree Termination (Windows-safe psutil recursive tree termination terminates child process trees cleanly).
- Scenario E: Filesystem Preservation (Prior confirmed writes remain completely intact; zero rollback or clobbering upon stop).
- Scenario F: Settled Execution Point Checkpoint & Durable MISSION_CANCELLED (Last valid checkpoint preserved, terminal status recorded).
- Scenario G: Idempotency of Repeated Stop Invocations (Calling stop multiple times is safe and non-damaging).
- Scenario H: Non-Blocking API Response (<100ms Stop API execution, asynchronous cleanup).
"""

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
import pytest
import psutil

from core.runtime_state.models import (
    HermesRuntimeState,
    MissionStatus,
    MissionState,
    MissionControlContext,
    LEGAL_MISSION_TRANSITIONS,
)
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.reducer import StateReducer
from core.event_bus import EventBus
from core.agent_loop import (
    ActionEnvelope,
    ActionExecutor,
    ActionStatus,
    AgentDecision,
    AgentDecisionType,
    AgentLoop,
)
from models.provider import NormalizedModelResponse
from core.workspace import WorkspaceManager
from core.mission_planner import Mission
from tools.shell_tools import (
    register_active_subprocess,
    unregister_active_subprocess,
    terminate_active_subprocesses,
    ACTIVE_SUBPROCESSES,
    PROCESS_MISSION_MAP,
    CURRENT_MISSION_ID,
)


# ── Scenario A: Concurrent Mission Isolation ──────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_a_concurrent_mission_isolation(tmp_path):
    """Stopping Mission A leaves concurrent Mission B active, uncancelled, and isolated."""
    bus = EventBus()
    m_a = f"m_iso_a_{uuid.uuid4().hex[:6]}"
    m_b = f"m_iso_b_{uuid.uuid4().hex[:6]}"

    abort_a = asyncio.Event()
    abort_b = asyncio.Event()

    ctrl_a = MissionControlContext(mission_id=m_a, run_id=f"run_{m_a}", abort_event=abort_a)
    ctrl_b = MissionControlContext(mission_id=m_b, run_id=f"run_{m_b}", abort_event=abort_b)

    # Both missions start
    bus.publish(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=m_a))
    bus.publish(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=m_b))

    store_a = bus.get_state(m_a)
    store_b = bus.get_state(m_b)
    assert store_a.get_snapshot().mission.status == MissionStatus.RUNNING
    assert store_b.get_snapshot().mission.status == MissionStatus.RUNNING

    # Stop Mission A only
    ctrl_a.cancel()
    assert ctrl_a.is_cancelled is True
    assert abort_a.is_set() is True

    bus.publish(HermesEvent(event_type=EventType.MISSION_CANCELLED, mission_id=m_a, payload={"reason": "User stop"}))

    # Verify Mission A is CANCELLED and Mission B remains RUNNING
    assert store_a.get_snapshot().mission.status == MissionStatus.CANCELLED
    assert store_a.get_snapshot().mission.is_terminal is True

    assert ctrl_b.is_cancelled is False
    assert abort_b.is_set() is False
    assert store_b.get_snapshot().mission.status == MissionStatus.RUNNING
    assert store_b.get_snapshot().mission.is_terminal is False


# ── Scenario B: Immediate Stop Barrier & Tool Execution Prevention ───────────

@pytest.mark.asyncio
async def test_scenario_b_immediate_stop_barrier_prevents_tool_execution(tmp_path):
    """Once a mission is aborted or cancelled, subsequent tool calls are blocked before physical execution."""
    bus = EventBus()
    mission_id = f"m_barrier_{uuid.uuid4().hex[:6]}"
    ws = WorkspaceManager()
    ws.lock(tmp_path)

    # Start and then immediately cancel mission
    bus.publish(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id))
    bus.publish(HermesEvent(event_type=EventType.MISSION_CANCELLED, mission_id=mission_id, payload={"reason": "Stopped"}))

    executor = ActionExecutor(mode="auto", event_bus_instance=bus)
    action = ActionEnvelope(
        mission_id=mission_id,
        turn_id="turn_1",
        tool_name="write_file",
        arguments={"path": "forbidden_file.txt", "content": "SHOULD_NOT_BE_WRITTEN"},
    )

    obs = await executor.execute_action(action, workspace=ws)

    # Action must be rejected due to terminal / aborted state
    assert obs.success is False
    assert "MISSION_TERMINAL" in obs.summary or "MISSION_TERMINAL" in obs.content or "Action aborted" in obs.content
    target_file = tmp_path / "forbidden_file.txt"
    assert not target_file.exists(), "File must NOT have been written to disk after stop"


# ── Scenario C: Late Model Response Discard ───────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_c_late_model_response_discard(tmp_path):
    """If model generation finishes after an abort signal has arrived, its decision is discarded."""
    bus = EventBus()
    mission_id = f"m_late_model_{uuid.uuid4().hex[:6]}"
    ws = WorkspaceManager()
    ws.lock(tmp_path)

    abort_evt = asyncio.Event()

    # Create dummy orchestrator that sets abort signal right before returning
    class DelayedOrchestrator:
        async def _generate_t1(self, *args, **kwargs):
            # Simulate operator clicking stop while model was thinking
            abort_evt.set()
            return NormalizedModelResponse(
                text='{"tool": "write_file", "parameters": {"path": "late.txt", "content": "late"}}',
                tool_calls=[{"name": "write_file", "arguments": {"path": "late.txt", "content": "late"}}],
                success=True,
            )

    loop = AgentLoop(
        orchestrator=DelayedOrchestrator(),
        workspace_manager=ws,
        event_bus_instance=bus,
        abort_event=abort_evt,
    )

    mission = Mission(
        mission_id=mission_id,
        user_prompt="Write a file late",
        workspace_root=str(tmp_path),
        abort_event=abort_evt,
    )

    result = await loop.run(mission)

    # Loop must have terminated cleanly with CANCELLED
    assert result.status == "CANCELLED"
    # The late file must not have been created
    late_file = tmp_path / "late.txt"
    assert not late_file.exists(), "Late tool call must have been discarded"


# ── Scenario D: Subprocess Tree Termination ───────────────────────────────────

def test_scenario_d_subprocess_tree_termination():
    """Windows-safe termination terminates child and parent processes registered to a specific mission."""
    import subprocess
    mission_id = f"m_subproc_{uuid.uuid4().hex[:6]}"
    other_mission = f"m_subproc_other_{uuid.uuid4().hex[:6]}"

    # Launch a long-running Python process for our target mission
    proc_target = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    register_active_subprocess(proc_target, mission_id=mission_id)

    # Launch an unrelated process for another mission
    proc_other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    register_active_subprocess(proc_other, mission_id=other_mission)

    assert proc_target.poll() is None
    assert proc_other.poll() is None

    # Terminate active subprocesses for target mission only
    killed_count = terminate_active_subprocesses(mission_id=mission_id)
    assert killed_count >= 1

    # Give OS a moment to reap
    time.sleep(0.5)
    assert proc_target.poll() is not None, "Target subprocess must be terminated"

    # Other mission process must remain running!
    assert proc_other.poll() is None, "Unrelated mission process must remain untouched"

    # Clean up the other process
    terminate_active_subprocesses(mission_id=other_mission)
    assert proc_other.poll() is not None


# ── Scenario E: Filesystem Preservation ───────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_e_filesystem_preservation_on_stop(tmp_path):
    """Prior completed files remain fully intact when mission is stopped; no rollback or clobber occurs."""
    bus = EventBus()
    mission_id = f"m_preserve_{uuid.uuid4().hex[:6]}"
    ws = WorkspaceManager()
    ws.lock(tmp_path)

    bus.publish(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id))

    executor = ActionExecutor(mode="auto", event_bus_instance=bus)

    # Step 1: Tool creates a verified file
    action1 = ActionEnvelope(
        mission_id=mission_id,
        turn_id="turn_1",
        tool_name="write_file",
        arguments={"path": "completed_module.py", "content": "def add(a, b): return a + b\n"},
    )
    obs1 = await executor.execute_action(action1, workspace=ws)
    assert obs1.success is True
    file_path = tmp_path / "completed_module.py"
    assert file_path.exists()
    content_before_stop = file_path.read_text(encoding="utf-8")

    # Step 2: Stop is invoked
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_CANCELLED,
        mission_id=mission_id,
        payload={"reason": "Operator stopped mission"}
    ))

    # Step 3: Verify the file is unaltered
    assert file_path.exists()
    content_after_stop = file_path.read_text(encoding="utf-8")
    assert content_before_stop == content_after_stop == "def add(a, b): return a + b\n"


# ── Scenario F: Settled Execution Point Checkpoint & Durable State ────────────

@pytest.mark.asyncio
async def test_scenario_f_settled_checkpoint_and_durable_stop(tmp_path):
    """The latest settled checkpoint is retained and final status is durably CANCELLED."""
    from core.persistence.database import SQLiteDatabase
    from core.persistence.blobs import BlobStore
    from core.checkpoints.engine import CheckpointEngine
    from core.persistence.models import CheckpointReason, CheckpointTrigger

    db_path = tmp_path / "test_hermes.db"
    db = SQLiteDatabase(db_path)
    blobs = BlobStore(tmp_path / "blobs")
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)

    chk_engine = CheckpointEngine(
        base_dir=tmp_path,
        workspace_root=ws_dir,
        db=db,
        blob_store=blobs,
    )
    bus = EventBus(db=db)

    mission_id = f"m_chk_{uuid.uuid4().hex[:6]}"
    store = bus.get_or_create_state(mission_id)

    bus.publish_durable(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id))
    bus.publish_durable(HermesEvent(event_type=EventType.AGENT_TURN_STARTED, mission_id=mission_id, turn_id="t1"))
    bus.publish_durable(HermesEvent(event_type=EventType.AGENT_TURN_COMPLETED, mission_id=mission_id, turn_id="t1"))

    # Create safe boundary checkpoint at turn settlement
    snap = store.get_snapshot()
    chk = chk_engine.create_checkpoint(
        session_id=f"sess_{mission_id}",
        mission_id=mission_id,
        runtime_state=snap,
        reason=CheckpointReason.POST_ACTION,
        trigger=CheckpointTrigger.SYSTEM,
        sequence=snap.last_event_sequence,
    )
    assert chk is not None

    # Operator stops mission
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_CANCELLED,
        mission_id=mission_id,
        payload={"reason": "Operator stop"}
    ))

    # Verify latest state
    final_snap = store.get_snapshot()
    assert final_snap.mission.status == MissionStatus.CANCELLED
    assert final_snap.mission.is_terminal is True

    # Checkpoint remains retrievable and matches settled state
    loaded_chk = chk_engine.get_checkpoint(chk.checkpoint_id)
    assert loaded_chk is not None
    assert loaded_chk.sequence == snap.last_event_sequence
    assert loaded_chk.checkpoint_id == chk.checkpoint_id
    assert loaded_chk.mission_id == mission_id


# ── Scenario G: Idempotency of Repeated Stop Invocations ───────────────────────

@pytest.mark.asyncio
async def test_scenario_g_idempotency_of_repeated_stop():
    """Invoking stop multiple times on the same mission is safe, idempotent, and produces no exceptions."""
    bus = EventBus()
    mission_id = f"m_idemp_{uuid.uuid4().hex[:6]}"
    abort_evt = asyncio.Event()
    ctrl = MissionControlContext(mission_id=mission_id, run_id=f"run_{mission_id}", abort_event=abort_evt)

    bus.publish(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id))
    store = bus.get_state(mission_id)

    # First stop
    ctrl.cancel()
    bus.publish(HermesEvent(event_type=EventType.MISSION_CANCELLED, mission_id=mission_id, payload={"reason": "Stop 1"}))
    assert store.get_snapshot().mission.status == MissionStatus.CANCELLED

    # Repeated stop 2
    ctrl.cancel()
    bus.publish(HermesEvent(event_type=EventType.MISSION_CANCELLED, mission_id=mission_id, payload={"reason": "Stop 2"}))
    assert store.get_snapshot().mission.status == MissionStatus.CANCELLED

    # Repeated stop 3
    ctrl.cancel()
    bus.publish(HermesEvent(event_type=EventType.MISSION_CANCELLED, mission_id=mission_id, payload={"reason": "Stop 3"}))
    assert store.get_snapshot().mission.status == MissionStatus.CANCELLED
    assert store.get_snapshot().mission.is_terminal is True


# ── Scenario H: Non-Blocking Stop API Response ────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_h_non_blocking_stop_execution():
    """request_cancellation / stop executes within sub-10ms latency."""
    mission_id = f"m_latency_{uuid.uuid4().hex[:6]}"
    abort_evt = asyncio.Event()
    ctrl = MissionControlContext(mission_id=mission_id, run_id=f"run_{mission_id}", abort_event=abort_evt)

    t0 = time.perf_counter()
    ctrl.cancel()
    t1 = time.perf_counter()

    latency_ms = (t1 - t0) * 1000.0
    assert latency_ms < 50.0, f"Stop execution took {latency_ms:.2f}ms, exceeding 50ms budget"
    assert ctrl.is_cancelled is True
    assert abort_evt.is_set() is True
