# tests/test_security_gate_integration.py
"""
Integration tests for SecurityGate, Event Emission, Denial Loops, and Reducer State.
"""

import time
import pytest
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, PermissionStatus
from core.runtime_state.reducer import StateReducer
from core.security.enums import (
    ApprovalScope,
    DenialReasonCode,
    PermissionOutcome,
    RiskLevel,
)
from core.security.gate import SecurityGate
from core.security.models import SubagentSecurityContext, UserIntent


@pytest.fixture
def emitted_events():
    events = []
    def record_event(event_type: str, payload: dict):
        events.append((event_type, payload))
    return events, record_event


def test_gate_evaluates_and_emits_risk_and_permission_events(emitted_events):
    events_list, record_fn = emitted_events
    gate = SecurityGate(event_emitter=record_fn)

    # 1. Propose safe read-only action
    decision, action = gate.evaluate_action(
        tool_name="view_file",
        arguments={"path": "src/App.tsx"},
        session_id="sess_test",
    )
    assert decision.outcome == PermissionOutcome.ALLOW
    
    event_types = [e[0] for e in events_list]
    assert "SECURITY_RISK_ASSESSED" in event_types
    assert "PERMISSION_EVALUATED" in event_types


def test_gate_asks_on_unapproved_medium_risk(emitted_events):
    events_list, record_fn = emitted_events
    gate = SecurityGate(event_emitter=record_fn)

    decision, action = gate.evaluate_action(
        tool_name="run_command",
        arguments={"command": "python build_assets.py"},
        session_id="sess_test",
        headless_mode=False,
    )
    assert decision.outcome == PermissionOutcome.ASK
    
    event_types = [e[0] for e in events_list]
    assert "PERMISSION_ASKED" in event_types


def test_gate_denial_loop_detection_and_escalation(emitted_events):
    events_list, record_fn = emitted_events
    gate = SecurityGate(event_emitter=record_fn)

    # Trigger 3 consecutive hard denies (e.g. destructive commands)
    for _ in range(3):
        decision, _ = gate.evaluate_action(
            tool_name="run_command",
            arguments={"command": "rm -rf /"},
            session_id="sess_test",
        )
        assert decision.outcome == PermissionOutcome.DENY

    assert gate.denial_tracker.consecutive_denials == 3
    event_types = [e[0] for e in events_list]
    assert "SECURITY_ESCALATION" in event_types


def test_gate_grant_consumption(emitted_events):
    events_list, record_fn = emitted_events
    gate = SecurityGate(event_emitter=record_fn)

    # 1. Add grant
    grant = gate.approval_store.create_grant(
        scope=ApprovalScope.EXACT_ACTION,
        tool_name="write_file",
        fingerprint=None,  # will set after calculating
        max_uses=1,
    )

    # Propose action
    action_desc = gate.classifier.build_descriptor(
        tool_name="write_file",
        arguments={"path": "src/new.py", "content": "hello"},
    )
    grant.action_fingerprint = action_desc.action_fingerprint

    # Evaluate
    decision, _ = gate.evaluate_action(
        tool_name="write_file",
        arguments={"path": "src/new.py", "content": "hello"},
    )
    assert decision.outcome == PermissionOutcome.ALLOW
    assert grant.remaining_uses == 0  # Consumed!
    event_types = [e[0] for e in events_list]
    assert "PERMISSION_GRANTED" in event_types


def test_state_reducer_processes_security_events():
    state = HermesRuntimeState.create_empty(mission_id="m_sec_test")
    assert state.permission.status == PermissionStatus.NONE

    # 1. PERMISSION_ASKED event
    ev_asked = HermesEvent(
        event_type=EventType.PERMISSION_ASKED,
        mission_id="m_sec_test",
        payload={
            "request_id": "req_123",
            "tool_name": "run_command",
            "scope": "ONE_ACTION",
            "risk_level": "HIGH",
        },
    )
    state = StateReducer.reduce(state, ev_asked)
    assert state.permission.status == PermissionStatus.REQUESTED
    assert state.permission.action == "run_command"
    assert state.permission.risk == "HIGH"

    # 2. PERMISSION_GRANTED event
    ev_granted = HermesEvent(
        event_type=EventType.PERMISSION_GRANTED,
        mission_id="m_sec_test",
        payload={"grant_id": "g_123", "tool_name": "run_command"},
    )
    state = StateReducer.reduce(state, ev_granted)
    assert state.permission.status == PermissionStatus.APPROVED
    assert state.permission.decision == "APPROVED"
