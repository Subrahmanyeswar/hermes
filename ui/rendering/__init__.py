# ui/rendering/__init__.py
"""Terminal UI Rendering Subsystem."""

from ui.rendering.text_safety import sanitize_terminal_text, get_char_width, get_string_display_width
from ui.rendering.terminal_capabilities import TerminalCapabilities, ColorDepth
from ui.rendering.screen_buffer import ScreenCell, ScreenFrame, ScreenBuffer
from ui.rendering.frame_diff import FrameDiffer, FrameDiffResult, DiffRun
from ui.rendering.terminal_writer import TerminalWriter
from ui.rendering.virtualization import VirtualList, VirtualRange
from ui.rendering.layout import LayoutEngine, Rect, LayoutGeometry
from ui.rendering.renderer_protocol import RendererProtocol
from ui.rendering.fallback_renderer import FallbackRenderer
from ui.rendering.renderer import TuiRenderer
from ui.rendering.render_supervisor import RenderSupervisor, CircuitState
from ui.rendering.render_scheduler import RenderScheduler

__all__ = [
    "sanitize_terminal_text",
    "get_char_width",
    "get_string_display_width",
    "TerminalCapabilities",
    "ColorDepth",
    "ScreenCell",
    "ScreenFrame",
    "ScreenBuffer",
    "FrameDiffer",
    "FrameDiffResult",
    "DiffRun",
    "TerminalWriter",
    "VirtualList",
    "VirtualRange",
    "LayoutEngine",
    "Rect",
    "LayoutGeometry",
    "RendererProtocol",
    "FallbackRenderer",
    "TuiRenderer",
    "RenderSupervisor",
    "CircuitState",
    "RenderScheduler",
]
