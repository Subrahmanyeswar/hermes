"""
Phase 2 Test Suite: Mission Lifecycle Transitions, Terminal State Immutability,
and Transition Invariants.

Verifies:
- INV-01, INV-05, INV-09, INV-10
- Legal transitions along the state machine graph
- Illegal transitions rejected
- Terminal state immutability within the same attempt
- Transition validation helper correctness
"""

import pytest
from core.runtime_state.models import (
    MissionStatus,
    LEGAL_MISSION_TRANSITIONS,
    is_legal_mission_transition,
    HermesRuntimeState,
    MissionState,
)
from core.runtime_state.reducer import StateReducer
from core.runtime_state.events import HermesEvent, EventType


def test_legal_mission_transitions_exhaustive_graph():
    """Verify all defined transitions in LEGAL_MISSION_TRANSITIONS are valid and accurate."""
    # Terminal states must have empty allowed outbound transitions
    assert LEGAL_MISSION_TRANSITIONS[MissionStatus.COMPLETED] == set()
    assert LEGAL_MISSION_TRANSITIONS[MissionStatus.FAILED] == set()
    assert LEGAL_MISSION_TRANSITIONS[MissionStatus.CANCELLED] == set()
    assert LEGAL_MISSION_TRANSITIONS[MissionStatus.ABORTED] == set()

    # Self-transition is always legal
    for status in MissionStatus:
        assert is_legal_mission_transition(status, status) is True

    # CREATED transitions
    assert is_legal_mission_transition(MissionStatus.CREATED, MissionStatus.RUNNING) is True
    assert is_legal_mission_transition(MissionStatus.CREATED, MissionStatus.PLANNING) is True
    assert is_legal_mission_transition(MissionStatus.CREATED, MissionStatus.CANCELLED) is True
    assert is_legal_mission_transition(MissionStatus.CREATED, MissionStatus.COMPLETED) is False

    # RUNNING transitions
    assert is_legal_mission_transition(MissionStatus.RUNNING, MissionStatus.WAITING) is True
    assert is_legal_mission_transition(MissionStatus.RUNNING, MissionStatus.COMPLETING) is True
    assert is_legal_mission_transition(MissionStatus.RUNNING, MissionStatus.COMPLETED) is True
    assert is_legal_mission_transition(MissionStatus.RUNNING, MissionStatus.FAILED) is True
    assert is_legal_mission_transition(MissionStatus.RUNNING, MissionStatus.CANCELLED) is True
    assert is_legal_mission_transition(MissionStatus.RUNNING, MissionStatus.CREATED) is False

    # WAITING transitions
    assert is_legal_mission_transition(MissionStatus.WAITING, MissionStatus.RUNNING) is True
    assert is_legal_mission_transition(MissionStatus.WAITING, MissionStatus.CANCELLED) is True
    assert is_legal_mission_transition(MissionStatus.WAITING, MissionStatus.FAILED) is True


def test_terminal_state_immutability_in_reducer():
    """Verify that once a mission reaches a terminal status, events within the same attempt cannot mutate it."""
    reducer = StateReducer()
    initial = HermesRuntimeState(
        mission=MissionState(
            mission_id="m_terminal_test",
            status=MissionStatus.COMPLETED,
            attempt_number=1,
        )
    )

    # An event from the same attempt trying to set it to RUNNING must be rejected / ignored
    resume_event = HermesEvent(
        event_type=EventType.MISSION_RESUMED,
        mission_id="m_terminal_test",
        attempt_number=1,
    )
    res_state = reducer.reduce(initial, resume_event)
    assert res_state.mission.status == MissionStatus.COMPLETED, "Terminal state must not be mutated by same attempt"

    # Tool started event on terminal mission must not change terminal status
    tool_event = HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id="m_terminal_test",
        attempt_number=1,
        payload={"tool_name": "write_file", "call_id": "c1"},
    )
    res_state2 = reducer.reduce(initial, tool_event)
    assert res_state2.mission.status == MissionStatus.COMPLETED


def test_authorized_new_attempt_can_resume_terminal_mission():
    """Verify that an authorized resume with attempt_number > prev_attempt allows transition from CANCELLED/FAILED to RUNNING."""
    reducer = StateReducer()
    initial = HermesRuntimeState(
        mission=MissionState(
            mission_id="m_resume_test",
            status=MissionStatus.CANCELLED,
            attempt_number=1,
        )
    )

    # Authorized resume event with higher attempt_number (attempt 2)
    resume_event = HermesEvent(
        event_type=EventType.MISSION_RESUMED,
        mission_id="m_resume_test",
        attempt_number=2,
        payload={"attempt_number": 2},
    )
    new_state = reducer.reduce(initial, resume_event)
    assert new_state.mission.status == MissionStatus.RUNNING
    assert new_state.mission.attempt_number == 2
