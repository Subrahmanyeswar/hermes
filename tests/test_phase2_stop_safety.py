"""
Phase 2 Stop Safety Test Suite (INV-04, INV-05, Scenarios B, C, D, I).

Verifies:
1. Scenario B: Stop during model turn (cooperative cancellation).
2. Scenario C: Stop right before tool execution boundary (stops cleanly without executing mutating action).
3. Scenario D: Repeated Stop calls are idempotent and do not corrupt state or resurrect missions.
4. Scenario I: Stop timeout (worker refuses to terminate within bounded period; Stop is NOT reported completed).
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.event_bus import EventBus
from core.mission_planner import Mission
from core.persistence.database import SQLiteDatabase
from core.runtime_state.events import EventType, HermesEvent
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import WorkspaceManager


@pytest.mark.asyncio
async def test_scenario_b_stop_during_model_turn():
    """Verify that requesting Stop while a model call is active cancels cooperatively and updates state truthfully."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_stop_model_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_stop_model_{test_id}"

    model_started = asyncio.Event()

    async def hanging_model_turn(system_prompt: str, user_message: str) -> str:
        model_started.set()
        # Simulate long/hanging model call
        await asyncio.sleep(10.0)
        return json.dumps({"tool": "write_file", "parameters": {"path": "leak.txt", "content": "leak"}})

    # Run background execution
    async def run_worker():
        loop = AgentLoop(
            orchestrator=MagicMock(),
            workspace_manager=ws_mgr,
            event_bus_instance=bus,
            state_store_instance=bus.get_or_create_state(mission_id),
            config=AgentLoopConfig(max_turns=3),
            abort_event=adapter._abort_events[mission_id],
        )
        loop._generate_model_turn = AsyncMock(side_effect=hanging_model_turn)
        m = Mission(
            mission_id=mission_id,
            run_id=f"run_1_{test_id}",
            attempt_number=1,
            user_prompt="Long running task",
            workspace_root=str(tmp_dir),
            abort_event=adapter._abort_events[mission_id],
        )
        await loop.run(m)

    adapter._abort_events[mission_id] = asyncio.Event()
    worker_task = asyncio.create_task(run_worker())
    adapter._active_tasks[mission_id] = worker_task

    # Save initial running record in SQLite
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="RUNNING",
        attempt_number=1,
        execution_active=True,
    )

    # Wait for model turn to start
    await asyncio.wait_for(model_started.wait(), timeout=3.0)

    # User issues Stop
    stopped = await adapter.stop_mission(mission_id)
    assert stopped is True, "Stop request must successfully terminate the worker"

    # Worker task must be done
    assert worker_task.done() is True

    # Database state must be truthfully CANCELLED
    m_row = db.get_mission(mission_id)
    assert m_row["status"] == "CANCELLED"
    assert m_row["execution_active"] == 0

    # No files should have leaked to disk
    assert not (tmp_dir / "leak.txt").exists()


@pytest.mark.asyncio
async def test_scenario_c_stop_at_tool_execution_boundary():
    """Verify that if abort is signalled before tool execution, tool is not physically executed."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_stop_tool_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    abort_evt = asyncio.Event()
    mission_id = f"m_stop_tool_{test_id}"

    async def model_returns_tool(system_prompt: str, user_message: str) -> str:
        # Before returning, signal abort so abort_event is set prior to tool execution
        abort_evt.set()
        return json.dumps({
            "tool": "write_file",
            "parameters": {"path": "should_never_exist.txt", "content": "intercepted"},
            "explanation": "Attempt write",
        })

    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws_mgr,
        event_bus_instance=bus,
        state_store_instance=bus.get_or_create_state(mission_id),
        abort_event=abort_evt,
        config=AgentLoopConfig(max_turns=2),
    )
    loop._generate_model_turn = AsyncMock(side_effect=model_returns_tool)

    m = Mission(
        mission_id=mission_id,
        run_id=f"run_1_{test_id}",
        attempt_number=1,
        user_prompt="Write file test",
        workspace_root=str(tmp_dir),
        abort_event=abort_evt,
    )

    result = await loop.run(m)

    # File must NOT have been written to disk
    assert not (tmp_dir / "should_never_exist.txt").exists()
    assert result.success is False
    assert result.status == "CANCELLED" or result.termination_reason == "Cancelled by user"


@pytest.mark.asyncio
async def test_scenario_d_repeated_stop_is_idempotent():
    """Verify that multiple successive or concurrent Stop calls are idempotent."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_stop_repeat_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_repeat_{test_id}"

    # Set up a mission in the DB and in-flight
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="RUNNING",
        attempt_number=1,
        execution_active=True,
    )

    async def mock_worker():
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(mock_worker())
    adapter._active_tasks[mission_id] = task
    adapter._abort_events[mission_id] = asyncio.Event()

    # Call 1: Stops active worker
    res1 = await adapter.stop_mission(mission_id)
    assert res1 is True
    assert task.done() is True

    # Call 2: Second stop call on already cancelled mission
    res2 = await adapter.stop_mission(mission_id)
    assert res2 is False, "Repeated Stop on already cancelled mission must return False (idempotent)"

    # Call 3: Third stop call
    res3 = await adapter.stop_mission(mission_id)
    assert res3 is False

    # Status must remain CANCELLED, not corrupted or resurrected
    m_row = db.get_mission(mission_id)
    assert m_row["status"] == "CANCELLED"
    assert m_row["execution_active"] == 0


@pytest.mark.asyncio
async def test_scenario_i_stop_timeout_unconfirmed_handling():
    """Verify that if a worker refuses to terminate within bounded timeout, Stop is not reported as completed (INV-04)."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_stop_timeout_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_timeout_{test_id}"

    # Worker that catches CancelledError and ignores it, refusing to terminate
    async def stubborn_worker():
        while True:
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                # Stubbornly refuse cancellation
                await asyncio.sleep(10.0)

    task = asyncio.create_task(stubborn_worker())
    await asyncio.sleep(0.02)  # Allow stubborn_worker to enter its running loop
    adapter._active_tasks[mission_id] = task
    adapter._abort_events[mission_id] = asyncio.Event()

    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="RUNNING",
        attempt_number=1,
        execution_active=True,
    )

    # Bounded stop with short timeout
    stopped = await adapter.stop_mission(mission_id, timeout=0.1)

    # Invariant INV-04: STOP REQUESTED != STOP COMPLETED
    # Because worker did not terminate, stopped must be False
    assert stopped is False, "Stop must return False when worker does not terminate within timeout"

    # SQLite record must NOT have been marked CANCELLED
    m_row = db.get_mission(mission_id)
    assert m_row["status"] != "CANCELLED", "Mission must not be marked CANCELLED before worker terminates"

    # Cleanup stubborn task
    task.cancel()
