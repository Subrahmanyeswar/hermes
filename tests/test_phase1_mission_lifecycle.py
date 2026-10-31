# tests/test_phase1_mission_lifecycle.py
"""
Deterministic Phase 1 Acceptance Test Suite for Canonical Mission Lifecycle and Run Control.

Scenarios Covered:
- Scenario A: Complete Legal Transition Graph Coverage (every valid transition verified).
- Scenario B: Comprehensive Illegal Transition Rejection (every forbidden transition rejected).
- Scenario C: Terminal-State Immutability (terminal states COMPLETED, FAILED, CANCELLED, ABORTED cannot be regressed).
- Scenario D: Mission Identity Stability and Monotonic Attempt Tracking (mission_id, run_id, attempt_number).
- Scenario E: Concurrent Run-Control Isolation (per-mission abort/cancellation does not leak across missions).
- Scenario F: Workspace Binding and Snapshot Consistency (Project Hub backward compatibility).
- Scenario G: Safe Run-Control Operations (Stop, Pause, Cancel, Resume semantics and eligibility contracts).
"""

import asyncio
import copy
import time
import uuid
import pytest
from pathlib import Path

from core.runtime_state.models import (
    HermesRuntimeState,
    MissionStatus,
    MissionState,
    MissionControlContext,
    LEGAL_MISSION_TRANSITIONS,
    is_legal_mission_transition,
    TaskStatus,
    WaitReason,
)
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.reducer import StateReducer
from core.server.runtime_adapter import RuntimeAdapter
from core.event_bus import EventBus
from core.workspace import WorkspaceManager
from core.mission_planner import Mission


# ── Scenario A: Complete Legal Transition Graph Coverage ───────────────────────

def test_scenario_a_legal_transition_graph():
    """Verify that every legal transition in LEGAL_MISSION_TRANSITIONS succeeds in StateReducer."""
    for origin_status, allowed_targets in LEGAL_MISSION_TRANSITIONS.items():
        for target_status in allowed_targets:
            state = HermesRuntimeState.create_empty(mission_id="m_test_legal", session_id="s_test")
            state.mission.status = origin_status

            # Map target status to a triggering event
            status_event_map = {
                MissionStatus.PLANNING: EventType.PLANNING_STARTED,
                MissionStatus.RUNNING: (
                    EventType.MISSION_RESUMED if origin_status == MissionStatus.PAUSED
                    else EventType.MISSION_STARTED
                ),
                MissionStatus.WAITING: EventType.MISSION_BLOCKED,
                MissionStatus.PAUSED: EventType.MISSION_PAUSED,
                MissionStatus.COMPLETING: EventType.MISSION_COMPLETING,
                MissionStatus.COMPLETED: EventType.MISSION_COMPLETED,
                MissionStatus.FAILED: EventType.MISSION_FAILED,
                MissionStatus.CANCELLED: EventType.MISSION_CANCELLED,
                MissionStatus.ABORTED: EventType.MISSION_ABORTED,
            }

            event_type = status_event_map.get(target_status)
            assert event_type is not None, f"Missing event mapping for {target_status}"

            evt = HermesEvent(
                event_type=event_type,
                mission_id="m_test_legal",
                payload={"reason": f"Transition from {origin_status} to {target_status}"},
            )

            reduced = StateReducer.reduce(state, evt)
            assert reduced.mission.status == target_status, (
                f"Expected legal transition {origin_status} -> {target_status} to produce {target_status}, "
                f"got {reduced.mission.status}"
            )
            assert "last_invalid_transition" not in reduced.metadata


# ── Scenario B: Comprehensive Illegal Transition Rejection ─────────────────────

def test_scenario_b_illegal_transition_rejection():
    """Verify that every forbidden transition is rejected without state corruption."""
    all_statuses = list(MissionStatus)
    for origin_status in all_statuses:
        allowed = LEGAL_MISSION_TRANSITIONS.get(origin_status, set())
        for target_status in all_statuses:
            if target_status == origin_status or target_status in allowed:
                continue

            # This transition is strictly ILLEGAL
            state = HermesRuntimeState.create_empty(mission_id="m_test_illegal", session_id="s_test")
            state.mission.status = origin_status

            status_event_map = {
                MissionStatus.CREATED: EventType.MISSION_CREATED,
                MissionStatus.PLANNING: EventType.PLANNING_STARTED,
                MissionStatus.RUNNING: EventType.MISSION_STARTED,
                MissionStatus.WAITING: EventType.MISSION_BLOCKED,
                MissionStatus.PAUSED: EventType.MISSION_PAUSED,
                MissionStatus.COMPLETING: EventType.MISSION_COMPLETING,
                MissionStatus.COMPLETED: EventType.MISSION_COMPLETED,
                MissionStatus.FAILED: EventType.MISSION_FAILED,
                MissionStatus.CANCELLED: EventType.MISSION_CANCELLED,
                MissionStatus.ABORTED: EventType.MISSION_ABORTED,
            }

            evt = HermesEvent(
                event_type=status_event_map[target_status],
                mission_id="m_test_illegal",
                payload={"reason": f"Illegal transition attempt from {origin_status} to {target_status}"},
            )

            reduced = StateReducer.reduce(state, evt)
            assert reduced.mission.status == origin_status, (
                f"Illegal transition {origin_status} -> {target_status} corrupted state to {reduced.mission.status}"
            )
            # If not in terminal guard (terminal guard returns early), metadata records the invalid transition
            if not origin_status in {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED, MissionStatus.ABORTED}:
                assert "last_invalid_transition" in reduced.metadata
                assert reduced.metadata["last_invalid_transition"]["from"] == origin_status.value
                assert reduced.metadata["last_invalid_transition"]["to"] == target_status.value


