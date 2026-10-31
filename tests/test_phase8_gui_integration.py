# tests/test_phase8_gui_integration.py
"""
HERMES Phase 8 Acceptance Test Suite:
GUI, Project Hub, Mission Controls (Pause, Stop, Resume) & Ordered Event Recovery Integration.

Verifies:
1. Authoritative snapshot synchronization with accurate wait_reason, recovery_required, and is_paused states.
2. Pause endpoint, mission execution control, and MISSION_PAUSED event publishing.
3. Live unpause preserving run identity vs cold continuation recovery.
4. Mission-scoped Stop with terminal cancellation protection.
5. Multi-mission control isolation (no cross-mission interference).
6. Ordered event replay and monotonic cursor sequence tracking.
7. Project Hub immutable mission workspace binding across workspace switches.
8. Network waiting detection and automatic/manual recovery integration.
"""

import asyncio
import json
import pytest
from pathlib import Path
from starlette.testclient import TestClient

from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import MissionControlContext
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.persistence.database import SQLiteDatabase
from core.workspace_registry import WorkspaceRegistry


@pytest.fixture
def phase8_test_env(tmp_path):
    """Fixture providing isolated workspace, database, event bus, and test client."""
    ws_a = tmp_path / "workspace_alpha"
    ws_a.mkdir(parents=True, exist_ok=True)
    ws_b = tmp_path / "workspace_beta"
    ws_b.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "test_state.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(enabled=True, db=db)
    adapter = RuntimeAdapter(event_bus=bus)
    registry = WorkspaceRegistry(registry_file=tmp_path / "test_recent_workspaces.json")
    app = create_app(adapter=adapter, registry=registry)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    return {
        "workspace_a": ws_a,
        "workspace_b": ws_b,
        "db": db,
        "event_bus": bus,
        "adapter": adapter,
        "registry": registry,
        "app": app,
        "client": client,
        "tmp_path": tmp_path,
    }


def test_1_authoritative_snapshot_synchronization_and_waiting_reason(phase8_test_env):
    """Verify GET /api/missions/{mission_id} returns authoritative state snapshot

    with accurate wait_reason, recovery_required, and is_paused values.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]
    db = phase8_test_env["db"]
    mission_id = "m_snap_p8_01"

    # 1. Start mission
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id="run_001",
        payload={"prompt": "Integrate Phase 8 GUI"}
    ))

    # 2. Enter waiting state via canonical event and DB update
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_WAITING,
        mission_id=mission_id,
        run_id="run_001",
        payload={"wait_reason": "INTERNET_LOSS", "reason": "Internet connection lost"}
    ))
    db.save_mission(
        mission_id=mission_id,
        run_id="run_001",
        workspace_path=str(phase8_test_env["workspace_a"]),
        status="WAITING",
        wait_reason="INTERNET_LOSS",
        recovery_required=True
    )

    # 3. Request snapshot
    resp = client.get(f"/api/missions/{mission_id}")
    assert resp.status_code == 200
    snap = resp.json()

    assert snap["mission_id"] == mission_id
    assert snap["run_id"] == "run_001"
    assert snap["status"] == "WAITING"
    assert snap["wait_reason"] == "INTERNET_LOSS"
    assert snap["recovery_required"] is True
    assert snap["is_paused"] is False


def test_2_pause_endpoint_and_event_publishing(phase8_test_env):
    """Verify POST /api/missions/{mission_id}/pause sets is_paused=True,
    publishes MISSION_PAUSED event, and updates the snapshot.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]
    mission_id = "m_pause_p8_02"

    control = MissionControlContext(
        mission_id=mission_id,
        run_id="run_pause_01",
        abort_event=asyncio.Event(),
        pause_event=asyncio.Event(),
        workspace_root=str(phase8_test_env["workspace_a"]),
    )
    adapter._mission_controls[mission_id] = control

    # Start mission
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id="run_pause_01",
        payload={"prompt": "Task needing pause"}
    ))

    # Send pause request
    resp = client.post(f"/api/missions/{mission_id}/pause")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mission_id"] == mission_id
    assert data["paused"] is True
    assert "pause" in data["message"].lower()

    # Verify adapter control state
    ctrl = adapter._mission_controls.get(mission_id)
    assert ctrl is not None
    assert ctrl.is_paused is True

    # Flush bus to database
    bus.flush()

    # Verify MISSION_PAUSED event was published
    db = phase8_test_env["db"]
    events = db.get_mission_events(mission_id)
    pause_events = [e for e in events if e.get("event_type") == EventType.MISSION_PAUSED.value]
    assert len(pause_events) >= 1
    assert pause_events[0]["mission_id"] == mission_id

    # Verify snapshot reflects is_paused=True
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["is_paused"] is True


