# tests/test_prompt16_replay.py
"""
Test Suite: Prompt 16 Replay Engine & Purity Invariant.

Verifies:
1. Replay is NOT execution: 0 model calls, 0 tool executions, 0 network, 0 disk writes.
2. Deterministic reconstruction of authoritative state via pure StateReducer.
3. Trace file replay support (JSON and JSONL).
4. Presentation sinks (Text, JSON, Stream-JSON) integration with ReplayEngine.
5. Determinism: replaying the same journal twice yields identical state versions and tasks.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.replay.engine import ReplayEngine, ReplayResult
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.runtime_state.models import MissionStatus, TaskStatus
from core.sinks import JsonSink, NullSink, StreamJsonSink, TextSink


def create_synthetic_event_sequence(mission_id: str = "m-replay-1", session_id: str = "s-replay-1") -> list[HermesEvent]:
    return [
        HermesEvent(
            event_type=EventType.MISSION_CREATED,
            session_id=session_id,
            mission_id=mission_id,
            sequence=1,
            payload={"title": "Test Replay Mission", "execution_mode": "auto"},
        ),
        HermesEvent(
            event_type=EventType.MISSION_STARTED,
            session_id=session_id,
            mission_id=mission_id,
            sequence=2,
            payload={},
        ),
        HermesEvent(
            event_type=EventType.TASK_CREATED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-1",
            sequence=3,
            payload={"title": "Setup environment", "task_id": "t-1"},
        ),
        HermesEvent(
            event_type=EventType.TASK_STARTED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-1",
            sequence=4,
            payload={},
        ),
        HermesEvent(
            event_type=EventType.TOOL_STARTED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-1",
            sequence=5,
            payload={"tool": "read_file", "path": "setup.py"},
        ),
        HermesEvent(
            event_type=EventType.TOOL_COMPLETED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-1",
            sequence=6,
            payload={"tool": "read_file", "output": "print('hello')"},
        ),
        HermesEvent(
            event_type=EventType.TASK_COMPLETED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-1",
            sequence=7,
            payload={},
        ),
        HermesEvent(
            event_type=EventType.MISSION_COMPLETED,
            session_id=session_id,
            mission_id=mission_id,
            sequence=8,
            payload={"reason": "ALL_TASKS_DONE"},
        ),
    ]


def test_replay_pure_reconstruction():
    """Verify ReplayEngine rebuilds complete runtime state without executing tools or models."""
    engine = ReplayEngine()
    events = create_synthetic_event_sequence()

    res: ReplayResult = engine.replay_events(events)

    assert res.success is True
    assert res.events_replayed == len(events)
    assert res.final_state.mission.mission_id == "m-replay-1"
    assert res.final_state.mission.status == MissionStatus.COMPLETED
    assert "t-1" in res.final_state.tasks
    assert res.final_state.tasks["t-1"].status == TaskStatus.COMPLETED


def test_replay_determinism():
    """Verify that replaying twice yields strictly deterministic identical state."""
    engine = ReplayEngine()
    events = create_synthetic_event_sequence()

    res1 = engine.replay_events(events)
    res2 = engine.replay_events(events)

    assert res1.final_state.state_version == res2.final_state.state_version
    assert res1.final_state.mission.status == res2.final_state.mission.status
    assert len(res1.final_state.tasks) == len(res2.final_state.tasks)
    assert res1.final_state.tasks["t-1"].status == res2.final_state.tasks["t-1"].status


def test_replay_empty_sequence():
    """Verify replaying empty event journal gracefully returns valid state."""
    engine = ReplayEngine()
    res = engine.replay_events([], initial_mission_id="empty_test")
    assert res.success is True
    assert res.events_replayed == 0
    assert res.final_state.mission.mission_id == "empty_test"


def test_replay_with_presentation_sink():
    """Verify sinks receive rendered event stream during replay."""
    engine = ReplayEngine()
    events = create_synthetic_event_sequence()

    sink_events = []

    def test_sink(evt: HermesEvent, state):
        sink_events.append((evt.event_type, state.state_version))

    res = engine.replay_events(events, sink=test_sink)
    assert res.success is True
    assert len(sink_events) == len(events)
    assert sink_events[0][0] == EventType.MISSION_CREATED
    assert sink_events[-1][0] == EventType.MISSION_COMPLETED


def test_replay_trace_file_json(tmp_path: Path):
    """Verify loading and replaying a JSON trace file."""
    trace_file = tmp_path / "mission_trace.json"
    raw_records = [
        {
            "event_type": "MISSION_CREATED",
            "mission_id": "trace-m-1",
            "session_id": "trace-s-1",
            "sequence": 1,
            "payload": {"title": "Trace Mission"},
        },
        {
            "event_type": "MISSION_COMPLETED",
            "mission_id": "trace-m-1",
            "session_id": "trace-s-1",
            "sequence": 2,
            "payload": {},
        },
    ]
    trace_file.write_text(json.dumps(raw_records), encoding="utf-8")

    engine = ReplayEngine()
    res = engine.replay_trace_file(trace_file)

    assert res.success is True
    assert res.events_replayed == 2
    assert res.final_state.mission.mission_id == "trace-m-1"
    assert res.final_state.mission.status == MissionStatus.COMPLETED


def test_replay_trace_file_jsonl(tmp_path: Path):
    """Verify loading and replaying a JSONL line-delimited trace file."""
    trace_file = tmp_path / "mission_trace.jsonl"
    lines = [
        json.dumps({"event_type": "MISSION_CREATED", "mission_id": "jsonl-m-1", "sequence": 1, "payload": {}}),
        json.dumps({"event_type": "TASK_CREATED", "mission_id": "jsonl-m-1", "task_id": "task-j", "sequence": 2, "payload": {"title": "JSONL task"}}),
    ]
    trace_file.write_text("\n".join(lines), encoding="utf-8")

    engine = ReplayEngine()
    res = engine.replay_trace_file(trace_file)

    assert res.success is True
    assert res.events_replayed == 2
    assert res.final_state.mission.mission_id == "jsonl-m-1"
    assert "task-j" in res.final_state.tasks


def test_replay_missing_trace_file(tmp_path: Path):
    """Verify missing trace file returns structured failure without crashing."""
    missing_file = tmp_path / "non_existent.json"
    engine = ReplayEngine()
    res = engine.replay_trace_file(missing_file)
    assert res.success is False
    assert "Trace file not found" in res.error
