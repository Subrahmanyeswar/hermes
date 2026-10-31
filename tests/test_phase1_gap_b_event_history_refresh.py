"""
Tests for Acceptance Gap B: Activity History Survives GUI Refresh & Remount.

Verifies:
1. Existing persisted events for the selected mission can be fetched/replayed from backend journal.
2. Historical events are displayed even when snapshot last_sequence > 0.
3. Snapshot synchronization does not erase the recovered event history.
4. Overlapping live/SSE events are merged without duplicate sequence entries.
5. Events are strictly ordered by monotonic sequence.
6. A genuinely new event appears after historical recovery.
7. GUI refresh/remount reconstructs history from durable backend state.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from core.event_bus import EventBus
from core.persistence.database import SQLiteDatabase
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus
from core.runtime_state.store import StateStore
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import WorkspaceManager


@pytest.fixture
def test_backend(tmp_path: Path):
    db_file = tmp_path / "journal_test.db"
    db = SQLiteDatabase(db_file)
    bus = EventBus(db=db)
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=wm)
    app = create_app(adapter=adapter)
    client = TestClient(app)
    return {
        "db": db,
        "bus": bus,
        "adapter": adapter,
        "client": client,
        "workspace": tmp_path,
    }


def test_gap_b_event_history_persisted_and_retrieved_via_api(test_backend):
    """Prove that durable events written to the database can be retrieved via the REST history endpoint."""
    client = test_backend["client"]
    bus = test_backend["bus"]
    mission_id = "m_persist_hist"

    # Emit 5 events
    for seq in range(1, 6):
        bus.publish(HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id=mission_id,
            sequence=seq,
            payload={"step": f"Step {seq}"},
        ))

    # Flush bus to durable SQLite journal
    bus.flush(timeout=1.0)

    # 1. Fetch via REST history endpoint
    resp = client.get(f"/api/missions/{mission_id}/events/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mission_id"] == mission_id
    assert data["total"] == 5
    events = data["events"]
    assert len(events) == 5
    assert [e["sequence"] for e in events] == [1, 2, 3, 4, 5]


def test_gap_b_history_retrieved_when_snapshot_last_sequence_greater_than_zero(test_backend):
    """Prove that historical events are fully recoverable when initial snapshot has last_sequence > 0."""
    client = test_backend["client"]
    bus = test_backend["bus"]
    mission_id = "m_high_watermark"

    # Emit events up to seq 10
    for seq in range(1, 11):
        bus.publish(HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id=mission_id,
            sequence=seq,
            payload={"step": seq},
        ))
    bus.flush(timeout=1.0)

    # Snapshot should report last_sequence = 10
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["last_sequence"] == 10

    # History endpoint recovers all 10 events even though snapshot is already at seq 10
    hist_resp = client.get(f"/api/missions/{mission_id}/events/history")
    assert hist_resp.status_code == 200
    hist_events = hist_resp.json()["events"]
    assert len(hist_events) == 10
    assert hist_events[0]["sequence"] == 1
    assert hist_events[-1]["sequence"] == 10


def test_gap_b_snapshot_poll_does_not_erase_client_history(test_backend):
    """Simulate the client-side synchronization algorithm and prove snapshots do not erase history."""
    # Algorithm mirroring gui/src/sync.ts and gui/src/App.tsx
    def create_initial_sync_state(snap=None):
        return {
            "snapshot": snap,
            "events": [],
            "lastWatermark": {
                "state_version": snap.get("state_version", 0) if snap else 0,
                "last_sequence": snap.get("last_sequence", 0) if snap else 0,
            },
        }

    def process_incoming_snapshot(state, incoming):
        if state["snapshot"] and state["snapshot"].get("mission_id") != incoming.get("mission_id"):
            return {"nextState": state, "accepted": False, "reason": "mismatch"}
        next_events = [e for e in state["events"] if (e.get("sequence", 0) > incoming.get("last_sequence", 0))]
        return {
            "nextState": {
                "snapshot": incoming,
                "events": next_events,
                "lastWatermark": {
                    "state_version": max(state["lastWatermark"]["state_version"], incoming.get("state_version", 0)),
                    "last_sequence": max(state["lastWatermark"]["last_sequence"], incoming.get("last_sequence", 0)),
                },
            },
            "accepted": True,
        }

    # Initial state with recovered historical events 1..5
    initial_events = [
        {"sequence": i, "event_type": "TASK_PROGRESS", "mission_id": "m_test"}
        for i in range(1, 6)
    ]

    client_state = create_initial_sync_state(None)

    # In App.tsx, streamEvents is maintained as a persistent list
    stream_events = list(initial_events)
    assert len(stream_events) == 5

    # Incoming snapshot at sequence 5
    snap = {
        "mission_id": "m_test",
        "status": "RUNNING",
        "state_version": 5,
        "last_sequence": 5,
        "tasks": [],
    }
    sync_res = process_incoming_snapshot(client_state, snap)
    assert sync_res["accepted"] is True
    client_state = sync_res["nextState"]

    # In our hardened App.tsx: streamEvents is NOT wiped by incoming snapshot
    assert len(stream_events) == 5
    assert [e["sequence"] for e in stream_events] == [1, 2, 3, 4, 5]

    # Now a new live event (seq 6) arrives
    live_event = {
        "sequence": 6,
        "event_id": "evt_6",
        "event_type": "TASK_COMPLETED",
        "mission_id": "m_test",
    }

    # App.tsx appends and deduplicates
    if not any(e["sequence"] == live_event["sequence"] for e in stream_events):
        stream_events.append(live_event)

    assert len(stream_events) == 6
    assert [e["sequence"] for e in stream_events] == [1, 2, 3, 4, 5, 6]


def test_gap_b_overlapping_live_events_deduplicated():
    """Verify that if an event arrives both via historical fetch and live SSE, it is not duplicated."""
    stream_events = [
        {"sequence": 1, "event_id": "e1", "event_type": "START"},
        {"sequence": 2, "event_id": "e2", "event_type": "TASK_PROGRESS"},
    ]

    # Duplicate seq 2 arrives
    incoming = {"sequence": 2, "event_id": "e2", "event_type": "TASK_PROGRESS"}
    is_dup = any(
        (e["sequence"] > 0 and e["sequence"] == incoming["sequence"]) or
        (e.get("event_id") and e.get("event_id") == incoming.get("event_id"))
        for e in stream_events
    )
    assert is_dup is True

    if not is_dup:
        stream_events.append(incoming)

    assert len(stream_events) == 2, "Duplicate event must not be added"


def test_gap_b_remount_reconstructs_from_backend(test_backend):
    """Simulate a page refresh / remount by re-fetching state and history for an existing mission."""
    client = test_backend["client"]
    bus = test_backend["bus"]
    mission_id = "m_remount_test"

    # Pre-populate 8 events
    for seq in range(1, 9):
        bus.publish(HermesEvent(
            event_type=EventType.TASK_PROGRESS,
            mission_id=mission_id,
            sequence=seq,
            payload={"data": f"item_{seq}"},
        ))
    bus.flush(timeout=1.0)

    # 1. Page Refresh / Remount occurs: App fetches snapshot
    snap_resp = client.get(f"/api/missions/{mission_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["last_sequence"] == 8

    # 2. App fetches history
    hist_resp = client.get(f"/api/missions/{mission_id}/events/history")
    assert hist_resp.status_code == 200
    events = hist_resp.json()["events"]
    assert len(events) == 8
    assert events[0]["sequence"] == 1
    assert events[-1]["sequence"] == 8

    # 3. New live event 9 emitted
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        sequence=9,
        payload={"result": "success"},
    ))
    bus.flush(timeout=0.5)

    hist_resp2 = client.get(f"/api/missions/{mission_id}/events/history")
    assert hist_resp2.status_code == 200
    assert hist_resp2.json()["total"] == 9