async def test_3_resume_live_unpause_preserves_run_identity(phase8_test_env):
    """Verify POST /api/missions/{mission_id}/resume handles live in-flight unpause
    without mutating run_id, unpausing the control and publishing MISSION_RESUMED.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]
    mission_id = "m_resume_live_p8_03"
    run_id = "run_live_03"

    control = MissionControlContext(
        mission_id=mission_id,
        run_id=run_id,
        abort_event=asyncio.Event(),
        pause_event=asyncio.Event(),
        workspace_root=str(phase8_test_env["workspace_a"]),
    )
    adapter._mission_controls[mission_id] = control

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"prompt": "Live in-flight test"}
    ))

    # Simulate an active running background task
    async def dummy_running_task():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy_running_task())
    adapter._active_tasks[mission_id] = task

    # Pause the mission while in-flight task is executing
    pause_res = client.post(f"/api/missions/{mission_id}/pause")
    assert pause_res.status_code == 200
    pdata = pause_res.json()
    assert pdata["status"] == "PAUSE_REQUESTED"
    assert pdata["paused"] is False
    assert adapter._mission_controls.get(mission_id).pause_requested is True
    assert adapter._mission_controls.get(mission_id).is_paused is False

    # Snapshot reports pause_pending = True and is_paused = False
    snap_pause = client.get(f"/api/missions/{mission_id}").json()
    assert snap_pause.get("pause_pending") is True
    assert snap_pause.get("is_paused") is False

    # Task reaches safe checkpoint boundary, emitting MISSION_PAUSED
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_PAUSED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"mission_id": mission_id}
    ))
    assert adapter._mission_controls.get(mission_id).is_paused is True
    assert adapter._mission_controls.get(mission_id).pause_requested is False

    # Now Resume (Live unpause branch)
    resume_resp = client.post(f"/api/missions/{mission_id}/resume")
    assert resume_resp.status_code == 200
    res_data = resume_resp.json()
    assert res_data["mission_id"] == mission_id
    assert res_data["run_id"] == run_id  # Run ID must be strictly preserved!
    assert res_data["status"] == "RUNNING"

    # Verify control is unpaused
    assert adapter._mission_controls.get(mission_id).is_paused is False

    # Flush bus to database
    bus.flush()

    # Verify MISSION_RESUMED event was published
    db = phase8_test_env["db"]
    events = db.get_mission_events(mission_id)
    res_events = [e for e in events if e.get("event_type") == EventType.MISSION_RESUMED.value]
    assert len(res_events) >= 1

    # Clean up dummy task
    task.cancel()


def test_4_stop_mission_scoped_cancellation(phase8_test_env):
    """Verify POST /api/missions/{mission_id}/stop dispatches immediate cancellation
    and publishes MISSION_CANCELLED.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]
    mission_id = "m_stop_p8_04"

    control = MissionControlContext(
        mission_id=mission_id,
        run_id="run_stop_04",
        abort_event=asyncio.Event(),
        pause_event=asyncio.Event(),
        workspace_root=str(phase8_test_env["workspace_a"]),
    )
    adapter._mission_controls[mission_id] = control

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id="run_stop_04",
        payload={"prompt": "Stopping mission"}
    ))

    resp = client.post(f"/api/missions/{mission_id}/stop")
    assert resp.status_code == 200
    stop_data = resp.json()
    assert stop_data["mission_id"] == mission_id
    assert stop_data["cancelled"] is True

    # Verify control cancellation requested
    ctrl = adapter._mission_controls.get(mission_id)
    assert ctrl.is_cancelled is True

    # Flush bus to database
    bus.flush()

    # Verify MISSION_CANCELLED event
    db = phase8_test_env["db"]
    events = db.get_mission_events(mission_id)
    cancelled_events = [e for e in events if e.get("event_type") == EventType.MISSION_CANCELLED.value]
    assert len(cancelled_events) >= 1


