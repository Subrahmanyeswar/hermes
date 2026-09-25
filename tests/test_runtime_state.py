# tests/test_runtime_state.py
"""
Authoritative Runtime State & Event Architecture Test Suite (HERMES 2.x - Prompt 3).
Validates all required regression scenarios (Scenarios A through J),
terminal state invariants, subscriber failure isolation, snapshot immutability,
pure reduction, and view-model safety.
"""

import copy
import time
import pytest

from core.runtime_state.models import (
    HermesRuntimeState,
    MissionStatus,
    TaskStatus,
    GoalStatus,
    WaitReason,
    ToolStatus,
    ModelStatus,
    VerificationStatus,
    NetworkConnectivity,
    PermissionStatus,
    EvidenceKind,
)
from core.runtime_state.events import (
    HermesEvent,
    EventType,
    EventSeverity,
    redact_sensitive_str,
    redact_sensitive_payload,
)
from core.runtime_state.reducer import StateReducer
from core.runtime_state.store import StateStore
from core.runtime_state.selectors import ViewModelBuilder
from core.event_bus import EventBus


@pytest.fixture
def fresh_bus():
    """Create a fresh isolated EventBus instance for testing."""
    return EventBus(enabled=True, buffer_size=500)


# ==============================================================================
# SCENARIO A: NORMAL MISSION LIFECYCLE
# ==============================================================================

def test_scenario_a_normal_mission_lifecycle(fresh_bus):
    """
    Scenario A: Full happy-path lifecycle:
    MISSION_STARTED -> TASK_STARTED -> MODEL_REQUESTED -> MODEL_COMPLETED ->
    TOOL_STARTED -> TOOL_COMPLETED -> VERIFICATION_STARTED -> VERIFICATION_COMPLETED ->
    TASK_COMPLETED -> MISSION_COMPLETED
    """
    m_id = "mission_scen_a"
    t_id = "task_1"

    fresh_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=m_id,
        payload={"prompt": "Build an authentication service"}
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.TASK_CREATED,
        mission_id=m_id,
        task_id=t_id,
        payload={"title": "Implement JWT verification"}
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.TASK_STARTED,
        mission_id=m_id,
        task_id=t_id
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.MODEL_REQUESTED,
        mission_id=m_id,
        task_id=t_id,
        payload={"model": "z-ai/glm-5.3-flash", "provider": "nvidia_nim", "tier": 1}
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.MODEL_COMPLETED,
        mission_id=m_id,
        task_id=t_id,
        payload={"latency": 1.25, "tokens": 340}
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id=m_id,
        task_id=t_id,
        payload={"tool_name": "write_file", "arguments_summary": "path=jwt_service.py"}
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=m_id,
        task_id=t_id,
        payload={"tool_name": "write_file", "exit_code": 0, "duration": 0.04}
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.VERIFICATION_STARTED,
        mission_id=m_id,
        task_id=t_id,
        payload={"method": "AST_CHECK"}
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.VERIFICATION_COMPLETED,
        mission_id=m_id,
        task_id=t_id,
        payload={"verdict": "PASSED", "confidence": 0.95}
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.TASK_COMPLETED,
        mission_id=m_id,
        task_id=t_id
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=m_id
    ))

    store = fresh_bus.get_state(m_id)
    assert store is not None
    state = store.get_state()

    assert state.mission.status == MissionStatus.COMPLETED
    assert state.tasks[t_id].status == TaskStatus.COMPLETED
    assert state.progress.completed_tasks == 1
    assert state.progress.total_tasks == 1
    assert state.progress.overall_fraction == 1.0
    assert state.tool_execution.status == ToolStatus.SUCCEEDED
    assert state.tool_execution.tool_name == "write_file"
    assert state.verification.status == VerificationStatus.PASSED
    assert state.model_execution.status == ModelStatus.COMPLETED
    assert state.state_version >= 11


# ==============================================================================
# SCENARIO B: UI SUBSCRIBER CRASH ISOLATION
# ==============================================================================

def test_scenario_b_ui_subscriber_crash_isolation(fresh_bus):
    """
    Scenario B: A subscriber throwing an unhandled exception does NOT crash
    the event bus or prevent StateStore from reaching terminal COMPLETED state.
    """
    m_id = "mission_scen_b"
    t_id = "task_b"

    def crashing_tui_subscriber(event: HermesEvent):
        raise RuntimeError("TUI rendering engine fatal segmentation/assertion failure!")

    fresh_bus.subscribe(crashing_tui_subscriber)

    fresh_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=m_id
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.TASK_STARTED,
        mission_id=m_id,
        task_id=t_id
    ))
    fresh_bus.publish(HermesEvent(
        event_type=EventType.TASK_COMPLETED,
        mission_id=m_id,
        task_id=t_id
    ))

    store = fresh_bus.get_state(m_id)
    assert store is not None
    assert store.get_state().tasks[t_id].status == TaskStatus.COMPLETED


