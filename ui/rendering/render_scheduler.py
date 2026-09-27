# ui/rendering/render_scheduler.py
"""
Adaptive Render Scheduler and Frame Coalescer.

Features:
1. Coalesces event bursts into single render frames (latest state wins).
2. Adaptive FPS throttling (~30 FPS active, 60 FPS streaming, 0 FPS idle).
3. Backpressure-safe: Drops obsolete intermediate frames without blocking backend execution.
4. Generational sequencing: Rejects late/stale frames.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from ui.rendering.frame_diff import FrameDiffResult, FrameDiffer
from ui.rendering.render_supervisor import RenderSupervisor
from ui.rendering.screen_buffer import ScreenFrame
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.rendering.terminal_writer import TerminalWriter
from ui.viewmodels.root import HermesViewModel


class RenderScheduler:
    """Manages frame scheduling, rate limiting, and burst coalescing."""

    def __init__(
        self,
        supervisor: RenderSupervisor,
        writer: TerminalWriter,
        target_fps: float = 30.0,
        streaming_fps: float = 60.0,
    ):
        self.supervisor = supervisor
        self.writer = writer
        self.min_frame_interval: float = 1.0 / max(1.0, target_fps)
        self.min_streaming_interval: float = 1.0 / max(1.0, streaming_fps)

        self._last_render_time: float = 0.0
        self._current_frame_id: int = 0
        self._last_rendered_frame: Optional[ScreenFrame] = None
        self._pending_vm: Optional[HermesViewModel] = None
        self._latest_revision: int = 0

        # Diagnostics
        self.frames_rendered: int = 0
        self.frames_skipped: int = 0
        self.coalesced_count: int = 0
        self.full_repaints: int = 0
        self.total_diff_bytes: int = 0

    def request_render(
        self,
        view_model: HermesViewModel,
        urgent: bool = False,
    ) -> bool:
        """
        Notify scheduler of updated view model.
        Returns True if render was executed immediately, False if coalesced or skipped.
        """
        now = time.perf_counter()
        interval = self.min_streaming_interval if view_model.chat.is_streaming else self.min_frame_interval

        if view_model.revision < self._latest_revision:
            # Stale frame delivered out of order: discard
            self.frames_skipped += 1
            return False

        self._latest_revision = view_model.revision
        time_since_last = now - self._last_render_time

        if not urgent and time_since_last < interval:
            # Coalesce: save as pending, skip immediate write
            self._pending_vm = view_model
            self.coalesced_count += 1
            return False

        # Execute render now
        return self._render_now(view_model)

    def flush_pending(self, force_full_repaint: bool = False) -> bool:
        """Render any pending coalesced view model immediately."""
        if self._pending_vm is not None:
            vm = self._pending_vm
            self._pending_vm = None
            return self._render_now(vm, force_full_repaint=force_full_repaint)
        return False

    def _render_now(
        self,
        view_model: HermesViewModel,
        force_full_repaint: bool = False,
    ) -> bool:
        self._current_frame_id += 1
        frame_id = self._current_frame_id

        # 1. Build frame via supervisor (with exception isolation)
        new_frame = self.supervisor.render_frame(
            view_model,
            self.writer.capabilities,
            frame_id=frame_id,
        )

        # 2. Compute minimal diff
        diff = FrameDiffer.diff(
            self._last_rendered_frame,
            new_frame,
            force_full_repaint=force_full_repaint,
        )

        # 3. Write diff to terminal
        bytes_written = self.writer.write_diff(diff)

        # 4. Update metrics & state
        self._last_render_time = time.perf_counter()
        self._last_rendered_frame = new_frame
        self.frames_rendered += 1
        self.total_diff_bytes += bytes_written
        if diff.is_full_repaint:
            self.full_repaints += 1

        return True

    def get_stats(self) -> Dict[str, Any]:
        """Return diagnostic metrics."""
        return {
            "frames_rendered": self.frames_rendered,
            "frames_skipped": self.frames_skipped,
            "coalesced_count": self.coalesced_count,
            "full_repaints": self.full_repaints,
            "total_diff_bytes": self.total_diff_bytes,
            "supervisor": self.supervisor.get_stats(),
        }
