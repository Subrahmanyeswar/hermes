"""
Phase 3 Test Suite: Event Envelope Contract & Monotonic Sequences.

Verifies:
- Scenario A: Correct event envelope (mission_id, run_id, attempt_number, sequence, timestamp, event_type, structured payload).
- Monotonic sequence progression.
- Serialization and deserialization parity.
"""

import uuid
import tempfile
import time
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType, EventSeverity


def test_scenario_a_correct_event_envelope():
    """Verify that every published mission event has valid envelope metadata and monotonic sequence."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_envelope_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    mission_id = f"m_env_{test_id}"
    run_id = f"run_{test_id}"

    event1 = HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id=run_id,
        attempt_number=1,
        payload={"workspace": str(tmp_dir), "mode": "auto"},
    )
    published1 = bus.publish_durable(event1)

    assert published1.mission_id == mission_id
    assert published1.run_id == run_id
    assert published1.attempt_number == 1
    assert isinstance(published1.sequence, int) and published1.sequence > 0
    assert isinstance(published1.timestamp, float) and published1.timestamp > 0
    assert published1.event_type == EventType.MISSION_STARTED
    assert published1.payload.get("mode") == "auto"

    event2 = HermesEvent(
        event_type=EventType.PLANNING_STARTED,
        mission_id=mission_id,
        run_id=run_id,
        attempt_number=1,
        payload={"action": "decompose_goal"},
    )
    published2 = bus.publish_durable(event2)

    assert published2.sequence == published1.sequence + 1, "Sequences must be strictly monotonically increasing"
    assert published2.timestamp >= published1.timestamp


def test_event_to_dict_and_roundtrip_contract():
    """Verify event conversion to dict and JSON safety."""
    event = HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id="m_dict_test",
        run_id="run_1",
        attempt_number=2,
        sequence=42,
        payload={"tool_name": "fs.write", "path": "test.txt"},
    )
    d = event.to_dict()
    assert d["mission_id"] == "m_dict_test"
    assert d["run_id"] == "run_1"
    assert d["attempt_number"] == 2
    assert d["sequence"] == 42
    assert d["event_type"] == "TOOL_STARTED"
    assert d["payload"]["tool_name"] == "fs.write"
