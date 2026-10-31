"""
Phase 2 Test Suite: Stale Worker & Delayed Event Fencing.

Verifies:
- Scenario F: Stale attempt event rejected (INV-09, Task 2.10)
- Scenario K: Delayed event cannot resurrect terminal mission (INV-10, Task 2.11)
- Attempt/run identity fencing
"""

import uuid
import tempfile
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import MissionStatus


def test_scenario_f_stale_attempt_event_rejected():
    """Verify that an event emitted by an earlier attempt (attempt 1) is rejected when state is at attempt 2."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_fencing_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    mission_id = f"m_fence_{test_id}"

    store = bus.get_or_create_state(mission_id)

    # Mission starts attempt 1
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        attempt_number=1,
    ))

    # Mission fails or is cancelled
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id,
        attempt_number=1,
        payload={"error": "transient timeout"},
    ))

    # Mission resumed under attempt 2
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_RESUMED,
        mission_id=mission_id,
        attempt_number=2,
    ))

    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.RUNNING
    assert snap.mission.attempt_number == 2

    # Now a delayed/stale event from attempt 1 arrives: e.g. a tool completion or error from attempt 1
    stale_event = HermesEvent(
        event_type=EventType.TOOL_FAILED,
        mission_id=mission_id,
        attempt_number=1,
        payload={"error": "stale worker failed"},
    )
    bus.publish_durable(stale_event)

    # State must NOT be mutated by attempt 1 stale event
    snap_after = store.get_snapshot()
    assert snap_after.mission.status == MissionStatus.RUNNING
    assert snap_after.mission.attempt_number == 2


def test_scenario_k_delayed_event_cannot_resurrect_terminal_mission():
    """Verify that delayed events cannot transition a completed or terminal mission back to active."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_resurrect_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    mission_id = f"m_resurrect_{test_id}"

    store = bus.get_or_create_state(mission_id)

    # Mission completes cleanly
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        attempt_number=1,
    ))
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        attempt_number=1,
    ))

    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.COMPLETED

    # Out-of-order delayed events arrive from network or async queues
    bus.publish_durable(HermesEvent(
        event_type=EventType.TASK_STARTED,
        mission_id=mission_id,
        attempt_number=1,
        payload={"task_id": "late_task"},
    ))
    bus.publish_durable(HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id=mission_id,
        attempt_number=1,
        payload={"tool_name": "late_tool"},
    ))

    # Must remain strictly terminal
    snap_after = store.get_snapshot()
    assert snap_after.mission.status == MissionStatus.COMPLETED
