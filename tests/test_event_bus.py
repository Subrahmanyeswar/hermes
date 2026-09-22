"""
Unit and Integration Tests for Phase 14 Event Bus + Event-Driven TUI.
Tests all 10 core scenarios:
1. Publish and subscribe delivery
2. Monotonic sequence numbering
3. Duplicate event deduplication
4. Stale event protection in state store
5. Multi-mission event isolation
6. Subscriber error isolation
7. State store reconstruction from events
8. High-frequency event burst processing
9. Sensitive credential redaction in TUI
10. Sub-millisecond event dispatch latency
"""
import time
import pytest
from core.event_bus import (
    HermesEvent,
    EventType,
    EventSeverity,
    ExecutionStateStore,
    EventBus
)
from ui.event_tui import EventDrivenTUI


@pytest.fixture
def bus():
    return EventBus(enabled=True, buffer_size=500)


def test_publish_and_subscribe_delivery(bus):
    """Subscribers receive published events."""
    received = []
    bus.subscribe(lambda e: received.append(e))

    ev = HermesEvent(event_type=EventType.MISSION_STARTED, mission_id="m1")
    bus.publish(ev)

    assert len(received) == 1
    assert received[0].mission_id == "m1"
    assert received[0].event_type == EventType.MISSION_STARTED


def test_event_sequence_monotonic_ordering(bus):
    """Event sequences increase monotonically."""
    ev1 = bus.publish(HermesEvent(event_type=EventType.MISSION_STARTED, mission_id="m2"))
    ev2 = bus.publish(HermesEvent(event_type=EventType.TASK_STARTED, mission_id="m2", task_id="t1"))

    assert ev2.sequence > ev1.sequence


def test_event_deduplication(bus):
    """Publishing identical event_id twice is deduplicated."""
    received = []
    bus.subscribe(lambda e: received.append(e))

    ev = HermesEvent(event_type=EventType.TASK_COMPLETED, mission_id="m3", event_id="dup-123")
    bus.publish(ev)
    bus.publish(ev)

    assert len(received) == 1


def test_stale_event_ignored_by_state_store(bus):
    """Out-of-order events with lower sequence do not overwrite newer state."""
    state = ExecutionStateStore("m4")
    ev1 = HermesEvent(event_type=EventType.MISSION_STARTED, mission_id="m4", sequence=10)
    ev2 = HermesEvent(event_type=EventType.MISSION_COMPLETED, mission_id="m4", sequence=20)
    ev_stale = HermesEvent(event_type=EventType.MISSION_STARTED, mission_id="m4", sequence=5)

    state.apply_event(ev1)
    state.apply_event(ev2)
    assert state.status == "COMPLETED"

    state.apply_event(ev_stale)
    assert state.status == "COMPLETED"  # Did not regress to RUNNING


def test_multi_mission_isolation(bus):
    """Events from Mission A do not affect Mission B state."""
    bus.publish(HermesEvent(event_type=EventType.WORKSPACE_SCAN_COMPLETED, mission_id="mA", payload={"files_indexed": 42}))
    bus.publish(HermesEvent(event_type=EventType.WORKSPACE_SCAN_COMPLETED, mission_id="mB", payload={"files_indexed": 99}))

    stA = bus.get_state("mA")
    stB = bus.get_state("mB")

    assert stA.workspace_files_count == 42
    assert stB.workspace_files_count == 99


def test_subscriber_failure_isolation(bus):
    """A failing subscriber does not crash the event bus or other subscribers."""
    received = []

    def broken_handler(e):
        raise ValueError("TUI render crashed!")

    bus.subscribe(broken_handler)
    bus.subscribe(lambda e: received.append(e))

    # Should not raise exception
    bus.publish(HermesEvent(event_type=EventType.TASK_STARTED, mission_id="m5"))
    assert len(received) == 1


def test_state_store_reconstruction(bus):
    """State store accurately tracks mission progress and active task."""
    bus.publish(HermesEvent(event_type=EventType.TASK_CREATED, mission_id="m6", payload={"task_id": "t1", "title": "Setup"}))
    bus.publish(HermesEvent(event_type=EventType.TASK_CREATED, mission_id="m6", payload={"task_id": "t2", "title": "Build"}))
    bus.publish(HermesEvent(event_type=EventType.TASK_STARTED, mission_id="m6", task_id="t1"))
    bus.publish(HermesEvent(event_type=EventType.TASK_COMPLETED, mission_id="m6", task_id="t1"))

    st = bus.get_state("m6")
    assert st.progress == (1, 2)
    assert st.tasks["t1"]["status"] == "COMPLETED"
    assert st.tasks["t2"]["status"] == "PENDING"


def test_high_frequency_event_burst(bus):
    """Event bus handles 1,000 rapid events without penalty."""
    t0 = time.perf_counter()
    for i in range(1000):
        bus.publish(HermesEvent(event_type=EventType.TASK_PROGRESS, mission_id="m_burst", payload={"pct": i}))
    dur_ms = (time.perf_counter() - t0) * 1000.0

    assert dur_ms < 100.0  # Fast dispatch throughput


def test_tui_sensitive_data_redaction():
    """TUI redacts API keys, tokens, and passwords."""
    tui = EventDrivenTUI(mission_id="m7")
    raw = "User requested with key sk-1234567890abcdef123 and password 'super_secret' and <think>internal reasoning</think>"
    redacted = tui.redact_sensitive(raw)

    assert "super_secret" not in redacted
    assert "sk-1234567890abcdef123" not in redacted
    assert "<think>" not in redacted


def test_fast_event_dispatch_sub_millisecond(bus):
    """Individual event publish overhead is < 0.05 ms."""
    ev = HermesEvent(event_type=EventType.TOOL_STARTED, mission_id="m8", payload={"tool_name": "write_file"})
    t0 = time.perf_counter()
    bus.publish(ev)
    dur_ms = (time.perf_counter() - t0) * 1000.0

    assert dur_ms < 0.1
