# tests/test_stale_running_control_reconciliation.py
"""
Deterministic regression tests for lifecycle and execution-control defect repairs:
1. Active running mission Stop requests immediately cancel worker and persist CANCELLED.
2. Stale RUNNING mission Stop request without active worker transitions to CANCELLED,
   authoritatively updating both SQLite (missions & snapshots) and in-memory event bus/state store.
3. Stop during waiting/recovery safely cancels mission.
4. Active mission Pause request observes pause protocol.
5. Stale RUNNING mission Pause request without live worker reconciles to WAITING (WAITING_FOR_RECOVERY),
   returns informative blocker and persists truthful state.
6. Repeated Stop requests are idempotent and preserve terminal state without corruption.
7. Concurrent Stop request and worker completion: terminal CANCELLED cannot be resurrected to RUNNING.
8. Stale worker from earlier attempt cannot overwrite newer attempt.
9. Persistence failure during Stop reports error, not false success.
10. Resume of stopped/terminal mission follows legal transitions and does not silently replay.
11. Workspace binding and write-ahead integrity are preserved during stop and pause.
12. API endpoint verification across TestClient boundaries for both active and stale states.
"""

import asyncio
import json
import pytest
from pathlib import Path
from starlette.testclient import TestClient

from core.event_bus import EventBus
from core.persistence.database import SQLiteDatabase
from core.persistence.serializer import serialize_runtime_state
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionControlContext,
    MissionState,
    MissionStatus,
    TaskState,
    TaskStatus,
)
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter


@pytest.fixture
def isolated_env(tmp_path):
    """Fixture providing isolated database, workspace, event bus, adapter, and test client."""
    ws = tmp_path / "workspace_test"
    ws.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "isolated_runtime.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(enabled=True, db=db)
    adapter = RuntimeAdapter(event_bus=bus)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return {
        "workspace": ws,
        "db": db,
        "bus": bus,
        "adapter": adapter,
        "app": app,
        "client": client,
    }


# Case 1: Active running mission Stop request cancels worker and persists CANCELLED
@pytest.mark.asyncio
async def test_case_1_active_running_mission_stop_cancels_and_persists(isolated_env):
    adapter = isolated_env["adapter"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_active_case1"

    # Pre-register mission in database
    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
        wait_reason="WORKING",
        run_id="run_1_c1",
        attempt_number=1,
    )

    # Start mission state
    ctrl = MissionControlContext(mission_id=m_id, run_id="run_1_c1", workspace_root=str(ws))
    adapter._mission_controls[m_id] = ctrl
    adapter.event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=m_id,
        run_id="run_1_c1",
        payload={"mission_id": m_id}
    ))

    worker_finished = False
    worker_attempted_write_after_cancel = False

    # Create dummy active task with controlled execution
    async def dummy_worker():
        nonlocal worker_finished, worker_attempted_write_after_cancel
        try:
            await asyncio.sleep(10.0)
            worker_finished = True
        except asyncio.CancelledError:
            # Simulate worker cleanup - verify it cannot write protected state after cancellation
            await asyncio.sleep(0.02)
            worker_finished = True
            raise

    task = asyncio.create_task(dummy_worker())
    await asyncio.sleep(0.01)  # Allow dummy_worker to enter sleep(10.0)
    adapter._active_tasks[m_id] = task

    # Invoke stop_mission - MUST await worker task completion
    stopped = await adapter.stop_mission(m_id)
    assert stopped is True
    # The worker task must be strictly done upon stop_mission return
    assert task.done() is True
    assert worker_finished is True

    # State store in-memory must be CANCELLED and terminal
    store = adapter.event_bus.get_state(m_id)
    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.CANCELLED
    assert snap.mission.is_terminal is True

    # Authoritative database records must be durably CANCELLED
    m_row = db.get_mission(m_id)
    assert m_row["status"] == "CANCELLED"
    assert m_row["wait_reason"] == "NONE"
    assert m_row["execution_active"] is False

    snap_row = db.get_snapshot(m_id)
    assert snap_row is not None
    assert snap_row["status"] == "CANCELLED"


