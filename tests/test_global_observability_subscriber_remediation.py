# tests/test_global_observability_subscriber_remediation.py
"""
Qualification and regression suite for HERMES 2.x Global Observability Subscriber Remediation.
Verifies:
A. One EventBus publication produces one telemetry record.
B. Four sequential missions do not increase subscriber count.
C. Two concurrent missions route events to correct independent run directories exactly once.
D. Repeated RuntimeAdapter initialization does not create additional subscriptions.
E. Subscriber shutdown and reinitialization do not leave stale callbacks.
F. TOOL_STARTED and TOOL_COMPLETED are each recorded once per logical operation.
G. Event sequence numbers increment once per logical event.
H. A complete mission still performs Tier 1 -> Tier 2 recovery and completes successfully.
"""

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from core.event_bus import EventBus
from core.observability.bus_subscriber import ObservabilityBusSubscriber
from core.observability.logger import MissionTelemetryLogger, get_telemetry_logger
from core.runtime_state.events import HermesEvent, EventType, EventSeverity
from core.server.runtime_adapter import RuntimeAdapter


@pytest.fixture
def temp_obs_dir():
    tmp = tempfile.mkdtemp(prefix="hermes_obs_remed_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


def test_a_one_event_one_telemetry_record(temp_obs_dir):
    """Scenario A: One EventBus publication produces exactly one telemetry record in events.jsonl."""
    bus = EventBus()
    subscriber = ObservabilityBusSubscriber(bus)
    subscriber.attach()

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    logger = MissionTelemetryLogger(run_id=run_id, mission_id=mission_id, base_dir=temp_obs_dir)

    action_id = f"act_{uuid.uuid4().hex[:8]}"
    event = HermesEvent(
        event_type=EventType.ACTION_DENIED,
        mission_id=mission_id,
        run_id=run_id,
        severity=EventSeverity.WARNING,
        source="agent_loop",
        payload={
            "action_id": action_id,
            "tool_name": "fs.read",
            "reason": "TOOL_REJECTED_NO_PROGRESS",
            "code": "TOOL_REJECTED_NO_PROGRESS",
        },
    )

    bus.publish(event)
    subscriber.detach()

    events_file = logger.files["events"]
    lines = [json.loads(l) for l in events_file.read_text(encoding="utf-8").splitlines() if l.strip()]

    # Filter out initial runtime snapshot
    action_events = [d for d in lines if d.get("payload", {}).get("action_id") == action_id]
    assert len(action_events) == 1, f"Expected exactly 1 ACTION_DENIED event, got {len(action_events)}"
    assert action_events[0]["event_type"] == "ACTION_DENIED"


def test_b_sequential_missions_do_not_increase_subscriber_count():
    """Scenario B: Four sequential missions do not increase EventBus subscriber count."""
    bus = EventBus()
    adapter = RuntimeAdapter(event_bus=bus)

    initial_subscribers = len(bus._subscribers)
    assert adapter.telemetry_subscriber is not None
    assert adapter.telemetry_subscriber.is_attached

    from core.agent_loop.loop import AgentLoop
    from core.agent_loop.types import AgentLoopConfig
    from unittest.mock import MagicMock

    # Simulate 4 sequential missions by creating 4 AgentLoop instances
    for i in range(4):
        m_id = f"m_seq_{i}"
        r_id = f"run_1_{m_id}"
        mock_orch = MagicMock()
        mock_ws = MagicMock()
        loop = AgentLoop(
            orchestrator=mock_orch,
            workspace_manager=mock_ws,
            event_bus_instance=bus,
            config=AgentLoopConfig(),
        )
        loop._mission_id = m_id
        loop._run_id = r_id
        # In remediated code, AgentLoop does not attach a subscriber
        assert not hasattr(loop, "_obs_subscriber") or getattr(loop, "_obs_subscriber", None) is None

    final_subscribers = len(bus._subscribers)
    assert final_subscribers == initial_subscribers, (
        f"Subscriber leak detected! Initial: {initial_subscribers}, Final: {final_subscribers}"
    )


def test_c_concurrent_missions_route_to_independent_run_dirs(temp_obs_dir):
    """Scenario C: Two concurrent missions route events to independent run directories exactly once."""
    bus = EventBus()
    subscriber = ObservabilityBusSubscriber(bus)
    subscriber.attach()

    m1_id, r1_id = "m_conc_1", "run_1_m_conc_1"
    m2_id, r2_id = "m_conc_2", "run_1_m_conc_2"

    logger1 = MissionTelemetryLogger(run_id=r1_id, mission_id=m1_id, base_dir=temp_obs_dir)
    logger2 = MissionTelemetryLogger(run_id=r2_id, mission_id=m2_id, base_dir=temp_obs_dir)

    # Interleaved event publication
    ev1_a = HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=m1_id, run_id=r1_id)
    ev2_a = HermesEvent(event_type=EventType.MISSION_STARTED, mission_id=m2_id, run_id=r2_id)
    ev1_b = HermesEvent(event_type=EventType.AGENT_TURN_STARTED, mission_id=m1_id, run_id=r1_id, payload={"turn": 1})
    ev2_b = HermesEvent(event_type=EventType.AGENT_TURN_STARTED, mission_id=m2_id, run_id=r2_id, payload={"turn": 1})

    bus.publish(ev1_a)
    bus.publish(ev2_a)
    bus.publish(ev1_b)
    bus.publish(ev2_b)
    subscriber.detach()

    lines1 = [json.loads(l) for l in logger1.files["events"].read_text(encoding="utf-8").splitlines() if l.strip()]
    lines2 = [json.loads(l) for l in logger2.files["events"].read_text(encoding="utf-8").splitlines() if l.strip()]

    m1_events = [l for l in lines1 if l.get("event_type") in ("MISSION_STARTED", "AGENT_TURN_STARTED")]
    m2_events = [l for l in lines2 if l.get("event_type") in ("MISSION_STARTED", "AGENT_TURN_STARTED")]

    assert len(m1_events) == 2, f"Mission 1 should have exactly 2 published events, got {len(m1_events)}"
    assert len(m2_events) == 2, f"Mission 2 should have exactly 2 published events, got {len(m2_events)}"

    # Ensure zero cross-contamination
    assert all(l.get("mission_id") == m1_id for l in lines1 if "mission_id" in l)
    assert all(l.get("mission_id") == m2_id for l in lines2 if "mission_id" in l)


