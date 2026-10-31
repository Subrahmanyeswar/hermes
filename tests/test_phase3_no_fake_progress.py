"""
Phase 3 Test Suite: No Fabricated Activity & Honest Waiting State (Gate F / Scenario O).

Verifies:
- Scenario O: Quiet backend emits honest waiting states without fabricated progress.
- Authoritative wait reasons (e.g., WAITING_FOR_PROVIDER, WAITING_FOR_USER) are durably preserved.
- Sequence numbers do not advance spontaneously when backend is idle.
"""

import uuid
import tempfile
import asyncio
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import MissionStatus, WaitReason


def test_scenario_o_idle_backend_no_fabricated_events():
    """Verify that an idle backend produces 0 events and does not advance sequences."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_idle_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    mission_id = f"m_idle_{test_id}"

    store = bus.get_or_create_state(mission_id)

    # Initial state
    snap = store.get_snapshot()
    assert snap.state_version == 0
    assert snap.last_event_sequence == 0

    # Retrieve events from SQLite
    events = db.get_mission_events(mission_id)
    assert len(events) == 0

    # Verify no events persisted in SQLite
    db_events = db.get_mission_events(mission_id)
    assert len(db_events) == 0


def test_scenario_o_truthful_waiting_state():
    """Verify that legitimate waiting states (e.g. WAITING_FOR_PROVIDER) are recorded honestly without fake progress."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_wait_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    mission_id = f"m_wait_{test_id}"

    store = bus.get_or_create_state(mission_id)

    # Emit MISSION_STARTED
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"mission_id": mission_id, "prompt": "Process data"}
    ))

    # Emit MISSION_WAITING with provider backoff reason
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_WAITING,
        mission_id=mission_id,
        payload={
            "wait_reason": "WAITING_FOR_PROVIDER",
            "detail": "NVIDIA NIM rate limit backoff: 30s",
        }
    ))

    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.WAITING
    assert snap.progress.waiting_reason == WaitReason.WAITING_FOR_PROVIDER

    # Ensure no fabricated progress completed the mission
    assert snap.mission.is_terminal is False
    assert snap.progress.overall_fraction < 1.0 or snap.progress.overall_fraction == 0.0

    # Ensure database snapshot reflects WAITING truthfully
    db_events = db.get_mission_events(mission_id)
    assert len(db_events) == 2
    assert db_events[1]["event_type"] == EventType.MISSION_WAITING.value