# Case 2: Stale RUNNING mission with absent executor transitions to CANCELLED in DB and state store
@pytest.mark.asyncio
async def test_case_2_stale_running_mission_stop_transitions_to_cancelled(isolated_env):
    adapter = isolated_env["adapter"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_stale_case2"

    # Insert a stale RUNNING mission row directly into SQLite (simulating dead server / orphaned process)
    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
        wait_reason="WORKING",
        prompt="Build test application",
        execution_active=False,
        recovery_required=False,
    )
    # Ensure no active tasks or controls exist in memory
    assert m_id not in adapter._active_tasks
    assert m_id not in adapter._mission_controls

    # Stop the stale mission
    stopped = await adapter.stop_mission(m_id)
    assert stopped is True

    # Authoritative verification in SQLite missions table
    m_row = db.get_mission(m_id)
    assert m_row is not None
    assert m_row["status"] == "CANCELLED"
    assert m_row["wait_reason"] == "NONE"
    assert m_row["execution_active"] is False
    assert m_row["recovery_required"] is False

    # Authoritative verification in SQLite snapshots table
    snap_row = db.get_snapshot(m_id)
    assert snap_row is not None
    assert snap_row["status"] == "CANCELLED"

    # In-memory StateStore check
    store = adapter.event_bus.get_state(m_id)
    assert store is not None
    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.CANCELLED
    assert snap.mission.is_terminal is True


# Case 3: Stop during waiting/recovery state cleanly cancels mission
@pytest.mark.asyncio
async def test_case_3_stop_during_waiting_recovery_state(isolated_env):
    adapter = isolated_env["adapter"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_waiting_case3"

    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="WAITING",
        wait_reason="WAITING_FOR_RECOVERY",
        prompt="Sample task",
        execution_active=False,
        recovery_required=True,
    )

    stopped = await adapter.stop_mission(m_id)
    assert stopped is True

    m_row = db.get_mission(m_id)
    assert m_row["status"] == "CANCELLED"
    assert m_row["wait_reason"] == "NONE"
    assert m_row["recovery_required"] is False


# Case 4: Active mission Pause request observes pause protocol
def test_case_4_active_mission_pause_observes_protocol(isolated_env):
    adapter = isolated_env["adapter"]
    ws = isolated_env["workspace"]
    m_id = "m_pause_case4"

    ctrl = MissionControlContext(mission_id=m_id, run_id="run_1_c4", workspace_root=str(ws))
    adapter._mission_controls[m_id] = ctrl
    adapter.event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=m_id,
        run_id="run_1_c4",
    ))

    # Request pause without active background worker -> confirms immediately
    accepted, confirmed = adapter.request_pause(m_id)
    assert accepted is True
    assert confirmed is True
    assert ctrl.is_paused is True

    store = adapter.event_bus.get_state(m_id)
    assert store.get_snapshot().mission.status == MissionStatus.PAUSED


# Case 5: Stale RUNNING mission Pause request reconciles to WAITING (WAITING_FOR_RECOVERY)
def test_case_5_stale_running_pause_reconciles_to_waiting(isolated_env):
    client = isolated_env["client"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    adapter = isolated_env["adapter"]
    m_id = "m_stale_case5"

    # Pre-populate state in memory so snapshot API has state
    state = HermesRuntimeState.create_empty(mission_id=m_id)
    state.mission.status = MissionStatus.RUNNING
    state.mission.workspace_root = str(ws)
    snap_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
        snapshot_dict=snap_dict,
        state_hash=s_hash,
    )

    # Insert stale RUNNING record in DB without live control
    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
        wait_reason="WORKING",
        prompt="Fix server bugs",
        execution_active=False,
        recovery_required=False,
    )

    # Calling pause endpoint
    resp = client.post(f"/api/missions/{m_id}/pause")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "not actively executing" in detail
    assert "Reconciled status to WAITING (WAITING_FOR_RECOVERY)" in detail

    # Verify reconciliation in DB
    m_row = db.get_mission(m_id)
    assert m_row["status"] == "WAITING"
    assert m_row["wait_reason"] == "WAITING_FOR_RECOVERY"
    assert m_row["recovery_required"] is True

    # Verify snapshot endpoint now truthful
    snap_resp = client.get(f"/api/missions/{m_id}")
    assert snap_resp.status_code == 200
    snap_data = snap_resp.json()
    assert snap_data["status"] == "WAITING"
    assert snap_data["wait_reason"] == "WAITING_FOR_RECOVERY"
    assert snap_data["recovery_required"] is True


# Case 6: Repeated Stop requests are idempotent and non-damaging
@pytest.mark.asyncio
async def test_case_6_repeated_stop_requests_idempotency(isolated_env):
    adapter = isolated_env["adapter"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_idemp_case6"

    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
        wait_reason="WORKING",
    )

    # Call 1: Successfully stops stale mission
    res1 = await adapter.stop_mission(m_id)
    assert res1 is True
    assert db.get_mission(m_id)["status"] == "CANCELLED"

    # Call 2: Already terminal, returns False (already stopped) without error
    res2 = await adapter.stop_mission(m_id)
    assert res2 is False
    assert db.get_mission(m_id)["status"] == "CANCELLED"

    # Call 3: Idempotent repetition
    res3 = await adapter.stop_mission(m_id)
    assert res3 is False
    assert db.get_mission(m_id)["status"] == "CANCELLED"