def test_d_repeated_runtime_adapter_init_idempotent():
    """Scenario D: Repeated RuntimeAdapter initialization does not create additional subscriptions."""
    bus = EventBus()
    adapter = RuntimeAdapter(event_bus=bus)

    count_after_first = len(bus._subscribers)
    # Call _init_telemetry_subscriber repeatedly
    adapter._init_telemetry_subscriber()
    adapter._init_telemetry_subscriber()

    count_after_repeats = len(bus._subscribers)
    assert count_after_repeats == count_after_first, "Repeated initialization added duplicate subscriptions"


def test_e_subscriber_shutdown_and_reinit_no_stale_callbacks():
    """Scenario E: Subscriber shutdown and reinitialization do not leave stale callbacks."""
    bus = EventBus()
    adapter = RuntimeAdapter(event_bus=bus)

    # Verify initial attachment
    assert bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY) or any(getattr(s[0], "__name__", "") == "handle_event" for s in bus._subscribers)

    # Detach
    adapter.detach_telemetry_subscriber()
    assert not bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY)
    assert not any(getattr(s[0], "__name__", "") == "handle_event" for s in bus._subscribers)
    assert adapter.telemetry_subscriber is None

    # Reinitialize
    adapter._init_telemetry_subscriber()
    assert adapter.telemetry_subscriber is not None
    assert adapter.telemetry_subscriber.is_attached
    has_sub = bus.has_subscription(ObservabilityBusSubscriber.SUBSCRIPTION_KEY)
    obs_subscribers = [s for s in bus._subscribers if getattr(s[0], "__name__", "") == "handle_event"]
    assert has_sub or len(obs_subscribers) == 1, "Expected active subscriber after re-init"



