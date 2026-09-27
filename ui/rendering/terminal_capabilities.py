# ui/rendering/terminal_capabilities.py
"""
Terminal Capability Detection and Graceful Degradation Model.

Detects terminal dimensions, color fidelity, Unicode support, and control modes.
Never crashes when stdout is redirected, non-interactive, or running in CI.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ColorDepth(str, Enum):
    NO_COLOR = "NO_COLOR"
    ANSI_16 = "ANSI_16"
    ANSI_256 = "ANSI_256"
    TRUECOLOR = "TRUECOLOR"


@dataclass(frozen=True)
class TerminalCapabilities:
    """Immutable record of terminal capabilities."""
    is_tty: bool
    width: int
    height: int
    color_depth: ColorDepth
    unicode_supported: bool
    mouse_supported: bool
    bracketed_paste_supported: bool
    alternate_screen_supported: bool
    is_windows: bool
    term_type: str = ""

    @classmethod
    def detect(cls, override_stream: Optional[Any] = None) -> TerminalCapabilities:
        """
        Probe terminal environment safely without side effects.
        """
        stream = override_stream or sys.stdout
        is_tty = hasattr(stream, "isatty") and stream.isatty()

        # Dimensions
        try:
            size = shutil.get_terminal_size(fallback=(80, 24))
            width, height = max(10, size.columns), max(5, size.lines)
        except Exception:
            width, height = 80, 24

        term = os.environ.get("TERM", "").lower()
        colorterm = os.environ.get("COLORTERM", "").lower()
        no_color = "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb"

        is_win = sys.platform.startswith("win")
        wt_session = "WT_SESSION" in os.environ

        # Color depth
        if no_color or not is_tty:
            color_depth = ColorDepth.NO_COLOR
        elif colorterm in ("truecolor", "24bit") or wt_session:
            color_depth = ColorDepth.TRUECOLOR
        elif "256color" in term or "xterm" in term:
            color_depth = ColorDepth.ANSI_256
        elif is_win:
            color_depth = ColorDepth.ANSI_16
        else:
            color_depth = ColorDepth.ANSI_16

        # Unicode support
        encoding = getattr(stream, "encoding", "") or "utf-8"
        unicode_supported = "utf" in encoding.lower() or wt_session or not is_win

        # Mouse & Bracketed paste
        mouse_supported = is_tty and (wt_session or "xterm" in term or not is_win)
        bracketed_paste_supported = is_tty and (wt_session or "xterm" in term or not is_win)
        alternate_screen_supported = is_tty and term != "dumb"

        return cls(
            is_tty=is_tty,
            width=width,
            height=height,
            color_depth=color_depth,
            unicode_supported=unicode_supported,
            mouse_supported=mouse_supported,
            bracketed_paste_supported=bracketed_paste_supported,
            alternate_screen_supported=alternate_screen_supported,
            is_windows=is_win,
            term_type=term,
        )

    def with_dimensions(self, width: int, height: int) -> TerminalCapabilities:
        """Return a copy with updated dimensions."""
        return TerminalCapabilities(
            is_tty=self.is_tty,
            width=max(10, width),
            height=max(5, height),
            color_depth=self.color_depth,
            unicode_supported=self.unicode_supported,
            mouse_supported=self.mouse_supported,
            bracketed_paste_supported=self.bracketed_paste_supported,
            alternate_screen_supported=self.alternate_screen_supported,
            is_windows=self.is_windows,
            term_type=self.term_type,
        )

    @classmethod
    def fallback_plain(cls, width: int = 80, height: int = 24) -> TerminalCapabilities:
        """Create a minimal plain capability set for headless/CI/fallback environments."""
        return cls(
            is_tty=False,
            width=width,
            height=height,
            color_depth=ColorDepth.NO_COLOR,
            unicode_supported=True,
            mouse_supported=False,
            bracketed_paste_supported=False,
            alternate_screen_supported=False,
            is_windows=sys.platform.startswith("win"),
            term_type="dumb",
        )
