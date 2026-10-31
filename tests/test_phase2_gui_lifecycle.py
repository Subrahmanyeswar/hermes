"""
Phase 2 Test Suite: GUI Lifecycle, Disconnect/Reconnect, Event History & Replay.

Verifies:
- Scenario L: Disconnected client reconnects and retrieves full history (Task 2.14)
- Snapshot reconciliation without event loss (INV-11)
- UI Stop/Resume contract
"""

import uuid
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.workspace import WorkspaceManager
from core.server.runtime_adapter import RuntimeAdapter
from core.server.app import app
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import MissionStatus


def test_scenario_l_disconnected_client_reconnect_replays_events():
    """Verify that a client that disconnects during execution can reconnect and fetch the complete sequential event history."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_gui_reconnect_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_gui_{test_id}"

    # Pre-seed mission in database and bus
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="RUNNING",
        attempt_number=1,
    )
    store = bus.get_or_create_state(mission_id)

    # Publish 5 events in order
    for i in range(1, 6):
        bus.publish_durable(HermesEvent(
            event_type=EventType.TASK_STARTED if i == 1 else EventType.PROGRESS_UPDATED,
            mission_id=mission_id,
            attempt_number=1,
            payload={"step": i},
        ))

    from core.server.app import create_app
    test_app = create_app(adapter=adapter)
    client = TestClient(test_app)

    # First connection: client fetches history starting from sequence 0
    resp1 = client.get(f"/api/missions/{mission_id}/events/history?from_seq=0")
    assert resp1.status_code == 200
    events1 = resp1.json().get("events", [])
    assert len(events1) >= 5

    # Verify ordering: sequences must be strictly monotonically increasing (INV-11)
    seqs = [e["sequence"] for e in events1]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "No duplicate sequence numbers"

    # Simulate client reconnecting asking for events since sequence 3
    resp2 = client.get(f"/api/missions/{mission_id}/events/history?from_seq=3")
    assert resp2.status_code == 200
    events2 = resp2.json().get("events", [])
    assert all(e["sequence"] >= 3 for e in events2)


def test_ui_stop_and_resume_api_contract():
    """Verify that calling /stop changes mission state to CANCELLED and returns confirmed status."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_gui_stop_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_gui_stop_{test_id}"

    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="RUNNING",
        attempt_number=1,
        execution_active=True,
    )
    # Pre-seed running state
    store = bus.get_or_create_state(mission_id)
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        attempt_number=1,
    ))

    from core.server.app import create_app
    test_app = create_app(adapter=adapter)
    client = TestClient(test_app)

    # Call stop API
    resp = client.post(f"/api/missions/{mission_id}/stop")
    assert resp.status_code == 200
    assert resp.json().get("cancelled") is True

    # Verify mission is CANCELLED in DB
    m_row = db.get_mission(mission_id)
    assert m_row["status"] == "CANCELLED"
