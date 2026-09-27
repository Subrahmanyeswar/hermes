# ui/rendering/terminal_writer.py
"""
Terminal Output Writer and Safe ANSI Stream Emitter.

Responsibilities:
1. Translate FrameDiffResult into capability-aware ANSI escape sequences.
2. Safe writing with broken pipe/redirected output error containment.
3. Cursor hiding and alternate screen buffer lifecycle management.
4. Color translation (NO_COLOR, ANSI_16, ANSI_256, TRUECOLOR).
5. Never propagate terminal I/O exceptions into the caller.
"""

from __future__ import annotations

import io
import sys
from typing import Optional, TextIO, Tuple

from ui.rendering.frame_diff import FrameDiffResult, DiffRun
from ui.rendering.screen_buffer import ScreenCell
from ui.rendering.terminal_capabilities import TerminalCapabilities, ColorDepth


_COLOR_NAME_TO_ANSI_16 = {
    "black": 30,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "blue": 34,
    "magenta": 35,
    "cyan": 36,
    "white": 37,
    "gray": 90,
    "grey": 90,
    "bright_red": 91,
    "bright_green": 92,
    "bright_yellow": 93,
    "bright_blue": 94,
    "bright_magenta": 95,
    "bright_cyan": 96,
    "bright_white": 97,
}


def _hex_to_rgb(hex_code: str) -> Optional[Tuple[int, int, int]]:
    """Convert #rrggbb to RGB tuple."""
    hex_clean = hex_code.lstrip("#")
    if len(hex_clean) == 6:
        try:
            return (
                int(hex_clean[0:2], 16),
                int(hex_clean[2:4], 16),
                int(hex_clean[4:6], 16),
            )
        except ValueError:
            return None
    return None


class TerminalWriter:
    """Writes rendered frame diffs to a terminal stream."""

    def __init__(
        self,
        stream: Optional[TextIO] = None,
        capabilities: Optional[TerminalCapabilities] = None,
    ):
        self.stream = stream or sys.stdout
        self.capabilities = capabilities or TerminalCapabilities.detect(self.stream)
        self.is_alive: bool = True
        self._last_style: Optional[Tuple[Any, ...]] = None

    def enter_alternate_screen(self) -> None:
        """Switch to alternate screen buffer and hide cursor if supported."""
        if not self.is_alive or not self.capabilities.alternate_screen_supported:
            return
        try:
            self.stream.write("\033[?1049h\033[?25l")
            self.stream.flush()
        except Exception:
            self.is_alive = False

    def exit_alternate_screen(self) -> None:
        """Restore standard screen buffer and unhide cursor."""
        if not self.is_alive or not self.capabilities.alternate_screen_supported:
            return
        try:
            self.stream.write("\033[?1049l\033[?25h\033[0m")
            self.stream.flush()
        except Exception:
            self.is_alive = False

    def write_diff(self, diff: FrameDiffResult) -> int:
        """
        Write diff runs to terminal stream.
        Returns total bytes written.
        """
        if not self.is_alive:
            return 0

        out = io.StringIO()

        if diff.is_full_repaint:
            # Clear screen and move cursor home
            out.write("\033[2J\033[H")
            self._last_style = None

        for run in diff.runs:
            # Position cursor at (run.x + 1, run.y + 1)
            out.write(f"\033[{run.y + 1};{run.x + 1}H")
            for cell in run.cells:
                if cell.width == 0:
                    continue  # Wide continuation cell
                style_key = (cell.fg, cell.bg, cell.bold, cell.dim, cell.underline, cell.reverse)
                if style_key != self._last_style:
                    out.write(self._format_sgr(cell))
                    self._last_style = style_key
                out.write(cell.glyph)

        # Reset formatting at end of frame
        if self._last_style is not None:
            out.write("\033[0m")
            self._last_style = None

        content = out.getvalue()
        if not content:
            return 0

        try:
            self.stream.write(content)
            self.stream.flush()
            return len(content.encode("utf-8", "replace"))
        except Exception:
            self.is_alive = False
            return 0

    def _format_sgr(self, cell: ScreenCell) -> str:
        """Generate SGR formatting codes based on capabilities."""
        if self.capabilities.color_depth == ColorDepth.NO_COLOR:
            return ""

        codes = ["0"]  # Reset before applying attributes
        if cell.bold:
            codes.append("1")
        if cell.dim:
            codes.append("2")
        if cell.underline:
            codes.append("4")
        if cell.reverse:
            codes.append("7")

        if cell.fg:
            fg_sgr = self._get_color_sgr(cell.fg, is_bg=False)
            if fg_sgr:
                codes.append(fg_sgr)

        if cell.bg:
            bg_sgr = self._get_color_sgr(cell.bg, is_bg=True)
            if bg_sgr:
                codes.append(bg_sgr)

        return f"\033[{';'.join(codes)}m"

    def _get_color_sgr(self, color_str: str, is_bg: bool) -> Optional[str]:
        offset = 10 if is_bg else 0

        # Named ANSI 16 color
        if color_str.lower() in _COLOR_NAME_TO_ANSI_16:
            code = _COLOR_NAME_TO_ANSI_16[color_str.lower()] + offset
            return str(code)

        # Hex / RGB Truecolor
        rgb = _hex_to_rgb(color_str)
        if rgb:
            r, g, b = rgb
            if self.capabilities.color_depth == ColorDepth.TRUECOLOR:
                mode = "48;2" if is_bg else "38;2"
                return f"{mode};{r};{g};{b}"
            elif self.capabilities.color_depth == ColorDepth.ANSI_256:
                # Approximate 256 color
                idx = 16 + (36 * int(r / 51)) + (6 * int(g / 51)) + int(b / 51)
                mode = "48;5" if is_bg else "38;5"
                return f"{mode};{idx}"
            elif self.capabilities.color_depth == ColorDepth.ANSI_16:
                # Basic approximation
                is_bright = (r + g + b) > 384
                base = 90 if is_bright else 30
                return str(base + offset + 7)  # default to white/light gray

        return None