# Case 7: Concurrent Stop and worker completion: terminal CANCELLED cannot be resurrected to RUNNING
@pytest.mark.asyncio
async def test_case_7_stop_race_cannot_resurrect_running(isolated_env):
    adapter = isolated_env["adapter"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_race_case7"

    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
        run_id="run_1_c7",
    )
    store = adapter.event_bus.get_or_create_state(m_id)
    adapter.event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=m_id,
        run_id="run_1_c7",
    ))

    # Mission stopped
    await adapter.stop_mission(m_id)
    assert store.get_snapshot().mission.status == MissionStatus.CANCELLED

    # Late worker attempt to publish MISSION_RUNNING or MISSION_STARTED is rejected
    adapter.event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=m_id,
        run_id="run_1_c7",
    ))
    assert store.get_snapshot().mission.status == MissionStatus.CANCELLED
    assert store.get_snapshot().mission.is_terminal is True


# Case 8: Stale worker from earlier attempt cannot overwrite newer attempt
def test_case_8_stale_worker_cannot_overwrite_newer_attempt(isolated_env):
    adapter = isolated_env["adapter"]
    m_id = "m_attempt_case8"

    # Attempt 2 starts
    adapter.event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=m_id,
        run_id="run_2_xyz",
        attempt_number=2,
    ))
    store = adapter.event_bus.get_state(m_id)
    assert store.get_snapshot().mission.attempt_number == 2

    # Stale event from attempt 1 arrives
    adapter.event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=m_id,
        run_id="run_1_abc",
        attempt_number=1,
        payload={"error": "Stale crash"},
    ))

    # Snapshot should remain unaffected by older attempt event
    snap = store.get_snapshot()
    assert snap.mission.attempt_number == 2
    assert snap.mission.status == MissionStatus.RUNNING


# Case 9: Persistence failure during Stop reports error, not false success
@pytest.mark.asyncio
async def test_case_9_persistence_failure_reporting(isolated_env, monkeypatch):
    adapter = isolated_env["adapter"]
    client = isolated_env["client"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_persist_fail_case9"
    m_id_api = "m_persist_fail_api"

    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
    )
    db.save_mission(
        mission_id=m_id_api,
        workspace_path=str(ws),
        status="RUNNING",
    )

    # Monkeypatch save_mission to simulate fatal disk I/O error
    def failing_save_mission(*args, **kwargs):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(db, "save_mission", failing_save_mission)

    # Calling stop_mission directly raises the persistence error
    with pytest.raises(OSError, match="Simulated disk write failure"):
        await adapter.stop_mission(m_id)

    # The mission must NOT be falsely marked as CANCELLED in database
    # (database retains original RUNNING row)
    original_row = db.get_mission(m_id)
    assert original_row["status"] == "RUNNING"

    # API endpoint must report HTTP 500 error and NOT false success
    resp = client.post(f"/api/missions/{m_id_api}/stop")
    assert resp.status_code == 500
    assert "Failed to durably stop mission" in resp.json()["detail"]


# Case 10: Resume of stopped/terminal mission follows legal transitions
@pytest.mark.asyncio
async def test_case_10_resume_of_terminal_mission_legal_transition(isolated_env):
    adapter = isolated_env["adapter"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_legal_case10"

    # Mission completed successfully (terminal) with all tasks completed
    state = HermesRuntimeState.create_empty(mission_id=m_id, session_id="sess_10")
    state.mission.status = MissionStatus.COMPLETED
    state.tasks["t1"] = TaskState(
        task_id="t1",
        mission_id=m_id,
        title="Completed task",
        status=TaskStatus.COMPLETED,
        completion_reason="Verified",
    )
    snap_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(
        mission_id=m_id,
        workspace_path=str(ws),
        status="COMPLETED",
        snapshot_dict=snap_dict,
        state_hash=s_hash,
    )
    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="COMPLETED",
    )

    # Resume eligibility check rejects completed mission
    can_res, reason = adapter.validate_resume_eligibility(m_id)
    assert can_res is False
    assert "already completed" in reason.lower() or "terminal" in reason.lower()


# Case 11: Workspace binding and write-ahead integrity preserved
@pytest.mark.asyncio
async def test_case_11_workspace_binding_and_write_ahead_integrity(isolated_env):
    adapter = isolated_env["adapter"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_binding_case11"

    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
        wait_reason="WORKING",
    )

    await adapter.stop_mission(m_id)
    adapter.event_bus.flush()

    # Check that original workspace was preserved in database
    m_row = db.get_mission(m_id)
    assert m_row["workspace_path"] == str(ws)

    # Check journal has committed event
    events = db.get_mission_events(m_id)
    types = [e["event_type"] for e in events]
    assert "MISSION_CANCELLED" in types


