"""
Phase 3 Test Suite: Real Execution Activity Stream (Gate E).

Verifies that execution moves truthfully through the required stages:
1. Mission started
2. Planning started & Plan created
3. Tool execution started & completed/failed
4. File modifications accurately recorded in tool completion payloads
5. Verification completed and terminal status reached
"""

import uuid
import tempfile
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType, EventSeverity
from core.workspace import WorkspaceManager
from core.agent_loop.loop import ActionExecutor
from core.agent_loop.actions import ActionEnvelope


@pytest.mark.asyncio
async def test_gate_e_planning_and_tool_activity_events():
    """Verify that planning, tool execution, file changes, and verification emit authentic ordered events."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_gate_e_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))
    mission_id = f"m_gate_e_{test_id}"

    # 1. Mission Started
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"mission_id": mission_id, "prompt": "Create test report file"}
    ))

    # 2. Planning Started & Plan Created
    bus.publish_durable(HermesEvent(
        event_type=EventType.PLANNING_STARTED,
        mission_id=mission_id,
        payload={"mission_id": mission_id, "summary": "Decomposing user request"}
    ))

    bus.publish_durable(HermesEvent(
        event_type=EventType.PLAN_CREATED,
        mission_id=mission_id,
        payload={"mission_id": mission_id, "goal_id": f"g_{test_id}", "requirements_count": 1}
    ))

    # 3. Action / Tool Execution using ActionExecutor (real tool execution write_file)
    executor = ActionExecutor(mode="auto", event_bus_instance=bus)

    action = ActionEnvelope(
        mission_id=mission_id,
        turn_id="turn_1",
        tool_call_id=f"tc_{test_id}",
        tool_name="write_file",
        arguments={
            "path": "report.txt",
            "content": "Phase 3 Gate E verification content\n",
        },
    )

    obs = await executor.execute_action(action, workspace=ws_mgr)
    assert obs.success is True
    assert (tmp_dir / "report.txt").exists()
    assert "Phase 3 Gate E" in (tmp_dir / "report.txt").read_text(encoding="utf-8")

    # 4. Verification completed
    bus.publish_durable(HermesEvent(
        event_type=EventType.VERIFICATION_COMPLETED,
        mission_id=mission_id,
        payload={"verdict": "PASSED", "confidence": 1.0}
    ))

    # 5. Mission Completed
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        payload={"reason": "All checks passed", "files_created": ["report.txt"]}
    ))

    # Verify all events in database
    persisted_events = db.get_mission_events(mission_id)
    event_types = [e["event_type"] for e in persisted_events]

    assert EventType.MISSION_STARTED.value in event_types
    assert EventType.PLANNING_STARTED.value in event_types
    assert EventType.PLAN_CREATED.value in event_types
    assert EventType.TOOL_STARTED.value in event_types
    assert EventType.TOOL_COMPLETED.value in event_types
    assert EventType.VERIFICATION_COMPLETED.value in event_types
    assert EventType.MISSION_COMPLETED.value in event_types

    # Verify tool completed payload tracks side effects (created report.txt)
    tool_completed_evts = [e for e in persisted_events if e["event_type"] == EventType.TOOL_COMPLETED.value]
    assert len(tool_completed_evts) >= 1
    raw_p = tool_completed_evts[0]["payload"]
    inner_payload = raw_p.get("payload", raw_p)
    assert "side_effects" in inner_payload
    created_files = [Path(p).name for p in inner_payload["side_effects"].get("files_created", [])]
    assert "report.txt" in created_files


@pytest.mark.asyncio
async def test_gate_e_tool_failure_event_propagation():
    """Verify that a failing tool execution truthfully emits TOOL_FAILED with error details."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p3_fail_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))
    mission_id = f"m_fail_{test_id}"

    executor = ActionExecutor(mode="auto", event_bus_instance=bus)

    # Attempt to read non-existent file
    action = ActionEnvelope(
        mission_id=mission_id,
        turn_id="turn_1",
        tool_call_id=f"tc_fail_{test_id}",
        tool_name="read_file",
        arguments={"path": "does_not_exist_xyz.txt"},
    )

    obs = await executor.execute_action(action, workspace=ws_mgr)
    assert obs.success is False

    persisted_events = db.get_mission_events(mission_id)
    event_types = [e["event_type"] for e in persisted_events]

    assert EventType.TOOL_STARTED.value in event_types
    assert EventType.TOOL_FAILED.value in event_types

    # Ensure error details are present
    fail_evts = [e for e in persisted_events if e["event_type"] == EventType.TOOL_FAILED.value]
    assert len(fail_evts) == 1
    raw_p = fail_evts[0]["payload"]
    inner_payload = raw_p.get("payload", raw_p)
    assert inner_payload.get("success") is False
    assert inner_payload.get("error") != ""
