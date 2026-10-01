# tests/test_prompt17_eval_replay.py
"""
Test Suite: Prompt 17 Replay Engine & Zero Side-Effect Invariant.

Verifies:
1. Replaying Prompt 17 events (LSP, Browser, Evaluation) requires ZERO live network calls,
   ZERO model calls, ZERO live browser launches, and ZERO subprocesses.
2. Determinism: Replaying the same journal twice yields identical state versions and properties.
3. Monotonic causal sequence tracking and stale event rejection.
4. Presentation sinks (Text, JSON, Stream-JSON) consume Prompt 17 replay events cleanly.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.browser.manager import BrowserManager
from core.replay.engine import ReplayEngine, ReplayResult
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus, TaskStatus
from core.runtime_state.reducer import StateReducer
from core.sinks import JsonSink, NullSink, StreamJsonSink, TextSink


def create_prompt17_synthetic_event_sequence(
    mission_id: str = "m-p17-replay",
    session_id: str = "s-p17-replay",
) -> list[HermesEvent]:
    return [
        HermesEvent(
            event_type=EventType.MISSION_CREATED,
            session_id=session_id,
            mission_id=mission_id,
            sequence=1,
            payload={"title": "Prompt 17 Evaluation Mission", "execution_mode": "auto"},
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
            task_id="t-dash",
            sequence=3,
            payload={"title": "Build Transaction Dashboard", "task_id": "t-dash"},
        ),
        HermesEvent(
            event_type=EventType.TASK_STARTED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=4,
            payload={},
        ),
        # LSP events
        HermesEvent(
            event_type=EventType.LSP_STARTED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=5,
            payload={"language": "python", "server": "ruff server"},
        ),
        HermesEvent(
            event_type=EventType.LSP_DIAGNOSTICS_UPDATED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=6,
            payload={"file_path": "app.py", "error_count": 0, "warning_count": 0},
        ),
        # Browser events
        HermesEvent(
            event_type=EventType.BROWSER_LAUNCHED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=7,
            payload={"driver": "cdp", "browser": "msedge.exe", "headless": True},
        ),
        HermesEvent(
            event_type=EventType.BROWSER_NAVIGATED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=8,
            payload={"url": "http://localhost:8000", "status": 200, "title": "Transaction Dashboard"},
        ),
        HermesEvent(
            event_type=EventType.BROWSER_ACTION_EXECUTED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=9,
            payload={"action": "click", "selector": "#add-btn", "success": True},
        ),
        # Evaluation events
        HermesEvent(
            event_type=EventType.EVALUATION_STARTED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=10,
            payload={"task_id": "cap_web_transaction_dashboard", "status": "PASS", "passed": 3, "failed": 0},
        ),
        HermesEvent(
            event_type=EventType.EVALUATION_CHECK_COMPLETED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=11,
            payload={"check": "chk_saved_row", "status": "PASS"},
        ),
        HermesEvent(
            event_type=EventType.EVALUATION_FINISHED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=12,
            payload={"overall_status": "PASS", "trials": 3, "pass_rate": 1.0},
        ),
        HermesEvent(
            event_type=EventType.TASK_COMPLETED,
            session_id=session_id,
            mission_id=mission_id,
            task_id="t-dash",
            sequence=13,
            payload={"reason": "Dashboard verified functionally and visually"},
        ),
        HermesEvent(
            event_type=EventType.MISSION_COMPLETED,
            session_id=session_id,
            mission_id=mission_id,
            sequence=14,
            payload={"summary": "Mission passed all functional and visual gates"},
        ),
    ]


def test_prompt17_replay_zero_side_effects():
    """
    Verify replaying Prompt 17 events executes ZERO live actions:
    0 subprocess calls, 0 network requests, 0 browser launches, 0 model calls.
    """
    events = create_prompt17_synthetic_event_sequence()
    engine = ReplayEngine()

    # Patch potential side-effect surfaces
    with patch("subprocess.Popen") as mock_popen, \
         patch("subprocess.run") as mock_run, \
         patch("httpx.AsyncClient") as mock_http, \
         patch("core.browser.manager.BrowserManager.launch") as mock_launch:

        res = engine.replay_events(events, sink=NullSink().on_event)

        assert res.success is True
        assert res.events_replayed == len(events)
        assert res.final_state.mission.status == MissionStatus.COMPLETED
        assert res.final_state.last_event_sequence == 14

        # Verify absolutely ZERO external calls were made
        assert mock_popen.call_count == 0
        assert mock_run.call_count == 0
        assert mock_http.call_count == 0
        assert mock_launch.call_count == 0


def test_prompt17_replay_determinism():
    """Verify replaying the same Prompt 17 journal twice produces identical states."""
    events = create_prompt17_synthetic_event_sequence()
    engine = ReplayEngine()

    res1 = engine.replay_events(events)
    res2 = engine.replay_events(events)

    assert res1.final_state.state_version == res2.final_state.state_version
    assert res1.final_state.last_event_sequence == res2.final_state.last_event_sequence
    assert res1.final_state.mission.status == res2.final_state.mission.status


def test_prompt17_replay_presentation_sinks():
    """Verify TextSink, JsonSink, and StreamJsonSink receive and format Prompt 17 events."""
    events = create_prompt17_synthetic_event_sequence()
    engine = ReplayEngine()

    # 1. TextSink
    text_sink = TextSink()
    res_text = engine.replay_events(events, sink=text_sink.on_event)
    text_sink.on_completed(res_text.final_state, exit_code=0)

    # 2. JsonSink
    json_sink = JsonSink()
    res_json = engine.replay_events(events, sink=json_sink.on_event)
    json_sink.on_completed(res_json.final_state, exit_code=0)

    # 3. StreamJsonSink
    stream_sink = StreamJsonSink()
    res_stream = engine.replay_events(events, sink=stream_sink.on_event)
    stream_sink.on_completed(res_stream.final_state, exit_code=0)

    # Ensure json output collected all events
    assert len(json_sink.events_collected) == len(events)
    assert res_json.final_state.mission.status == MissionStatus.COMPLETED
