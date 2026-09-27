# tests/test_tui_supervisor_and_fallback.py
"""Tests for RenderSupervisor, FallbackRenderer, and failure isolation."""

import pytest
from ui.rendering.fallback_renderer import FallbackRenderer
from ui.rendering.render_supervisor import CircuitState, RenderSupervisor
from ui.rendering.renderer import TuiRenderer
from ui.rendering.renderer_protocol import RendererProtocol
from ui.rendering.screen_buffer import ScreenFrame
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.viewmodels.mission import MissionViewModel
from ui.viewmodels.root import HermesViewModel


class BrokenRenderer(RendererProtocol):
    """Simulates a buggy primary renderer that throws an unexpected error."""
    def build_frame(self, view_model, capabilities, frame_id=0):
        raise RuntimeError("Simulated UI widget tree render crash!")


def test_fallback_renderer_truthful_output():
    fallback = FallbackRenderer()
    vm = HermesViewModel(
        mission=MissionViewModel(title="Test Mission", status="RUNNING", mission_id="m_123"),
    )
    caps = TerminalCapabilities.fallback_plain(80, 24)

    frame = fallback.build_frame(vm, caps)
    plain_text = frame.to_plain_text()

    assert "HERMES" in plain_text
    assert "RUNNING" in plain_text
    assert "Test Mission" in plain_text
    assert "DEGRADED FALLBACK" in plain_text


def test_render_supervisor_catches_exception_and_engages_fallback():
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


def test_render_supervisor_circuit_breaker_transitions():
    broken = BrokenRenderer()
    fallback = FallbackRenderer()
    supervisor = RenderSupervisor(
        primary_renderer=broken,
        fallback_renderer=fallback,
        max_consecutive_failures=3,
    )
    vm = HermesViewModel()
    caps = TerminalCapabilities.fallback_plain(80, 24)

    # Failure 1
    supervisor.render_frame(vm, caps)
    assert supervisor.circuit_state == CircuitState.DEGRADED

    # Failure 2
    supervisor.render_frame(vm, caps)
    assert supervisor.circuit_state == CircuitState.DEGRADED

    # Failure 3 -> Trips to FALLBACK
    supervisor.render_frame(vm, caps)
    assert supervisor.circuit_state == CircuitState.FALLBACK
    assert supervisor.primary_failures == 3
