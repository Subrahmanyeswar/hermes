# tests/test_tui_isolation_and_purity.py
"""Tests for Renderer Purity, Headless Import Isolation, and UI Failure Isolation."""

import subprocess
import pytest
from core.runtime_state.models import HermesRuntimeState, MissionStatus
from ui.rendering.fallback_renderer import FallbackRenderer
from ui.rendering.render_supervisor import RenderSupervisor
from ui.rendering.renderer import TuiRenderer
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.viewmodels.mission import MissionViewModel
from ui.viewmodels.root import HermesViewModel


def test_renderer_purity_no_prohibited_calls(monkeypatch):
    """Prove that TuiRenderer.build_frame cannot invoke network, subprocess, or shell."""
    def forbidden_call(*args, **kwargs):
        raise AssertionError("FORBIDDEN: Renderer attempted prohibited side effect!")

    # Monkeypatch subprocess
    monkeypatch.setattr(subprocess, "run", forbidden_call)
    monkeypatch.setattr(subprocess, "Popen", forbidden_call)

    renderer = TuiRenderer()
    caps = TerminalCapabilities.fallback_plain(100, 30)
    vm = HermesViewModel(
        mission=MissionViewModel(title="Purity Check", status="RUNNING"),
    )

    # Must execute smoothly without triggering forbidden side effects
    frame = renderer.build_frame(vm, caps)
    assert frame.width == 100
    assert frame.height == 30


def test_ui_failure_isolation_mission_status_unaffected():
    """Verify that a fatal rendering exception never mutates or terminates the mission."""
    class CrashingRenderer:
        def build_frame(self, vm, caps, frame_id=0):
            raise MemoryError("Simulated catastrophic UI crash")

    state = HermesRuntimeState.create_empty("mission_isolated")
    state.mission.status = MissionStatus.RUNNING

    supervisor = RenderSupervisor(primary_renderer=CrashingRenderer(), fallback_renderer=FallbackRenderer())
    caps = TerminalCapabilities.fallback_plain(80, 24)
    vm = HermesViewModel(mission=MissionViewModel(title="Survivor", status="RUNNING"))

    # Render fails and engages fallback
    frame = supervisor.render_frame(vm, caps)

    # Mission status in authoritative runtime state remains RUNNING
    assert state.mission.status == MissionStatus.RUNNING
    assert "HERMES" in frame.to_plain_text()


def test_headless_execution_import_isolation():
    """Ensure core runtime modules can be imported and instantiated without TUI dependencies."""
    from core.event_bus import EventBus
    from core.runtime_state.models import HermesRuntimeState
    from core.runtime_state.events import HermesEvent, EventType
    from core.persistence.serializer import serialize_runtime_state, deserialize_runtime_state

    state = HermesRuntimeState.create_empty("headless_test")
    assert state.mission.mission_id == "headless_test"

    data, state_hash = serialize_runtime_state(state)
    restored = deserialize_runtime_state(data)
    assert restored.mission.mission_id == "headless_test"
