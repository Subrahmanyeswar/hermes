# tests/test_tui_runtime_observer.py
"""Tests for TuiRuntimeObserver and EventBus event projection."""

import io
import pytest
from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionStatus
from ui.rendering.fallback_renderer import FallbackRenderer
from ui.rendering.render_scheduler import RenderScheduler
from ui.rendering.render_supervisor import RenderSupervisor
from ui.rendering.renderer import TuiRenderer
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.rendering.terminal_writer import TerminalWriter
from ui.runtime.observer import TuiRuntimeObserver


def test_runtime_observer_attach_and_event_handling():
    event_bus = EventBus()
    state = HermesRuntimeState.create_empty("obs_mission")
    state.mission.status = MissionStatus.RUNNING

    output_stream = io.StringIO()
    caps = TerminalCapabilities.fallback_plain(80, 24)
    writer = TerminalWriter(stream=output_stream, capabilities=caps)
    supervisor = RenderSupervisor(primary_renderer=TuiRenderer(), fallback_renderer=FallbackRenderer())
    scheduler = RenderScheduler(supervisor=supervisor, writer=writer)

    observer = TuiRuntimeObserver(
        event_bus=event_bus,
        state_provider=lambda: state,
        scheduler=scheduler,
    )

    # Attach observer: initial render triggered
    observer.attach()
    assert scheduler.frames_rendered >= 1
    assert observer.is_attached is True

    # Receive live event
    ev = HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id="obs_mission",
        payload={"tool_name": "fs.write", "output_preview": "file created", "success": True},
    )
    observer.on_event(ev)

    assert len(observer.projector.messages) == 1
    assert observer.projector.messages[0].author_role == "Tool"
    assert "fs.write" in observer.projector.messages[0].content


def test_runtime_observer_disconnect_and_reconnect():
    event_bus = EventBus()
    state = HermesRuntimeState.create_empty("rec_mission")

    output_stream = io.StringIO()
    caps = TerminalCapabilities.fallback_plain(80, 24)
    writer = TerminalWriter(stream=output_stream, capabilities=caps)
    supervisor = RenderSupervisor(primary_renderer=TuiRenderer())
    scheduler = RenderScheduler(supervisor=supervisor, writer=writer)

    observer = TuiRuntimeObserver(
        event_bus=event_bus,
        state_provider=lambda: state,
        scheduler=scheduler,
    )

    observer.attach()
    initial_frames = scheduler.frames_rendered

    # Detach (TUI disconnect)
    observer.detach()
    assert observer.is_attached is False

    # Event while detached -> ignored by observer
    ev = HermesEvent(event_type=EventType.TASK_COMPLETED, mission_id="rec_mission", payload={"task_id": "t1"})
    observer.on_event(ev)
    assert len(observer.projector.messages) == 0

    # Reconnect (TUI reconnect)
    state.mission.status = MissionStatus.COMPLETED
    observer.attach()
    assert observer.is_attached is True
    # Rebuilt and repainted from current authoritative state
    assert scheduler.frames_rendered > initial_frames