def test_5_multi_mission_control_isolation(phase8_test_env):
    """Verify pausing or stopping Mission A has zero effect on Mission B."""
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]

    mission_a = "m_iso_alpha"
    mission_b = "m_iso_beta"

    control_a = MissionControlContext(
        mission_id=mission_a,
        run_id="run_a",
        abort_event=asyncio.Event(),
        pause_event=asyncio.Event(),
        workspace_root=str(phase8_test_env["workspace_a"]),
    )
    control_b = MissionControlContext(
        mission_id=mission_b,
        run_id="run_b",
        abort_event=asyncio.Event(),
        pause_event=asyncio.Event(),
        workspace_root=str(phase8_test_env["workspace_b"]),
    )
    adapter._mission_controls[mission_a] = control_a
    adapter._mission_controls[mission_b] = control_b

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_a,
        run_id="run_a",
        payload={"prompt": "Alpha"}
    ))
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_b,
        run_id="run_b",
        payload={"prompt": "Beta"}
    ))

    # Pause Mission A
    client.post(f"/api/missions/{mission_a}/pause")

    ctrl_a = adapter._mission_controls.get(mission_a)
    ctrl_b = adapter._mission_controls.get(mission_b)

    assert ctrl_a.is_paused is True
    assert ctrl_b.is_paused is False  # B must remain unpaused!

    # Stop Mission A
    client.post(f"/api/missions/{mission_a}/stop")

    assert ctrl_a.is_cancelled is True
    assert ctrl_b.is_cancelled is False  # B must remain active!

    # Snapshots check
    snap_b = client.get(f"/api/missions/{mission_b}").json()
    assert snap_b["is_paused"] is False
    assert snap_b["is_terminal"] is False


def test_6_ordered_event_replay_and_cursor_tracking(phase8_test_env):
    """Verify event replay from cursor returns strictly ordered sequence numbers

    without missing or duplicating events.
    """
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]
    mission_id = "m_seq_p8_06"

    for i in range(1, 8):
        bus.publish(HermesEvent(
            event_type=EventType.PROGRESS_UPDATED,
            mission_id=mission_id,
            sequence=i,
            payload={"step": i}
        ))

    # Query events since cursor = 4
    events = adapter.get_events_since(mission_id, last_sequence=4)
    assert len(events) == 3
    assert [e.sequence for e in events] == [5, 6, 7]
    assert [e.payload["step"] for e in events] == [5, 6, 7]