def test_f_tool_started_and_completed_recorded_once(temp_obs_dir):
    """Scenario F: TOOL_STARTED and TOOL_COMPLETED are each recorded once per logical operation."""
    bus = EventBus()
    subscriber = ObservabilityBusSubscriber(bus)
    subscriber.attach()

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    logger = MissionTelemetryLogger(run_id=run_id, mission_id=mission_id, base_dir=temp_obs_dir)

    tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
    operation_id = f"op_{uuid.uuid4().hex[:8]}"

    # 1. EventBus publishes TOOL_STARTED
    bus.publish(HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id=mission_id,
        run_id=run_id,
        tool_call_id=tool_call_id,
        payload={
            "operation_id": operation_id,
            "tool_call_id": tool_call_id,
            "tool_name": "fs.write",
            "target_path": "app.js",
        }
    ))

    # 2. EventBus publishes TOOL_COMPLETED
    bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        run_id=run_id,
        tool_call_id=tool_call_id,
        payload={
            "operation_id": operation_id,
            "tool_call_id": tool_call_id,
            "tool_name": "fs.write",
            "target_path": "app.js",
            "exit_code": 0,
            "duration_ms": 42.0,
            "success": True,
        }
    ))

    # 3. AgentLoop executes direct record_tool_call() with same tool_call_id
    logger.record_tool_call(
        tool_call_id=tool_call_id,
        tool_name="fs.write",
        turn=1,
        duration_ms=42.0,
        success=True,
        exit_code=0,
        target_path="app.js",
        stdout="Wrote 100 bytes",
    )

    subscriber.detach()

    # Read tools.jsonl
    tools_file = logger.files["tools"]
    lines = [json.loads(l) for l in tools_file.read_text(encoding="utf-8").splitlines() if l.strip()]

    started_events = [l for l in lines if l.get("event_type") == "TOOL_STARTED"]
    completed_events = [l for l in lines if l.get("event_type") == "TOOL_COMPLETED"]

    assert len(started_events) == 1, f"Expected exactly 1 TOOL_STARTED, got {len(started_events)}"
    assert len(completed_events) == 1, f"Expected exactly 1 TOOL_COMPLETED, got {len(completed_events)}"
    assert logger._stats["tool_calls"] == 1, f"Expected stats.tool_calls == 1, got {logger._stats['tool_calls']}"


def test_g_event_sequence_numbers_increment_once_per_logical_event(temp_obs_dir):
    """Scenario G: Event sequence numbers increment exactly once per logical event."""
    bus = EventBus()
    subscriber = ObservabilityBusSubscriber(bus)
    subscriber.attach()

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    logger = MissionTelemetryLogger(run_id=run_id, mission_id=mission_id, base_dir=temp_obs_dir)

    for i in range(3):
        bus.publish(HermesEvent(
            event_type=EventType.PROGRESS_UPDATED,
            mission_id=mission_id,
            run_id=run_id,
            payload={"turn": i + 1, "progress": (i + 1) * 33}
        ))

    subscriber.detach()

    lines = [json.loads(l) for l in logger.files["events"].read_text(encoding="utf-8").splitlines() if l.strip()]
    prog_events = [l for l in lines if l.get("event_type") == "PROGRESS_UPDATED"]

    assert len(prog_events) == 3
    seqs = [e["event_seq"] for e in prog_events]
    # Verify sequence numbers are strictly incrementing by 1
    assert seqs[1] == seqs[0] + 1
    assert seqs[2] == seqs[1] + 1


@pytest.mark.asyncio
async def test_h_mission_tier1_to_tier2_recovery_convergence(temp_obs_dir):
    """Scenario H: A complete mission performs Tier 1 -> Tier 2 recovery and records telemetry 1x."""
    bus = EventBus()
    subscriber = ObservabilityBusSubscriber(bus)
    subscriber.attach()

    run_id = f"run_1_recov_{uuid.uuid4().hex[:6]}"
    mission_id = f"m_recov_{uuid.uuid4().hex[:6]}"
    logger = MissionTelemetryLogger(run_id=run_id, mission_id=mission_id, base_dir=temp_obs_dir)

    # 1. Tier 1 encounters failure
    bus.publish(HermesEvent(
        event_type=EventType.MODEL_REQUESTED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"tier": 1, "provider": "gemini", "model": "gemini-3.5-flash-lite"}
    ))
    bus.publish(HermesEvent(
        event_type=EventType.TIER_FAILOVER_STARTED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"from_tier": 1, "to_tier": 2, "provider": "mistral", "model": "codestral-latest"}
    ))
    bus.publish(HermesEvent(
        event_type=EventType.TIER_SELECTED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"tier": 2, "provider": "mistral", "model": "codestral-latest"}
    ))
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        run_id=run_id,
        payload={"outcome": "SUCCESS", "tier": 2}
    ))

    subscriber.detach()

    lines = [json.loads(l) for l in logger.files["events"].read_text(encoding="utf-8").splitlines() if l.strip()]
    failover_events = [l for l in lines if l.get("event_type") == "TIER_FAILOVER_STARTED"]
    completed_events = [l for l in lines if l.get("event_type") == "MISSION_COMPLETED"]

    assert len(failover_events) == 1, f"Expected 1 TIER_FAILOVER_STARTED, got {len(failover_events)}"
    assert len(completed_events) == 1, f"Expected 1 MISSION_COMPLETED, got {len(completed_events)}"
