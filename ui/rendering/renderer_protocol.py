# ui/rendering/renderer_protocol.py
"""Protocol for HERMES 2.x Renderers."""

from __future__ import annotations

from typing import Protocol

from ui.rendering.screen_buffer import ScreenFrame
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.viewmodels.root import HermesViewModel


class RendererProtocol(Protocol):
    """Contract that any compliant HERMES renderer must fulfill."""

    def build_frame(
        self,
        view_model: HermesViewModel,
        capabilities: TerminalCapabilities,
        frame_id: int = 0,
    ) -> ScreenFrame:
        """
        Produce an immutable ScreenFrame from view_model and capabilities.
        Must be pure and side-effect free.
        """
        ...
