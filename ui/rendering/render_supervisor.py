# ui/rendering/render_supervisor.py
"""
RenderSupervisor and Failure Isolation Circuit Breaker.

STRICT INVARIANTS:
1. UI FAILURE != MISSION FAILURE.
2. Render exceptions are caught, logged, and isolated.
3. Automatically transitions to FallbackRenderer upon primary failure.
4. Circuit breaker protects against infinite retry storms.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from ui.rendering.fallback_renderer import FallbackRenderer
from ui.rendering.renderer_protocol import RendererProtocol
from ui.rendering.screen_buffer import ScreenFrame
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.viewmodels.root import HermesViewModel


class CircuitState(str, Enum):
    PRIMARY = "PRIMARY"
    DEGRADED = "DEGRADED"
    FALLBACK = "FALLBACK"
    PROBING = "PROBING"


class RenderSupervisor:
    """Supervises rendering health, isolating exceptions and engaging fallback."""

    def __init__(
        self,
        primary_renderer: RendererProtocol,
        fallback_renderer: Optional[RendererProtocol] = None,
        max_consecutive_failures: int = 3,
        probe_success_threshold: int = 5,
    ):
        self.primary = primary_renderer
        self.fallback = fallback_renderer or FallbackRenderer()
        self.max_failures = max_consecutive_failures
        self.probe_threshold = probe_success_threshold

        self.circuit_state = CircuitState.PRIMARY
        self._consecutive_failures: int = 0
        self._consecutive_fallback_successes: int = 0

        # Diagnostics counters
        self.frames_generated: int = 0
        self.primary_successes: int = 0
        self.primary_failures: int = 0
        self.fallback_activations: int = 0
        self.last_error: Optional[str] = None

    def render_frame(
        self,
        view_model: HermesViewModel,
        capabilities: TerminalCapabilities,
        frame_id: int = 0,
    ) -> ScreenFrame:
        """
        Build an immutable ScreenFrame with guaranteed exception isolation.
        """
        self.frames_generated += 1

        # Check circuit state
        if self.circuit_state == CircuitState.FALLBACK:
            return self._render_with_fallback(view_model, capabilities, frame_id)

        # Attempt primary rendering
        try:
            frame = self.primary.build_frame(view_model, capabilities, frame_id)
            self._on_primary_success()
            return frame
        except Exception as e:
            self._on_primary_failure(e)
            return self._render_with_fallback(view_model, capabilities, frame_id)

    def _render_with_fallback(
        self,
        view_model: HermesViewModel,
        capabilities: TerminalCapabilities,
        frame_id: int = 0,
    ) -> ScreenFrame:
        self.fallback_activations += 1
        try:
            frame = self.fallback.build_frame(view_model, capabilities, frame_id)
            self._consecutive_fallback_successes += 1
            if (
                self.circuit_state == CircuitState.FALLBACK
                and self._consecutive_fallback_successes >= self.probe_threshold
            ):
                # Probe returning to primary
                self.circuit_state = CircuitState.PROBING
            return frame
        except Exception as e:
            # Guaranteed emergency fallback
            self.last_error = f"Fallback error: {e}"
            return FallbackRenderer().build_frame(view_model, capabilities, frame_id)

    def _on_primary_success(self) -> None:
        self.primary_successes += 1
        self._consecutive_failures = 0
        if self.circuit_state == CircuitState.PROBING:
            self.circuit_state = CircuitState.PRIMARY
            self._consecutive_fallback_successes = 0

    def _on_primary_failure(self, error: Exception) -> None:
        self.primary_failures += 1
        self._consecutive_failures += 1
        self.last_error = str(error)

        if self._consecutive_failures >= self.max_failures:
            self.circuit_state = CircuitState.FALLBACK
            self._consecutive_fallback_successes = 0
        else:
            self.circuit_state = CircuitState.DEGRADED

    def get_stats(self) -> Dict[str, Any]:
        """Return diagnostic metrics without side effects."""
        return {
            "circuit_state": self.circuit_state.value,
            "frames_generated": self.frames_generated,
            "primary_successes": self.primary_successes,
            "primary_failures": self.primary_failures,
            "fallback_activations": self.fallback_activations,
            "last_error": self.last_error,
        }