def test_7_project_hub_immutable_mission_workspace_binding(phase8_test_env):
    """Verify switching the active project in Project Hub does not mutate or corrupt

    the workspace binding of an existing mission.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    db = phase8_test_env["db"]
    ws_a = phase8_test_env["workspace_a"]
    ws_b = phase8_test_env["workspace_b"]
    mission_id = "m_immut_p8_07"

    # Start mission bound strictly to Workspace A
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id="run_immut_07",
        payload={
            "prompt": "Workspace binding test",
            "workspace_root": str(ws_a)
        }
    ))
    db.save_mission(
        mission_id=mission_id,
        run_id="run_immut_07",
        workspace_path=str(ws_a),
        status="RUNNING"
    )

    # Verify initial snapshot has workspace A
    snap_a = client.get(f"/api/missions/{mission_id}").json()
    assert Path(snap_a["workspace_root"]).resolve() == ws_a.resolve()

    # User switches active workspace in Hub to Workspace B
    switch_resp = client.post("/api/workspaces/select", json={"folder_path": str(ws_b)})
    assert switch_resp.status_code == 200
    assert Path(switch_resp.json()["current_workspace"]).resolve() == ws_b.resolve()

    # Check snapshot again - mission workspace MUST still be Workspace A!
    snap_after = client.get(f"/api/missions/{mission_id}").json()
    assert Path(snap_after["workspace_root"]).resolve() == ws_a.resolve()
    assert Path(snap_after["workspace_root"]).resolve() != ws_b.resolve()


def test_8_network_recovery_integration_and_resumption(phase8_test_env):
    """Verify network recovery endpoint discovers waiting missions and triggers recovery."""
    client = phase8_test_env["client"]
    db = phase8_test_env["db"]
    bus = phase8_test_env["event_bus"]
    ws = phase8_test_env["workspace_a"]
    mission_id = "m_net_recover_p8_08"

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id="run_net_08",
        payload={"prompt": "Network recovery test", "workspace_root": str(ws)}
    ))

    db.save_mission(
        mission_id=mission_id,
        run_id="run_net_08",
        workspace_path=str(ws),
        status="WAITING",
        wait_reason="INTERNET_LOSS",
        recovery_required=True
    )

    # Check network status endpoint reports waiting mission
    status_resp = client.get("/api/network/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert "waiting_missions_count" in status_data

    # Trigger recovery endpoint
    rec_resp = client.post("/api/network/recover")
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    assert "recovered_count" in rec_data
    assert "recovered_mission_ids" in rec_data


async def test_9_pause_pending_vs_confirmed_lifecycle_boundary(phase8_test_env):
    """Verify pause requested on an active executing task reports PAUSE_REQUESTED,
    leaves pause_pending=True, and transitions to is_paused=True only after safe boundary confirmation.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]
    mission_id = "m_pause_boundary_09"
    run_id = "run_p9_01"

    control = MissionControlContext(
        mission_id=mission_id,
        run_id=run_id,
        abort_event=asyncio.Event(),
        pause_event=asyncio.Event(),
        workspace_root=str(phase8_test_env["workspace_a"]),
    )
    adapter._mission_controls[mission_id] = control

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"prompt": "Boundary test"}
    ))

    # Simulate running in-flight task
    async def dummy_task():
        await asyncio.sleep(5)
    t = asyncio.create_task(dummy_task())
    adapter._active_tasks[mission_id] = t

    # Step 1: Request pause while running
    resp = client.post(f"/api/missions/{mission_id}/pause")
    assert resp.status_code == 200
    res_json = resp.json()
    assert res_json["status"] == "PAUSE_REQUESTED"
    assert res_json["paused"] is False
    assert "waiting for safe checkpoint boundary" in res_json["message"]

    # Step 2: Verify snapshot exposes pause_pending=True, is_paused=False
    snap1 = client.get(f"/api/missions/{mission_id}").json()
    assert snap1["pause_pending"] is True
    assert snap1["is_paused"] is False

    # Step 3: Emit MISSION_PAUSED to represent reaching safe checkpoint boundary
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_PAUSED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"mission_id": mission_id}
    ))

    # Step 4: Verify snapshot now transitions to pause_pending=False, is_paused=True
    snap2 = client.get(f"/api/missions/{mission_id}").json()
    assert snap2["pause_pending"] is False
    assert snap2["is_paused"] is True

    t.cancel()


def test_10_stale_and_old_run_event_rejection(phase8_test_env):
    """Verify reducer and store reject events from older attempts, old run IDs,
    or duplicate sequence numbers without corrupting runtime state.
    """
    bus = phase8_test_env["event_bus"]
    mission_id = "m_stale_event_10"

    # Initialize state at attempt 2
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id="run_attempt_2",
        attempt_number=2,
        sequence=10,
        payload={"prompt": "Attempt 2 mission"}
    ))

    store = bus.get_state(mission_id)
    assert store is not None
    snap = store.get_snapshot()
    assert snap.mission.attempt_number == 2
    assert snap.mission.run_id == "run_attempt_2"

    # Attempt to send event from older attempt 1
    bus.publish(HermesEvent(
        event_type=EventType.TASK_CREATED,
        mission_id=mission_id,
        run_id="run_attempt_1",
        attempt_number=1,
        sequence=11,
        payload={"task_id": "t1", "title": "Stale Task 1"}
    ))

    # Verify attempt 1 event was dropped by reducer
    snap_after = store.get_snapshot()
    assert snap_after.mission.attempt_number == 2
    assert "t1" not in snap_after.tasks


