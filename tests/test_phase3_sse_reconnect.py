"""
Phase 3 Test Suite: SSE Delivery, Reconnect, and Cross-Mission Isolation.

Verifies:
- Scenario D: SSE subscriber receives mission events in order (Gate C).
- Scenario J: Disconnect and reconnect using sequence cursor (Gate C).
- Scenario L: Cross-mission isolation: events for mission A do not appear in mission B (Gate C).
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


@pytest.mark.asyncio
async def test_scenario_d_sse_subscriber_receives_events_in_order():
    """Verify that an SSE subscriber queue receives streamed mission events in strict sequence order."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_sse_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_sse_{test_id}"

    # Connect subscriber generator
    gen = adapter.subscribe_mission_events(mission_id, last_sequence=0)

    # Publish 3 events
    e1 = bus.publish_durable(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id))
    e2 = bus.publish_durable(HermesEvent(event_type=EventType.PLANNING_STARTED, mission_id=mission_id))
    e3 = bus.publish_durable(HermesEvent(event_type=EventType.PLAN_CREATED, mission_id=mission_id))

    # Pull 3 events from generator
    received = []
    for _ in range(3):
        evt = await asyncio.wait_for(anext(gen), timeout=2.0)
        received.append(evt)

    await gen.aclose()

    assert len(received) == 3
    assert [e.sequence for e in received] == [e1.sequence, e2.sequence, e3.sequence]
    assert received[0].event_type == EventType.MISSION_STARTED
    assert received[1].event_type == EventType.PLANNING_STARTED
    assert received[2].event_type == EventType.PLAN_CREATED


@pytest.mark.asyncio
async def test_scenario_j_disconnect_and_reconnect_replays_missed_events():
    """Verify that reconnecting with a sequence cursor yields all intermediate missed events."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_recon_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    mission_id = f"m_recon_{test_id}"

    # Initial events 1, 2
    e1 = bus.publish_durable(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mission_id))
    e2 = bus.publish_durable(HermesEvent(event_type=EventType.TASK_STARTED, mission_id=mission_id))

    # Client was connected and saw events up to e1
    # Now client reconnects specifying last_sequence = e1.sequence
    reconnect_gen = adapter.subscribe_mission_events(mission_id, last_sequence=e1.sequence)

    # Meanwhile event 3 was emitted
    e3 = bus.publish_durable(HermesEvent(event_type=EventType.TASK_COMPLETED, mission_id=mission_id))

    # Reconnect stream must yield e2 and e3
    r1 = await asyncio.wait_for(anext(reconnect_gen), timeout=2.0)
    r2 = await asyncio.wait_for(anext(reconnect_gen), timeout=2.0)
    await reconnect_gen.aclose()

    assert r1.sequence == e2.sequence
    assert r2.sequence == e3.sequence


@pytest.mark.asyncio
async def test_scenario_l_cross_mission_isolation():
    """Verify that events published for mission A are never yielded to mission B subscribers."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_iso_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)

    mA = f"mA_{test_id}"
    mB = f"mB_{test_id}"

    genB = adapter.subscribe_mission_events(mB, last_sequence=0)

    # Publish events to mA
    bus.publish_durable(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mA))
    bus.publish_durable(HermesEvent(event_type=EventType.TASK_STARTED, mission_id=mA))

    # Publish 1 event to mB
    bus.publish_durable(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=mB))

    # Subscriber for mB must only receive the mB event
    evt_B = await asyncio.wait_for(anext(genB), timeout=2.0)
    await genB.aclose()

    assert evt_B.mission_id == mB
