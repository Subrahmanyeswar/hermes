"""
Phase 3 Test Suite: Attempt Fencing, Terminal Snapshot Protection, and Resume.

Verifies:
- Scenario I: Delayed event from attempt A1 cannot regress active attempt A2 state (Gate D).
- Scenario M: Stop while disconnected preserves cancellation state upon reconnect (Gate D).
- Scenario N: Resume into a newer attempt preserves continuation identity (Gate D).
"""

import uuid
import tempfile
import asyncio
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.workspace import WorkspaceManager
from core.server.runtime_adapter import RuntimeAdapter
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import MissionStatus


def test_scenario_i_delayed_event_from_older_attempt_rejected():
    """Verify that a delayed event from attempt 1 cannot regress state when attempt 2 is running."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_fence_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    mission_id = f"m_fence_{test_id}"

    store = bus.get_or_create_state(mission_id)

    # Attempt 1 starts and fails
    bus.publish_durable(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id, attempt_number=1))
    bus.publish_durable(HermesEvent(event_type=EventType.MISSION_FAILED, mission_id=mission_id, attempt_number=1))

    # Attempt 2 starts (authorized resume)
    bus.publish_durable(HermesEvent(event_type=EventType.MISSION_RESUMED, mission_id=mission_id, attempt_number=2))

    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.RUNNING
    assert snap.mission.attempt_number == 2

    # Delayed event arrives from attempt 1 claiming mission completed or failed
    stale_event = HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        attempt_number=1,
    )
    bus.publish_durable(stale_event)

    # State must NOT be regressed by attempt 1
    snap_after = store.get_snapshot()
    assert snap_after.mission.status == MissionStatus.RUNNING
    assert snap_after.mission.attempt_number == 2


@pytest.mark.asyncio
async def test_scenario_m_stop_while_disconnected_preserves_cancellation():
    """Verify that stopping a mission via adapter while client is disconnected results in CANCELLED state upon reconnect."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_stop_disc_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_stop_disc_{test_id}"

    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="RUNNING",
        attempt_number=1,
        execution_active=True,
    )
    bus.get_or_create_state(mission_id)
    bus.publish_durable(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id, attempt_number=1))

    # User issues Stop
    stopped = await adapter.stop_mission(mission_id)
    assert stopped is True

    # When client connects/reconnects and gets snapshot & events
    snap = adapter.get_mission_snapshot(mission_id)
    assert snap.mission.status == MissionStatus.CANCELLED
    events = adapter.get_events_since(mission_id, 0)
    assert any(e.event_type == EventType.MISSION_CANCELLED for e in events)


@pytest.mark.asyncio
async def test_scenario_n_resume_into_newer_attempt():
    """Verify resuming an interrupted mission increments attempt number and emits MISSION_RESUMED with attempt 2."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_res_att_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_res_att_{test_id}"

    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="CANCELLED",
        attempt_number=1,
        execution_active=False,
    )
    store = bus.get_or_create_state(mission_id)
    bus.publish_durable(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id, attempt_number=1))
    bus.publish_durable(HermesEvent(event_type=EventType.MISSION_CANCELLED, mission_id=mission_id, attempt_number=1))

    # Save snapshot so RecoveryEngine can formulate resume plan
    snap = store.get_snapshot()
    from core.persistence.serializer import serialize_runtime_state
    s_dict, s_hash = serialize_runtime_state(snap)
    db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="CANCELLED",
        snapshot_dict=s_dict,
        state_hash=s_hash,
        attempt_number=1,
    )

    # Resume interrupted mission
    new_run_id = await adapter.resume_interrupted_mission(mission_id)
    assert "run_2_" in new_run_id

    # Stop background task immediately to prevent background execution
    await adapter.stop_mission(mission_id)

    # Check that MISSION_RESUMED with attempt_number=2 exists
    events = adapter.get_events_since(mission_id, 0)
    resume_events = [e for e in events if e.event_type == EventType.MISSION_RESUMED]
    assert len(resume_events) == 1
    assert resume_events[0].attempt_number == 2