# ── Scenario C: Terminal-State Immutability ─────────────────────────────────────

def test_scenario_c_terminal_state_immutability():
    """Verify that once terminal, late events, tool completions, or restarts cannot alter status."""
    terminal_statuses = [
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
        MissionStatus.ABORTED,
    ]

    for term_status in terminal_statuses:
        state = HermesRuntimeState.create_empty(mission_id="m_term_test")
        state.mission.status = term_status
        assert state.mission.is_terminal is True

        # Try resurrecting via MISSION_STARTED
        resurrect_evt = HermesEvent(
            event_type=EventType.MISSION_STARTED,
            mission_id="m_term_test",
            payload={"prompt": "Restart mission"},
        )
        reduced = StateReducer.reduce(state, resurrect_evt)
        assert reduced.mission.status == term_status, "Late MISSION_STARTED must not resurrect terminal mission"
        assert reduced.mission.is_terminal is True

        # Try regressing via late TOOL_COMPLETED
        tool_evt = HermesEvent(
            event_type=EventType.TOOL_COMPLETED,
            mission_id="m_term_test",
            task_id="t1",
            payload={"tool_name": "bash", "result": "done"},
        )
        reduced2 = StateReducer.reduce(reduced, tool_evt)
        assert reduced2.mission.status == term_status, "Late TOOL_COMPLETED must not modify terminal status"

        # Try regressing via late PLANNING_STARTED
        plan_evt = HermesEvent(
            event_type=EventType.PLANNING_STARTED,
            mission_id="m_term_test",
        )
        reduced3 = StateReducer.reduce(reduced2, plan_evt)
        assert reduced3.mission.status == term_status, "Late PLANNING_STARTED must not modify terminal status"


# ── Scenario D: Mission Identity Stability and Monotonic Attempt Tracking ──────

def test_scenario_d_mission_identity_stability_and_run_correlation():
    """Verify mission_id stability, distinct run_id generation, and monotonic attempt tracking."""
    state = HermesRuntimeState.create_empty(
        mission_id="m_stable_123",
        session_id="sess_abc",
        run_id="run_1_abc123",
        attempt_number=1,
    )
    assert state.mission.mission_id == "m_stable_123"
    assert state.mission.run_id == "run_1_abc123"
    assert state.mission.attempt_number == 1

    # Apply event matching current run_id
    valid_run_evt = HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id="m_stable_123",
        run_id="run_1_abc123",
        attempt_number=1,
        sequence=1,
    )
    s1 = StateReducer.reduce(state, valid_run_evt)
    assert s1.mission.status == MissionStatus.RUNNING

    # Apply stale run event with mismatched run_id (should be dropped)
    stale_run_evt = HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id="m_stable_123",
        run_id="run_0_stale_old",
        attempt_number=0,
        sequence=2,
    )
    s2 = StateReducer.reduce(s1, stale_run_evt)
    assert s2.mission.status == MissionStatus.RUNNING, "Stale run event from mismatched run_id must be ignored"

    # Apply cross-mission event (should be dropped)
    cross_mission_evt = HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id="m_other_unrelated",
        run_id="run_1_abc123",
        sequence=3,
    )
    s3 = StateReducer.reduce(s2, cross_mission_evt)
    assert s3.mission.status == MissionStatus.RUNNING, "Cross-mission event must be ignored"

    # Monotonic attempt progression on new run
    s3.mission.run_id = "run_2_retry456"
    retry_evt = HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id="m_stable_123",
        run_id="run_2_retry456",
        attempt_number=2,
        sequence=4,
    )
    s4 = StateReducer.reduce(s3, retry_evt)
    assert s4.mission.run_id == "run_2_retry456"
    assert s4.mission.attempt_number == 2


# ── Scenario E: Concurrent Run-Control Isolation ───────────────────────────────