# Case 12: API endpoint verification across TestClient boundaries for both active and stale states
def test_case_12_api_endpoint_boundaries(isolated_env):
    client = isolated_env["client"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]

    # 1. Stale RUNNING mission: Stop via HTTP POST
    m_stale = "m_api_stale_12"
    db.save_mission(
        mission_id=m_stale,
        workspace_path=str(ws),
        status="RUNNING",
        wait_reason="WORKING",
    )

    stop_resp = client.post(f"/api/missions/{m_stale}/stop")
    assert stop_resp.status_code == 200
    stop_data = stop_resp.json()
    assert stop_data["cancelled"] is True

    # Verify GET snapshot reflects CANCELLED with wait_reason NONE
    snap_resp = client.get(f"/api/missions/{m_stale}")
    assert snap_resp.status_code == 200
    snap_data = snap_resp.json()
    assert snap_data["status"] == "CANCELLED"
    assert snap_data["wait_reason"] is None
    assert snap_data["is_terminal"] is True

    # 2. Repeated Stop returns cancelled: false, already terminated
    stop_resp2 = client.post(f"/api/missions/{m_stale}/stop")
    assert stop_resp2.status_code == 200
    assert stop_resp2.json()["cancelled"] is False
    assert "already terminated" in stop_resp2.json()["message"]


# Case 13: Bounded cancellation timeout on stubborn worker reports failed cancellation
@pytest.mark.asyncio
async def test_case_13_stubborn_worker_cancellation_timeout_reports_failure(isolated_env):
    adapter = isolated_env["adapter"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_stubborn_case13"

    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
        wait_reason="WORKING",
    )

    ctrl = MissionControlContext(mission_id=m_id, run_id="run_stubborn", workspace_root=str(ws))
    adapter._mission_controls[m_id] = ctrl

    uncooperative_running = True

    # Dummy worker that ignores CancelledError and refuses to terminate
    async def stubborn_worker():
        nonlocal uncooperative_running
        while uncooperative_running:
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                # Deliberately catch and suppress CancelledError
                pass

    task = asyncio.create_task(stubborn_worker())
    await asyncio.sleep(0.01)  # Allow stubborn_worker to enter while loop
    adapter._active_tasks[m_id] = task

    # Monkeypatch timeout in wait_for to short duration for test speed
    orig_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, timeout):
        # Enforce 0.05s timeout for testing the stubborn worker
        return await orig_wait_for(coro, timeout=0.05)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(asyncio, "wait_for", fast_wait_for)
        # stop_mission must return False truthfully when worker does not stop
        stopped = await adapter.stop_mission(m_id)
        assert stopped is False
        assert task.done() is False

    # Cleanup stubborn task
    uncooperative_running = False
    await asyncio.sleep(0.05)


# Case 14: Action execution blocked after Stop is confirmed
@pytest.mark.asyncio
async def test_case_14_action_execution_blocked_after_stop(isolated_env):
    adapter = isolated_env["adapter"]
    db = isolated_env["db"]
    ws = isolated_env["workspace"]
    m_id = "m_block_action_case14"

    db.save_mission(
        mission_id=m_id,
        workspace_path=str(ws),
        status="RUNNING",
        wait_reason="WORKING",
    )

    # Initialize state store
    store = adapter.event_bus.get_or_create_state(m_id)
    adapter.event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=m_id,
        run_id="run_14",
    ))

    # Stop mission
    stopped = await adapter.stop_mission(m_id)
    assert stopped is True
    assert store.get_snapshot().mission.status == MissionStatus.CANCELLED

    # Verify ActionExecutor strictly blocks action dispatch when mission is terminal
    from core.agent_loop.actions import ActionExecutor
    from core.agent_loop.types import ActionEnvelope

    from core.workspace import WorkspaceManager

    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(ws))
    executor = ActionExecutor(event_bus_instance=adapter.event_bus)
    action = ActionEnvelope(
        mission_id=m_id,
        tool_name="write_file",
        arguments={"path": "forbidden.txt", "content": "should never be written"},
    )
    obs = await executor.execute_action(action, workspace=ws_mgr)
    assert obs.success is False
    assert "MISSION_TERMINAL" in obs.content or "MISSION_ABORTED" in str(obs.metadata)

    # Workspace must not contain the file
    assert not (ws / "forbidden.txt").exists()
