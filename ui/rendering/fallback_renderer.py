# ui/rendering/fallback_renderer.py
"""
Minimal, Crashproof Fallback Renderer.

STRICT INVARIANTS:
1. CANNOT CRASH: Zero external dependencies, pure array manipulations, guarded writes.
2. TRUTHFUL: Displays actual view-model state (no fabricated progress or success).
3. ACTIVATION: Engaged whenever primary renderer fails or terminal is degraded.
"""

from __future__ import annotations

from ui.rendering.renderer_protocol import RendererProtocol
from ui.rendering.screen_buffer import ScreenBuffer, ScreenFrame
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.rendering.text_safety import sanitize_terminal_text
from ui.viewmodels.root import HermesViewModel


class FallbackRenderer(RendererProtocol):
    """Guaranteed crash-safe minimal renderer for degraded terminal states."""

    def build_frame(
        self,
        view_model: HermesViewModel,
        capabilities: TerminalCapabilities,
        frame_id: int = 0,
    ) -> ScreenFrame:
        width = max(10, capabilities.width)
        height = max(5, capabilities.height)
        buf = ScreenBuffer(width, height)

        try:
            m = view_model.mission
            p = view_model.progress
            s = view_model.session

            # Row 0: Banner
            buf.put_string(0, 0, f"HERMES | {m.status} | DEGRADED FALLBACK", fg="yellow", bold=True)

            # Row 1: Mission
            buf.put_string(0, 1, f"Mission: {m.title[:50]} (ID: {m.mission_id[:12]})", fg="white")

            # Row 2: Task / Progress
            if height > 2:
                buf.put_string(0, 2, f"Task: {p.active_task_title[:45]} | Progress: {p.percentage_str}", fg="cyan")

            # Row 3: Action / State
            if height > 3:
                buf.put_string(0, 3, f"Action: {p.current_action[:50]}", fg="white")

            # Row 4: Checkpoint / Session
            if height > 4:
                chk_id = s.current_checkpoint_id or "None"
                buf.put_string(0, 4, f"Session: {s.session_id[:12]} | Checkpoint: {chk_id[:10]}", fg="gray")

            # Row 5+: Notifications / Warnings
            y = 5
            for notif in view_model.active_notifications:
                if y >= height - 2:
                    break
                buf.put_string(0, y, f"! {notif[:width - 4]}", fg="bright_yellow")
                y += 1

            # Footer: Input & Controls
            if height > 1:
                foot_y = height - 1
                buf.put_string(0, foot_y, "[TUI degraded: fallback active] | [Ctrl+C] cancel", fg="gray", dim=True)

        except Exception as e:
            # Absolute ultimate emergency fallback
            buf.clear()
            buf.put_string(0, 0, "HERMES [FALLBACK RECOVERY]", fg="red", bold=True)
            buf.put_string(0, 1, f"Status: {getattr(view_model.mission, 'status', 'UNKNOWN')}", fg="white")
            if height > 2:
                buf.put_string(0, height - 1, "[Ctrl+C] Cancel", fg="gray")

        return buf.snapshot(frame_id=frame_id, state_revision=view_model.revision)