@pytest.mark.asyncio
async def test_scenario_e_concurrent_run_control_isolation(tmp_path):
    """Verify that multiple concurrent missions have completely isolated cancellation controls."""
    bus = EventBus()
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=wm)

    # Launch first mission
    m1_id = await adapter.start_mission("Task 1 in workspace", workspace_root=str(tmp_path))

    # In Phase 2 (Task 2.1 / INV-01), starting a second mission while m1 is running is rejected under single-mission policy
    with pytest.raises(RuntimeError, match="single-mission policy"):
        await adapter.start_mission("Task 2 in workspace", workspace_root=str(tmp_path))

    # Stop mission 1
    stopped_m1 = await adapter.stop_mission(m1_id)
    assert stopped_m1 is True

    # Now that m1 is stopped, launching mission 2 is allowed and gets fresh isolated control
    m2_id = await adapter.start_mission("Task 2 in workspace", workspace_root=str(tmp_path))

    assert m1_id != m2_id
    assert m1_id in adapter._mission_controls
    assert m2_id in adapter._mission_controls

    ctrl1 = adapter._mission_controls[m1_id]
    ctrl2 = adapter._mission_controls[m2_id]

    assert ctrl1.run_id != ctrl2.run_id
    assert ctrl1.abort_event is not ctrl2.abort_event

    # Mission 1 is aborted/terminal, Mission 2 is active
    assert ctrl1.abort_event.is_set() is True
    assert ctrl1.is_cancelled is True
    assert ctrl1.is_terminal is True

    assert ctrl2.abort_event.is_set() is False
    assert ctrl2.is_cancelled is False

    # Clean up mission 2
    await adapter.stop_mission(m2_id)
    assert ctrl2.abort_event.is_set() is True


# ── Scenario F: Workspace Binding and Snapshot Consistency ─────────────────────

def test_scenario_f_workspace_binding_and_snapshot_fields(tmp_path):
    """Verify that MissionState and Mission preserve workspace bindings and run identities."""
    ws_path = str(tmp_path.resolve())
    mission = Mission(
        mission_id="m_ws_bind_test",
        run_id="run_1_bind",
        attempt_number=1,
        user_prompt="Inspect files",
        workspace_root=ws_path,
    )
    assert mission.workspace_root == ws_path
    assert mission.run_id == "run_1_bind"
    assert mission.attempt_number == 1

    state = HermesRuntimeState.create_empty(
        mission_id="m_ws_bind_test",
        run_id="run_1_bind",
        attempt_number=1,
    )
    state.mission.workspace_root = ws_path
    state_dict = state.to_dict()
    assert state_dict["mission"]["workspace_root"] == ws_path
    assert state_dict["mission"]["run_id"] == "run_1_bind"
    assert state_dict["mission"]["attempt_number"] == 1


# ── Scenario G: Safe Run-Control Operations and Eligibility ─────────────────────

def test_scenario_g_run_control_pause_resume_contracts():
    """Verify precise definitions of Stop, Pause, Cancel, and Resume eligibility."""
    abort_evt = asyncio.Event()
    pause_evt = asyncio.Event()
    pause_evt.set()

    ctx = MissionControlContext(
        mission_id="m_control_test",
        run_id="run_1_ctrl",
        attempt_number=1,
        abort_event=abort_evt,
        pause_event=pause_evt,
    )

    # Initial active state
    assert ctx.is_paused is False
    assert ctx.is_cancelled is False
    assert ctx.is_terminal is False

    # 1. Request Pause
    ctx.request_pause()
    assert ctx.pause_requested is True
    assert ctx.is_paused is False
    assert pause_evt.is_set() is False
    assert ctx.is_terminal is False

    # Confirm Pause at safe checkpoint boundary
    ctx.confirm_pause()
    assert ctx.is_paused is True
    assert ctx.pause_requested is False

    # 2. Resume
    ctx.resume()
    assert ctx.is_paused is False
    assert ctx.pause_requested is False
    assert pause_evt.is_set() is True
    assert ctx.is_terminal is False

    # 3. Request Cancel
    ctx.cancel(reason="User clicked cancel")
    assert ctx.is_cancelled is True
    assert ctx.is_terminal is True
    assert abort_evt.is_set() is True

    # 4. Resume eligibility check on terminal mission
    adapter = RuntimeAdapter()
    adapter._mission_controls["m_control_test"] = ctx

    eligible, reason = adapter.validate_resume_eligibility("m_control_test")
    assert eligible is False
    assert "terminal state" in reason.lower()

    # 5. Cold resume of non-existent mission
    eligible_cold, cold_reason = adapter.validate_resume_eligibility("m_nonexistent")
    assert eligible_cold is False
    assert "durable checkpoint recovery deferred to phase 2/3" in cold_reason.lower()
