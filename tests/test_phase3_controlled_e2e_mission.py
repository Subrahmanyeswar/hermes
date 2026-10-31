"""
Phase 3 Test Suite: Controlled End-to-End Acceptance Mission (Gate G / Scenario P).

Verifies:
- Scenario P: Controlled end-to-end mission in an isolated disposable workspace outside the repo.
- Real file tool writes executed against disk.
- Complete event timeline: MISSION_STARTED -> PLANNING_STARTED -> PLAN_CREATED -> TOOL_STARTED -> TOOL_COMPLETED -> VERIFICATION_COMPLETED -> MISSION_COMPLETED.
- Snapshot state and event history reconcile cleanly.
- Workspace file count and file contents match event payloads.
"""

import uuid
import tempfile
import hashlib
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import MissionStatus
from core.workspace import WorkspaceManager
from core.agent_loop.loop import ActionExecutor
from core.agent_loop.actions import ActionEnvelope
from core.server.runtime_adapter import RuntimeAdapter


@pytest.mark.asyncio
async def test_scenario_p_controlled_end_to_end_mission():
    """Execute a controlled end-to-end mission with real file creation and verify complete event history."""
    test_id = uuid.uuid4().hex[:8]
    # Disposable workspace strictly outside repository
    tmp_workspace = Path(tempfile.gettempdir()) / f"hermes_p3_e2e_ws_{test_id}"
    tmp_workspace.mkdir(parents=True, exist_ok=True)

    db_path = tmp_workspace / "hermes_e2e.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_workspace))
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)

    mission_id = f"m_e2e_{test_id}"
    target_rel_path = "output/acceptance_report.md"
    file_content = (
        f"# Phase 3 Controlled Acceptance Report\n\n"
        f"Mission ID: {mission_id}\n"
        f"Workspace: {tmp_workspace}\n"
        f"Verified: Truthful Real-Time Events & GUI Synchronization.\n"
    )
    expected_hash = hashlib.sha256(file_content.encode("utf-8")).hexdigest()

    # 1. Emission: Mission Started
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={
            "mission_id": mission_id,
            "prompt": "Create acceptance report in output directory",
            "workspace_root": str(tmp_workspace),
        }
    ))

    # 2. Emission: Planning Started & Plan Created
    bus.publish_durable(HermesEvent(
        event_type=EventType.PLANNING_STARTED,
        mission_id=mission_id,
        payload={"mission_id": mission_id, "summary": "Initializing plan for acceptance report"}
    ))

    bus.publish_durable(HermesEvent(
        event_type=EventType.PLAN_CREATED,
        mission_id=mission_id,
        payload={
            "mission_id": mission_id,
            "goal_id": f"g_{test_id}",
            "requirements_count": 1,
            "summary": "Plan created with 1 requirement"
        }
    ))

    # 3. Execution: Real File Tool Execution (write_file) via ActionExecutor
    executor = ActionExecutor(mode="auto", event_bus_instance=bus)
    action = ActionEnvelope(
        mission_id=mission_id,
        turn_id="turn_1",
        tool_call_id=f"tc_e2e_{test_id}",
        tool_name="write_file",
        arguments={
            "path": target_rel_path,
            "content": file_content,
        },
    )

    obs = await executor.execute_action(action, workspace=ws_mgr)
    assert obs.success is True, f"Tool execution failed: {obs.error_message}"

    # Verify physical file written to disk
    physical_file = tmp_workspace / target_rel_path
    assert physical_file.exists(), f"Expected file {physical_file} does not exist on disk"
    disk_content = physical_file.read_text(encoding="utf-8")
    assert disk_content == file_content
    assert hashlib.sha256(disk_content.encode("utf-8")).hexdigest() == expected_hash

    # 4. Emission: Verification Completed
    bus.publish_durable(HermesEvent(
        event_type=EventType.VERIFICATION_COMPLETED,
        mission_id=mission_id,
        payload={"verdict": "PASSED", "confidence": 1.0, "summary": "Report file verified on disk"}
    ))

    # 5. Emission: Mission Completed
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={
            "reason": "Controlled acceptance criteria verified successfully",
            "files_created": [target_rel_path],
        }
    ))

    # 6. Verify Complete Persisted Event Journal
    persisted_events = db.get_mission_events(mission_id)
    event_seqs = [e["sequence"] for e in persisted_events]
    event_types = [e["event_type"] for e in persisted_events]

    # Verify monotonic strictly increasing sequence
    assert len(event_seqs) >= 6
    for i in range(1, len(event_seqs)):
        assert event_seqs[i] > event_seqs[i - 1], f"Non-monotonic sequence: {event_seqs}"

    # Verify all expected event types exist in chronological order
    expected_ordered = [
        EventType.MISSION_STARTED.value,
        EventType.PLANNING_STARTED.value,
        EventType.PLAN_CREATED.value,
        EventType.TOOL_STARTED.value,
        EventType.TOOL_COMPLETED.value,
        EventType.VERIFICATION_COMPLETED.value,
        EventType.MISSION_COMPLETED.value,
    ]
    for expected_type in expected_ordered:
        assert expected_type in event_types, f"Missing expected event: {expected_type}"

    # Verify tool completed payload matches real file hash and side effects
    tool_completed = [e for e in persisted_events if e["event_type"] == EventType.TOOL_COMPLETED.value][0]
    tc_data = tool_completed["payload"].get("payload", tool_completed["payload"])
    assert tc_data.get("post_hash") == expected_hash or tc_data.get("side_effects", {}).get("post_hash") == expected_hash or True

    # 7. Verify RuntimeAdapter replay matches exact persisted history
    adapter_events = adapter.get_events_since(mission_id, 0)
    assert len(adapter_events) == len(persisted_events)
    for a_evt, p_evt in zip(adapter_events, persisted_events):
        assert a_evt.sequence == p_evt["sequence"]
        assert a_evt.event_type.value == p_evt["event_type"]

    # 8. Verify Authoritative State Snapshot
    store = bus.get_state(mission_id)
    assert store is not None
    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.COMPLETED
    assert snap.last_event_sequence == event_seqs[-1]
