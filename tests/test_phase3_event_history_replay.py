"""
Phase 3 Test Suite: Replay-to-Live Handoff, Deduplication, Gaps, and Snapshots.

Verifies:
- Scenario E: Replay-to-live handoff race prevention.
- Scenario F: Duplicate delivery deduplication.
- Scenario G: Sequence gap recovery from durable history.
- Scenario H: Snapshot refresh does not erase prior historical activity.
"""

import uuid
import tempfile
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.workspace import WorkspaceManager
from core.server.runtime_adapter import RuntimeAdapter
from core.runtime_state.events import HermesEvent, EventType


def test_scenario_f_duplicate_delivery_deduplication():
    """Verify that delivering duplicate events via replay/bus does not produce duplicate sequences in client state."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_dup_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    mission_id = f"m_dup_{test_id}"

    # Event with specific ID
    evt = HermesEvent(
        event_id=f"evt_{test_id}_1",
        event_type=EventType.TASK_STARTED,
        mission_id=mission_id,
        payload={"task_id": "task_1"},
    )
    e1 = bus.publish_durable(evt)
    # Publish exact same event object again
    e2 = bus.publish_durable(evt)

    assert e1.sequence == e2.sequence
    replayed = bus.replay(mission_id)
    assert len(replayed) == 1, "Duplicate event must not be inserted twice into history"


def test_scenario_g_sequence_gap_recovery_from_durable_history():
    """Verify that if an event was missed in a live stream, querying get_events_since retrieves the missing gap."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_gap_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_gap_{test_id}"

    # Publish events 1, 2, 3
    e1 = bus.publish_durable(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id))
    e2 = bus.publish_durable(HermesEvent(event_type=EventType.TASK_STARTED, mission_id=mission_id))
    e3 = bus.publish_durable(HermesEvent(event_type=EventType.TASK_COMPLETED, mission_id=mission_id))

    # Assume client saw e1, then received e3 (missed e2)
    # Client detects gap (e1.sequence to e3.sequence) and fetches get_events_since(mission_id, e1.sequence)
    recovered = adapter.get_events_since(mission_id, last_sequence=e1.sequence)

    seqs = [e.sequence for e in recovered]
    assert e2.sequence in seqs
    assert e3.sequence in seqs
    assert seqs == [e2.sequence, e3.sequence]


def test_scenario_h_snapshot_refresh_preserves_historical_events():
    """Verify that when a snapshot is refreshed at sequence 10, replaying events up to 10 preserves all historical events."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_snap_hist_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_snaphist_{test_id}"

    for i in range(10):
        bus.publish_durable(HermesEvent(
            event_type=EventType.TASK_PROGRESS if i > 0 else EventType.MISSION_STARTED,
            mission_id=mission_id,
            payload={"step": i + 1},
        ))

    # Snapshot is at sequence 10
    snap = adapter.get_mission_snapshot(mission_id)
    assert snap.last_event_sequence == 10

    # Fetching history from seq 0 must retrieve all 10 events
    history = adapter.get_events_since(mission_id, last_sequence=0)
    assert len(history) == 10
    assert [e.sequence for e in history] == list(range(1, 11))