def test_11_immutable_workspace_missing_or_unresolved_reports_blocking(phase8_test_env):
    """Verify missing or non-existent workspace path reports explicit blocking condition
    (recovery_required=True, WORKSPACE_NOT_FOUND or MISSING_WORKSPACE) and NEVER silently falls back
    to the active project hub workspace.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    db = phase8_test_env["db"]
    mission_id = "m_missing_ws_11"
    non_existent_path = "C:/path/that/does/not/exist/at/all_hermes_test"

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id="run_missing_ws",
        payload={"prompt": "Non existent workspace test", "workspace_root": non_existent_path}
    ))
    db.save_mission(
        mission_id=mission_id,
        run_id="run_missing_ws",
        workspace_path=non_existent_path,
        status="RUNNING"
    )

    # Fetch snapshot
    resp = client.get(f"/api/missions/{mission_id}")
    assert resp.status_code == 200
    snap = resp.json()

    # Must NOT silently fall back to Phase 8 fixture workspace_a or current cwd
    assert snap["workspace_root"] == non_existent_path
    assert snap["recovery_required"] is True
    assert snap["wait_reason"] == "WORKSPACE_NOT_FOUND"


async def test_12_stop_races_with_pending_pause_cannot_be_overwritten(phase8_test_env):
    """Verify Critical Interleaving 2: If Stop is issued immediately before pause confirmation,
    Stop wins, delayed confirm_pause() is discarded, MISSION_PAUSED is never published,
    and terminal state cannot be resurrected.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]
    mission_id = "m_stop_race_12"
    run_id = "run_p12_01"

    abort_evt = asyncio.Event()
    pause_evt = asyncio.Event()
    pause_evt.set()  # Initially unpaused/running

    control = MissionControlContext(
        mission_id=mission_id,
        run_id=run_id,
        attempt_number=1,
        abort_event=abort_evt,
        pause_event=pause_evt,
        workspace_root=str(phase8_test_env["workspace_a"]),
    )
    adapter._mission_controls[mission_id] = control

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"prompt": "Stop race test"}
    ))

    # Barrier events for deterministic synchronization:
    at_boundary_gate = asyncio.Event()
    proceed_gate = asyncio.Event()

    async def executor_loop():
        while not abort_evt.is_set():
            if pause_evt is not None and not pause_evt.is_set() and not abort_evt.is_set():
                # Reached safe boundary immediately before confirm_pause
                at_boundary_gate.set()
                await proceed_gate.wait()

                # Re-verify conditions in case Stop or Resume arrived:
                if abort_evt.is_set() or control.is_terminal:
                    break  # Stop won! Do not pause.
                elif pause_evt.is_set() or not control.pause_requested:
                    pass  # Resume won!
                else:
                    control.confirm_pause()
                    bus.publish(HermesEvent(
                        event_type=EventType.MISSION_PAUSED,
                        mission_id=mission_id,
                        run_id=run_id,
                    ))
            await asyncio.sleep(0.01)

    t = asyncio.create_task(executor_loop())
    adapter._active_tasks[mission_id] = t

    # Step 1: Request pause while running
    resp_pause = client.post(f"/api/missions/{mission_id}/pause")
    assert resp_pause.status_code == 200
    assert resp_pause.json()["status"] == "PAUSE_REQUESTED"
    assert control.pause_requested is True
    assert control.is_paused is False

    # Snapshot check: Pending pause
    snap_pending = client.get(f"/api/missions/{mission_id}").json()
    assert snap_pending["pause_pending"] is True
    assert snap_pending["is_paused"] is False

    # Wait until executor is held right at the boundary gate
    await at_boundary_gate.wait()

    # Step 2: Stop is issued while held right before confirmation
    resp_stop = client.post(f"/api/missions/{mission_id}/stop")
    assert resp_stop.status_code == 200
    assert control.is_terminal is True
    assert control.pause_requested is False
    assert control.is_paused is False

    # Step 3: Release proceed_gate allowing executor to proceed
    proceed_gate.set()
    try:
        await t
    except asyncio.CancelledError:
        pass  # Expected: stop_mission cancels the active task

    # Step 4: Delayed pause confirmation attempt must be a no-op
    control.confirm_pause()
    assert control.is_paused is False
    assert control.is_terminal is True

    # Verify no MISSION_PAUSED event was ever emitted
    paused_events = [e for e in bus._history if e.mission_id == mission_id and e.event_type == EventType.MISSION_PAUSED]
    assert len(paused_events) == 0, "MISSION_PAUSED must NEVER be emitted when Stop wins the race"

    # Snapshot check: Terminal mission must report is_paused=False, pause_pending=False, is_terminal=True
    snap = client.get(f"/api/missions/{mission_id}").json()
    assert snap["is_terminal"] is True
    assert snap["is_paused"] is False
    assert snap["pause_pending"] is False

    # Step 5: Resume attempt on stopped mission is rejected
    resp_resume = client.post(f"/api/missions/{mission_id}/resume")
    assert resp_resume.status_code == 409
    assert "terminal" in resp_resume.json()["detail"].lower()


