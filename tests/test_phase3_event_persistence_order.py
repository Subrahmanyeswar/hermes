"""
Phase 3 Test Suite: Durability Before Broadcast & Persistence Fault Injection.

Verifies:
- Scenario B: Persistence failure prevents event from being broadcast as durable (Gate B).
- Scenario C: Crash between persistence and broadcast is recoverable from durable history (Gate B).
"""

import uuid
import tempfile
from pathlib import Path
import unittest.mock
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType
from core.persistence.models import ToolPersistenceError


def test_scenario_b_persistence_failure_prevents_broadcast():
    """Verify that if database persistence fails, publish_durable raises ToolPersistenceError and does not broadcast."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_fail_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    mission_id = f"m_fail_{test_id}"

    received_events = []
    bus.subscribe(lambda e: received_events.append(e))

    # Mock append_mission_event to throw disk error
    with unittest.mock.patch.object(db, "append_mission_event", side_effect=IOError("Disk I/O failure")):
        event = HermesEvent(
            event_type=EventType.TOOL_STARTED,
            mission_id=mission_id,
            payload={"tool_name": "fs.write"},
        )
        with pytest.raises(ToolPersistenceError, match="Failed to durably commit event"):
            bus.publish_durable(event)

    # Invariant: subscriber must NOT have received the failed event
    assert len(received_events) == 0, "Failed event must not be broadcast to subscribers"

    # Memory history must NOT contain the failed event
    replayed = bus.replay(mission_id)
    assert len(replayed) == 0


def test_scenario_c_crash_between_persistence_and_broadcast_recoverable_from_history():
    """Verify that if an event is committed to SQLite but process halts before live broadcast, history recovery retrieves it."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_crash_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    mission_id = f"m_crash_{test_id}"

    # Write event directly to SQLite journal simulating crash right after database write
    persisted_event = HermesEvent(
        event_type=EventType.TASK_COMPLETED,
        mission_id=mission_id,
        sequence=1,
        attempt_number=1,
        payload={"task_id": "task_1", "result": "ok"},
    )
    db.append_mission_event(persisted_event)

    # Reconnect new client on clean startup
    new_bus = EventBus(db=db)
    recovered = new_bus.replay(mission_id, from_seq=0)

    assert len(recovered) == 1
    assert recovered[0].event_type == EventType.TASK_COMPLETED
    assert recovered[0].sequence == 1
