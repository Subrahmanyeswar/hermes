# ui/__init__.py
"""
HERMES 2.x TUI Subsystem.
Strict projection layer: TUI OBSERVES; TUI DOES NOT DECIDE.
"""

from ui.rendering import (
    sanitize_terminal_text,
    TerminalCapabilities,
    ColorDepth,
    ScreenCell,
    ScreenFrame,
    ScreenBuffer,
    FrameDiffer,
    FrameDiffResult,
    TerminalWriter,
    VirtualList,
    LayoutEngine,
    TuiRenderer,
    FallbackRenderer,
    RenderSupervisor,
    RenderScheduler,
)
from ui.viewmodels import HermesViewModel
from ui.state import build_root_view_model, RuntimeStateSnapshot
from ui.runtime import TuiRuntimeObserver, EventProjector
from ui.input import InputDecoder, InputRouter, CommandParser

__all__ = [
    "sanitize_terminal_text",
    "TerminalCapabilities",
    "ColorDepth",
    "ScreenCell",
    "ScreenFrame",
    "ScreenBuffer",
    "FrameDiffer",
    "FrameDiffResult",
    "TerminalWriter",
    "VirtualList",
    "LayoutEngine",
    "TuiRenderer",
    "FallbackRenderer",
    "RenderSupervisor",
    "RenderScheduler",
    "HermesViewModel",
    "build_root_view_model",
    "RuntimeStateSnapshot",
    "TuiRuntimeObserver",
    "EventProjector",
    "InputDecoder",
    "InputRouter",
    "CommandParser",
]