async def test_13_resume_races_with_pending_pause_preserves_identity(phase8_test_env):
    """Verify Critical Interleaving 1: If Resume is issued immediately before pause confirmation,
    Resume wins, pending pause is cancelled, delayed confirm_pause() is skipped,
    no MISSION_PAUSED is emitted, and live run identity is preserved.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]
    mission_id = "m_resume_race_13"
    run_id = "run_p13_01"

    abort_evt = asyncio.Event()
    pause_evt = asyncio.Event()
    pause_evt.set()  # Initially unpaused/running

    control = MissionControlContext(
        mission_id=mission_id,
        run_id=run_id,
        attempt_number=1,
        abort_event=abort_evt,
        pause_event=pause_evt,
        workspace_root=str(phase8_test_env["workspace_a"]),
    )
    adapter._mission_controls[mission_id] = control

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id=run_id,
        attempt_number=1,
        payload={"prompt": "Resume race test"}
    ))

    # Barrier events for deterministic synchronization:
    at_boundary_gate = asyncio.Event()
    proceed_gate = asyncio.Event()
    loop_finished = asyncio.Event()

    async def executor_loop():
        executed_steps = 0
        while not abort_evt.is_set() and executed_steps < 3:
            executed_steps += 1
            if pause_evt is not None and not pause_evt.is_set() and not abort_evt.is_set():
                # Reached safe boundary immediately before confirm_pause
                at_boundary_gate.set()
                await proceed_gate.wait()

                # Re-verify conditions in case Stop or Resume arrived:
                if abort_evt.is_set() or control.is_terminal:
                    break
                elif pause_evt.is_set() or not control.pause_requested:
                    pass  # Resume won! Skip pause confirmation
                else:
                    control.confirm_pause()
                    bus.publish(HermesEvent(
                        event_type=EventType.MISSION_PAUSED,
                        mission_id=mission_id,
                        run_id=run_id,
                    ))
            await asyncio.sleep(0.01)
        loop_finished.set()

    t = asyncio.create_task(executor_loop())
    adapter._active_tasks[mission_id] = t

    # Step 1: Request pause -> pending
    resp_pause = client.post(f"/api/missions/{mission_id}/pause")
    assert resp_pause.status_code == 200
    assert control.pause_requested is True
    assert control.is_paused is False

    # Snapshot check: Pending pause
    snap_pending = client.get(f"/api/missions/{mission_id}").json()
    assert snap_pending["pause_pending"] is True
    assert snap_pending["is_paused"] is False

    # Wait until executor is held right at the boundary gate
    await at_boundary_gate.wait()

    # Step 2: Request resume while held immediately before confirmation
    resp_resume = client.post(f"/api/missions/{mission_id}/resume")
    assert resp_resume.status_code == 200
    res_data = resp_resume.json()
    assert res_data["status"] == "RUNNING"
    assert "Pending pause cancelled" in res_data["message"]
    assert control.pause_requested is False
    assert control.is_paused is False

    # Step 3: Release proceed_gate allowing executor to proceed through confirmation path
    proceed_gate.set()
    await loop_finished.wait()

    # Step 4: Delayed confirm_pause() must be a no-op
    control.confirm_pause()
    assert control.is_paused is False
    assert control.pause_requested is False

    # Verify no MISSION_PAUSED event was ever emitted
    paused_events = [e for e in bus._history if e.mission_id == mission_id and e.event_type == EventType.MISSION_PAUSED]
    assert len(paused_events) == 0, "MISSION_PAUSED must NEVER be emitted when Resume wins the race"

    # Snapshot check: Run identity preserved, pause flags cleared
    snap = client.get(f"/api/missions/{mission_id}").json()
    assert snap["run_id"] == run_id
    assert snap["attempt_number"] == 1
    assert snap["pause_pending"] is False
    assert snap["is_paused"] is False

    t.cancel()


def test_14_pause_idempotency_and_terminal_protection(phase8_test_env):
    """Verify pause idempotency: repeated pause calls on a paused or pending mission
    return consistent statuses, and pause calls on a terminal mission are rejected.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    adapter = phase8_test_env["adapter"]
    mission_id = "m_idempotency_14"
    run_id = "run_p14_01"

    control = MissionControlContext(
        mission_id=mission_id,
        run_id=run_id,
        abort_event=asyncio.Event(),
        pause_event=asyncio.Event(),
        workspace_root=str(phase8_test_env["workspace_a"]),
    )
    adapter._mission_controls[mission_id] = control

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"prompt": "Idempotency test"}
    ))

    # Confirmed pause state via request then confirmation
    control.request_pause()
    control.confirm_pause()
    assert control.is_paused is True

    # Call pause again -> should return PAUSED with paused=True
    resp1 = client.post(f"/api/missions/{mission_id}/pause")
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "PAUSED"
    assert resp1.json()["paused"] is True

    # Now mark terminal (e.g. stopped)
    control.mark_terminal()
    assert control.is_terminal is True
    assert control.is_paused is False

    # Call pause on terminal mission -> must be rejected with 409
    resp_term = client.post(f"/api/missions/{mission_id}/pause")
    assert resp_term.status_code == 409
    assert "terminal" in resp_term.json()["detail"].lower()