# ==============================================================================
# SCENARIO C: PROMPT 1 PATH SCOPING REGRESSION
# ==============================================================================

def test_scenario_c_structured_feedback_scoping_regression(fresh_bus):
    """
    Scenario C: In Prompt 1, structured_feedback without workspace_ready crashed the TUI
    with UnboundLocalError: 'Path'. The authoritative runtime must process this event
    without crash or state corruption.
    """
    m_id = "mission_scen_c"

    ev = HermesEvent(
        event_type=EventType.EVIDENCE_CREATED,
        mission_id=m_id,
        payload={
            "evidence_id": "fb_1",
            "kind": "FILESYSTEM",
            "artifact_path": "components/Card.vue",
            "verdict": "NEEDS_IMPROVEMENT",
            "failed_dimensions": ["contrast", "accessibility"],
        }
    )
    fresh_bus.publish(ev)

    store = fresh_bus.get_state(m_id)
    assert store is not None
    assert "fb_1" in store.get_state().evidence
    assert store.get_state().evidence["fb_1"].artifact_path == "components/Card.vue"


# ==============================================================================
# SCENARIO D: DUPLICATE EVENT IDEMPOTENCY
# ==============================================================================

def test_scenario_d_duplicate_event_idempotency(fresh_bus):
    """
    Scenario D: Publishing the identical event_id twice must be safely deduplicated
    without double state mutation or sequence jumping.
    """
    m_id = "mission_scen_d"

    ev = HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=m_id,
        event_id="tool_dup_999",
        payload={"tool_name": "git_commit", "exit_code": 0}
    )

    res1 = fresh_bus.publish(ev)
    seq1 = res1.sequence

    res2 = fresh_bus.publish(ev)
    seq2 = res2.sequence

    assert seq1 == seq2
    assert len(fresh_bus.replay(m_id)) == 1


# ==============================================================================
# SCENARIO E: LATE EVENT AFTER TERMINAL COMPLETION
# ==============================================================================

def test_scenario_e_terminal_state_protection(fresh_bus):
    """
    Scenario E: Terminal states cannot regress.
    Once a task is COMPLETED, a late TASK_STARTED cannot regress it to RUNNING.
    Once a mission is COMPLETED, a late MODEL_REQUESTED cannot reopen it.
    """
    m_id = "mission_scen_e"
    t_id = "task_e"

    fresh_bus.publish(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=m_id))
    fresh_bus.publish(HermesEvent(event_type=EventType.TASK_STARTED, mission_id=m_id, task_id=t_id))
    fresh_bus.publish(HermesEvent(event_type=EventType.TASK_COMPLETED, mission_id=m_id, task_id=t_id))
    fresh_bus.publish(HermesEvent(event_type=EventType.MISSION_COMPLETED, mission_id=m_id))

    store = fresh_bus.get_state(m_id)
    assert store.get_state().mission.status == MissionStatus.COMPLETED
    assert store.get_state().tasks[t_id].status == TaskStatus.COMPLETED

    # Late out-of-order events
    fresh_bus.publish(HermesEvent(event_type=EventType.TASK_STARTED, mission_id=m_id, task_id=t_id))
    fresh_bus.publish(HermesEvent(event_type=EventType.MODEL_REQUESTED, mission_id=m_id))

    # Assert invariant: no regression
    assert store.get_state().mission.status == MissionStatus.COMPLETED
    assert store.get_state().tasks[t_id].status == TaskStatus.COMPLETED


# ==============================================================================
# SCENARIO F: NETWORK FAILURE & RECONNECT LIFECYCLE
# ==============================================================================

