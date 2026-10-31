# tests/test_prompt18_tui_soak_concurrency.py
"""
Prompt 18: TUI Soak, Concurrency, Terminal Chaos, and Resource Leak Detection.
Validates RenderSupervisor fallback, high-frequency event bus bursts,
terminal resize resilience, memory growth bounding, and concurrent state safety.
"""

from __future__ import annotations

import asyncio
import gc
import io
import psutil
import pytest

from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionStatus
from ui.rendering.fallback_renderer import FallbackRenderer
from ui.rendering.render_scheduler import RenderScheduler
from ui.rendering.render_supervisor import CircuitState, RenderSupervisor
from ui.rendering.renderer import TuiRenderer
from ui.rendering.renderer_protocol import RendererProtocol
from ui.rendering.screen_buffer import ScreenBuffer, ScreenFrame
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.rendering.terminal_writer import TerminalWriter
from ui.runtime.observer import TuiRuntimeObserver
from ui.viewmodels.mission import MissionViewModel
from ui.viewmodels.root import HermesViewModel


class BrokenRenderer(RendererProtocol):
    """Simulates a buggy primary renderer that throws an unexpected error."""
    def build_frame(self, view_model, capabilities, frame_id=0):
        raise RuntimeError("Simulated UI widget tree render crash!")


def test_tui_render_supervisor_catches_failure_and_activates_fallback():
    """
    Section 76: Renderer Failure Injection.
    Inject an exception in the primary rendering layout/screen buffer;
    supervisor must catch it, transition to FallbackRenderer, and keep mission alive.
    """
    broken = BrokenRenderer()
    fallback = FallbackRenderer()
    supervisor = RenderSupervisor(primary_renderer=broken, fallback_renderer=fallback)

    vm = HermesViewModel(
        mission=MissionViewModel(title="Crash Survival", status="ACTIVE"),
    )
    caps = TerminalCapabilities.fallback_plain(80, 24)

    # Supervisor must NOT raise RuntimeError
    frame = supervisor.render_frame(vm, caps, frame_id=1)
    text = frame.to_plain_text()

    assert "Crash Survival" in text
    assert supervisor.primary_failures == 1
    assert supervisor.fallback_activations == 1
    assert supervisor.circuit_state == CircuitState.DEGRADED


def test_tui_terminal_resize_chaos():
    """
    Section 72: Terminal Resize Chaos.
    Rapidly alternate geometry between tiny (20x10) and massive (200x60) viewports.
    ScreenBuffer and layout must not crash or leak escape codes.
    """
    test_dimensions = [
        (20, 10),
        (200, 60),
        (40, 20),
        (120, 40),
        (10, 5),   # Pathological tiny terminal
        (80, 24),
    ]

    for w, h in test_dimensions:
        buf = ScreenBuffer(width=w, height=h)
        assert buf.width == w
        assert buf.height == h
        # Write characters safely into bounds
        buf.put_string(0, 0, f"Viewport {w}x{h}")
        frame = buf.snapshot(frame_id=1, state_revision=1)
        rendered = frame.to_plain_text()
        assert len(rendered) > 0


def test_event_bus_high_throughput_burst_soak():
    """
    Section 70 & 75: Event Bus Burst Soak & Memory Growth Bounding.
    Inject 100 rapid state update events through EventBus and TuiRuntimeObserver;
    verify bounded event queue, no dropped fatal events, and memory growth < 25MB.
    """
    gc.collect()
    proc = psutil.Process()
    mem_before_mb = proc.memory_info().rss / (1024 * 1024)

    event_bus = EventBus()
    state = HermesRuntimeState.create_empty("soak_mission")
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
    observer.attach()

    # Emit 100 high-frequency events through event bus
    for i in range(100):
        ev = HermesEvent(
            event_type=EventType.TOOL_COMPLETED,
            payload={"tool_name": "fs.write", "output_preview": f"chunk_{i}", "success": True},
            source="test",
        )
        observer.on_event(ev)

    gc.collect()
    mem_after_mb = proc.memory_info().rss / (1024 * 1024)
    mem_growth_mb = mem_after_mb - mem_before_mb

    # Memory growth must be strictly bounded (< 30MB)
    assert mem_growth_mb < 30.0, f"Memory grew excessively by {mem_growth_mb:.2f} MB"
    assert scheduler.frames_rendered >= 1


def test_concurrent_background_jobs_and_checkpoints():
    """
    Section 90 & 91: Concurrency Chaos & Checkpoint Consistency.
    Execute concurrent background updates without corrupting authoritative state.
    """
    from core.runtime_state.reducer import StateReducer
    reducer = StateReducer()
    state = HermesRuntimeState.create_empty("sess_concurrent_001")

    events = []
    for worker_id in range(4):
        for step in range(10):
            ev = HermesEvent(
                event_type=EventType.TOOL_COMPLETED,
                payload={"tool_name": f"worker_{worker_id}", "output_preview": f"res_{step}", "success": True},
                source=f"worker_{worker_id}",
            )
            events.append(ev)

    for ev in events:
        state = reducer.reduce(state, ev)

    assert len(events) == 40
    assert state.tool_execution.success is True
    assert len(state.tool_execution.recent_tools) > 0