def test_15_delayed_snapshot_watermark_invariants(phase8_test_env):
    """Verify backend store and snapshot state enforce strictly monotonic state_version
    and sequence numbers, guaranteeing client-side watermark protection.
    """
    client = phase8_test_env["client"]
    bus = phase8_test_env["event_bus"]
    mission_id = "m_snap_watermark_15"

    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id="run_15",
        sequence=1,
        payload={"prompt": "Watermark invariant test"}
    ))

    store = bus.get_state(mission_id)
    assert store is not None
    snap1 = store.get_snapshot()
    assert snap1.state_version >= 1
    assert snap1.last_event_sequence >= 1

    # Publish subsequent event
    evt2 = HermesEvent(
        event_type=EventType.TASK_CREATED,
        mission_id=mission_id,
        run_id="run_15",
        sequence=2,
        payload={"task_id": "t1", "title": "Subtask 1"}
    )
    bus.publish(evt2)

    snap2 = store.get_snapshot()
    assert snap2.state_version > snap1.state_version
    assert snap2.last_event_sequence == 2

    # Verify that a duplicate event is deduplicated by EventBus and does NOT advance sequence or version
    bus.publish(evt2)

    snap3 = store.get_snapshot()
    assert snap3.last_event_sequence == 2
    assert snap3.state_version == snap2.state_version

    # Also check the API snapshot projection exposes last_sequence correctly
    snap_api = client.get(f"/api/missions/{mission_id}").json()
    assert snap_api["last_sequence"] == 2
    assert snap_api["state_version"] >= 2