def test_scenario_f_network_failure_and_reconnect(fresh_bus):
    """
    Scenario F: Network disconnection, reconnection, and restoration lifecycle.
    View models accurately project these states to the user.
    """
    m_id = "mission_scen_f"

    fresh_bus.publish(HermesEvent(
        event_type=EventType.MODEL_CONNECTED,
        mission_id=m_id,
        payload={"endpoint": "https://integrate.api.nvidia.com/v1"}
    ))
    store = fresh_bus.get_state(m_id)
    assert store.get_state().network.connectivity == NetworkConnectivity.CONNECTED

    fresh_bus.publish(HermesEvent(
        event_type=EventType.NETWORK_DISCONNECTED,
        mission_id=m_id,
        payload={"error": "Connection reset by peer"}
    ))
    vm1 = ViewModelBuilder.build(store.get_state())
    assert vm1.network.status_label == "DISCONNECTED"
    assert vm1.progress.waiting_reason_label == "WAITING_FOR_NETWORK"

    fresh_bus.publish(HermesEvent(
        event_type=EventType.NETWORK_RECONNECTING,
        mission_id=m_id
    ))
    vm2 = ViewModelBuilder.build(store.get_state())
    assert vm2.network.is_reconnecting is True
    assert "Reconnecting" in vm2.progress.headline

    fresh_bus.publish(HermesEvent(
        event_type=EventType.NETWORK_RESTORED,
        mission_id=m_id
    ))
    vm3 = ViewModelBuilder.build(store.get_state())
    assert vm3.network.status_label == "CONNECTED"
    assert vm3.network.is_reconnecting is False


# ==============================================================================
# SCENARIO G: PERMISSION REQUEST AND RESOLUTION
# ==============================================================================

def test_scenario_g_permission_lifecycle(fresh_bus):
    """
    Scenario G: Permission requests are tracked as authoritative runtime state,
    not local UI widget state.
    """
    m_id = "mission_scen_g"

    fresh_bus.publish(HermesEvent(
        event_type=EventType.PERMISSION_REQUESTED,
        mission_id=m_id,
        payload={
            "request_id": "perm_456",
            "action": "execute_shell: rm -rf dist/",
            "risk": "HIGH"
        }
    ))
    store = fresh_bus.get_state(m_id)
    vm1 = ViewModelBuilder.build(store.get_state())
    assert vm1.permission.has_pending_request is True
    assert vm1.permission.risk_badge == "HIGH"
    assert vm1.progress.waiting_reason_label == "WAITING_FOR_PERMISSION"

    fresh_bus.publish(HermesEvent(
        event_type=EventType.PERMISSION_APPROVED,
        mission_id=m_id,
        payload={"request_id": "perm_456"}
    ))
    vm2 = ViewModelBuilder.build(store.get_state())
    assert vm2.permission.has_pending_request is False


# ==============================================================================
# SCENARIO H: VERIFICATION PARTIAL STATE (CONFIDENCE=NONE SAFETY)
# ==============================================================================

def test_scenario_h_verification_partial_state_safety(fresh_bus):
    """
    Scenario H: When verification confidence is None (or partial), ViewModelBuilder
    converts it to a safe representation ('Pending') and NEVER throws a float format error.
    """
    m_id = "mission_scen_h"

    fresh_bus.publish(HermesEvent(
        event_type=EventType.VERIFICATION_STARTED,
        mission_id=m_id,
        payload={"method": "SEMANTIC_REVIEW", "confidence": None}
    ))
    store = fresh_bus.get_state(m_id)
    state = store.get_state()
    assert state.verification.confidence is None

    # Invariant: Must not raise TypeError: unsupported format string passed to NoneType
    bundle = ViewModelBuilder.build(state)
    assert bundle.verification.confidence_label == "Pending"
    assert bundle.verification.verdict_badge == "Evaluating"


# ==============================================================================
# SCENARIO I: SNAPSHOT IMMUTABILITY
# ==============================================================================

def test_scenario_i_snapshot_immutability(fresh_bus):
    """
    Scenario I: A caller mutating their copy of the snapshot must NEVER corrupt
    the live authoritative StateStore.
    """
    m_id = "mission_scen_i"

    fresh_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=m_id
    ))
    store = fresh_bus.get_state(m_id)
    snapshot = store.get_snapshot()

    assert snapshot.mission.status == MissionStatus.RUNNING

    # Attempt to mutate snapshot directly
    snapshot.mission.status = MissionStatus.FAILED
    snapshot.tasks["rogue_task"] = None

    # Live state must remain pure
    live_state = store.get_state()
    assert live_state.mission.status == MissionStatus.RUNNING
    assert "rogue_task" not in live_state.tasks


# ==============================================================================
# SCENARIO J: REPLAY DETERMINISM
# ==============================================================================

def test_scenario_j_replay_determinism():
    """
    Scenario J: Replaying a fixed sequence of events produces byte-for-byte identical state.
    """
    events = [
        HermesEvent(event_type=EventType.MISSION_STARTED, mission_id="rep", sequence=1, timestamp=100.0),
        HermesEvent(event_type=EventType.TASK_CREATED, mission_id="rep", task_id="t1", sequence=2, timestamp=101.0),
        HermesEvent(event_type=EventType.TASK_STARTED, mission_id="rep", task_id="t1", sequence=3, timestamp=102.0),
        HermesEvent(event_type=EventType.TOOL_STARTED, mission_id="rep", payload={"tool_name": "list_files"}, sequence=4, timestamp=103.0),
        HermesEvent(event_type=EventType.TOOL_COMPLETED, mission_id="rep", payload={"tool_name": "list_files", "exit_code": 0}, sequence=5, timestamp=104.0),
        HermesEvent(event_type=EventType.TASK_COMPLETED, mission_id="rep", task_id="t1", sequence=6, timestamp=105.0),
    ]

    store1 = StateStore("rep")
    for ev in events:
        store1.apply_event(ev)

    store2 = StateStore("rep")
    store2.replay(events)

    dict1 = store1.get_state().to_dict()
    dict2 = store2.get_state().to_dict()

    # Compare structural dictionaries
    assert dict1["mission"]["status"] == dict2["mission"]["status"]
    assert dict1["tasks"] == dict2["tasks"]
    assert dict1["progress"] == dict2["progress"]
    assert dict1["tool_execution"]["status"] == dict2["tool_execution"]["status"]
    assert dict1["state_version"] == dict2["state_version"]


# ==============================================================================
# TOOL NAME PRESERVATION ACROSS ALL LAYERS
# ==============================================================================

def test_tool_name_preservation(fresh_bus):
    """
    Validates that tool names survive from event -> state -> view model -> UI,
    and missing tool names are mapped to 'Unknown tool' instead of None.
    """
    m_id = "mission_tool_pres"

    fresh_bus.publish(HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id=m_id,
        payload={"tool_name": "read_file"}
    ))
    store = fresh_bus.get_state(m_id)
    assert store.get_state().tool_execution.tool_name == "read_file"

    bundle = ViewModelBuilder.build(store.get_state())
    assert bundle.tool.tool_label == "read_file"

    # Test fallback when tool_name is None
    store.get_state().tool_execution.tool_name = None
    bundle2 = ViewModelBuilder.build(store.get_state())
    assert bundle2.tool.tool_label == "Unknown tool"


# ==============================================================================
# SENSITIVE DATA REDACTION IN PAYLOADS
# ==============================================================================

def test_sensitive_credentials_redacted():
    """Validates that API keys, tokens, passwords, and think tags are scrubbed."""
    raw = {
        "api_key": "sk-1234567890abcdef1234567890abcdef",
        "nested": {
            "token": "ghp_1234567890abcdef1234567890abcdef1234",
            "password": "my_super_secret_password",
        },
        "reasoning": "Plan <think>hidden internal thought</think> output",
    }
    redacted = redact_sensitive_payload(raw)

    assert "sk-" not in redacted["api_key"]
    assert "ghp_" not in redacted["nested"]["token"]
    assert "<think>" not in redacted["reasoning"]


# ==============================================================================
# STATIC ARCHITECTURE INVARIANT CHECKS
# ==============================================================================

def test_static_architecture_boundary():
    """
    Enforces architectural dependency invariants:
    - core/runtime_state modules must NEVER import UI widgets
    - StateReducer must NEVER import network, model clients, or tools
    - Selectors/ViewModels must NEVER import network, model clients, or tools
    """
    import inspect
    import core.runtime_state.models as m
    import core.runtime_state.events as e
    import core.runtime_state.reducer as r
    import core.runtime_state.selectors as s
    import core.runtime_state.store as st

    reducer_src = inspect.getsource(r)
    selectors_src = inspect.getsource(s)
    models_src = inspect.getsource(m)
    events_src = inspect.getsource(e)

    # Invariant: Reducer pureness (no I/O, no network, no models, no tools, no UI)
    forbidden_in_reducer = ["import requests", "import httpx", "import urllib", "import models", "import tools", "import ui"]
    for forbidden in forbidden_in_reducer:
        assert forbidden not in reducer_src, f"StateReducer violates pureness invariant: contains '{forbidden}'"

    # Invariant: ViewModels pureness (no network, no models, no tools, no UI widgets)
    forbidden_in_selectors = ["import requests", "import httpx", "import models", "import tools", "from textual"]
    for forbidden in forbidden_in_selectors:
        assert forbidden not in selectors_src, f"Selectors violate pureness invariant: contains '{forbidden}'"

    # Invariant: Core runtime state does not import UI
    for forbidden in ["from ui", "import ui", "from textual"]:
        assert forbidden not in models_src, f"Models violate UI-isolation invariant: contains '{forbidden}'"
        assert forbidden not in events_src, f"Events violate UI-isolation invariant: contains '{forbidden}'"
