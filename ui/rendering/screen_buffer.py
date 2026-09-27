# ui/rendering/screen_buffer.py
"""
Deterministic, Double-Buffered Terminal Screen Matrix.

Features:
1. Exact character-cell geometry with full-width (CJK/emoji) handling and continuation cells.
2. Complete clipping bounds enforcement (never raises IndexError on overflow).
3. Immutable ScreenFrame snapshots for deterministic frame diffing.
4. Clean Unicode and ANSI serialization.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple, Any

from ui.rendering.text_safety import get_char_width, sanitize_terminal_text


@dataclass(frozen=True)
class ScreenCell:
    """An individual character cell on the terminal canvas."""
    glyph: str = " "
    fg: Optional[str] = None       # e.g., "red", "#ff0000", "green", None
    bg: Optional[str] = None
    bold: bool = False
    dim: bool = False
    underline: bool = False
    reverse: bool = False
    width: int = 1                 # 1 for standard, 2 for leading wide, 0 for trailing wide continuation

    @classmethod
    def empty(cls) -> ScreenCell:
        return cls()

    @classmethod
    def continuation(cls) -> ScreenCell:
        return cls(glyph="", width=0)


@dataclass(frozen=True)
class ScreenFrame:
    """Immutable point-in-time snapshot of a rendered screen."""
    width: int
    height: int
    cells: Tuple[Tuple[ScreenCell, ...], ...]
    frame_id: int
    state_revision: int
    timestamp: float

    def get_cell(self, x: int, y: int) -> ScreenCell:
        if 0 <= y < self.height and 0 <= x < self.width:
            return self.cells[y][x]
        return ScreenCell.empty()

    def to_plain_text(self) -> str:
        """Serialize frame to plain text lines."""
        lines = []
        for y in range(self.height):
            line_chars = []
            for x in range(self.width):
                cell = self.cells[y][x]
                if cell.width > 0:
                    line_chars.append(cell.glyph)
            lines.append("".join(line_chars).rstrip())
        return "\n".join(lines)


class ScreenBuffer:
    """
    Mutable drawing canvas for a single frame.
    Supports clipping, box drawing, text wrapping, and color attributes.
    """

    def __init__(self, width: int, height: int):
        self.width = max(10, width)
        self.height = max(5, height)
        self._grid: List[List[ScreenCell]] = [
            [ScreenCell.empty() for _ in range(self.width)]
            for _ in range(self.height)
        ]

    def clear(self) -> None:
        """Reset all cells to empty."""
        for y in range(self.height):
            for x in range(self.width):
                self._grid[y][x] = ScreenCell.empty()

    def put_char(
        self,
        x: int,
        y: int,
        ch: str,
        *,
        fg: Optional[str] = None,
        bg: Optional[str] = None,
        bold: bool = False,
        dim: bool = False,
        underline: bool = False,
        reverse: bool = False,
    ) -> int:
        """
        Put a single character at (x, y) with boundary clipping and wide-character awareness.
        Returns the cell width consumed (0, 1, or 2).
        """
        if not (0 <= y < self.height and 0 <= x < self.width):
            return 0

        ch_width = get_char_width(ch)
        if ch_width == 0:
            return 0

        if ch_width == 1:
            self._grid[y][x] = ScreenCell(
                glyph=ch, fg=fg, bg=bg, bold=bold, dim=dim, underline=underline, reverse=reverse, width=1
            )
            return 1
        elif ch_width == 2:
            # If wide char doesn't fit on the row, clip or don't write
            if x + 1 >= self.width:
                self._grid[y][x] = ScreenCell(glyph=" ", width=1)
                return 1
            self._grid[y][x] = ScreenCell(
                glyph=ch, fg=fg, bg=bg, bold=bold, dim=dim, underline=underline, reverse=reverse, width=2
            )
            self._grid[y][x + 1] = ScreenCell.continuation()
            return 2
        return 0

    def put_string(
        self,
        x: int,
        y: int,
        text: str,
        *,
        fg: Optional[str] = None,
        bg: Optional[str] = None,
        bold: bool = False,
        dim: bool = False,
        underline: bool = False,
        reverse: bool = False,
        max_width: Optional[int] = None,
    ) -> int:
        """
        Write string horizontally at (x, y) with clipping.
        Returns total columns written.
        """
        if y < 0 or y >= self.height or x >= self.width:
            return 0

        safe_text = sanitize_terminal_text(text, allow_newlines=False)
        curr_x = x
        limit = self.width if max_width is None else min(self.width, x + max_width)

        for ch in safe_text:
            if curr_x >= limit:
                break
            w = get_char_width(ch)
            if curr_x + w > limit:
                break
            consumed = self.put_char(
                curr_x, y, ch, fg=fg, bg=bg, bold=bold, dim=dim, underline=underline, reverse=reverse
            )
            curr_x += consumed

        return curr_x - x

    def fill_rect(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        ch: str = " ",
        *,
        fg: Optional[str] = None,
        bg: Optional[str] = None,
    ) -> None:
        """Fill a rectangular area with a character."""
        for cy in range(max(0, y), min(self.height, y + h)):
            for cx in range(max(0, x), min(self.width, x + w)):
                self.put_char(cx, cy, ch, fg=fg, bg=bg)

    def draw_box(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        title: Optional[str] = None,
        *,
        fg: Optional[str] = None,
        bg: Optional[str] = None,
        style: str = "single",  # "single" or "double" or "rounded"
    ) -> None:
        """Draw a box frame with optional title."""
        if w < 2 or h < 2:
            return

        # Box characters
        if style == "rounded":
            tl, tr, bl, br, hz, vt = "╭", "╮", "╰", "╯", "─", "│"
        elif style == "double":
            tl, tr, bl, br, hz, vt = "╔", "╗", "╚", "╝", "═", "║"
        else:
            tl, tr, bl, br, hz, vt = "┌", "┐", "└", "┘", "─", "│"

        # Corners
        self.put_char(x, y, tl, fg=fg, bg=bg)
        self.put_char(x + w - 1, y, tr, fg=fg, bg=bg)
        self.put_char(x, y + h - 1, bl, fg=fg, bg=bg)
        self.put_char(x + w - 1, y + h - 1, br, fg=fg, bg=bg)

        # Horizontal edges
        for cx in range(x + 1, x + w - 1):
            self.put_char(cx, y, hz, fg=fg, bg=bg)
            self.put_char(cx, y + h - 1, hz, fg=fg, bg=bg)

        # Vertical edges
        for cy in range(y + 1, y + h - 1):
            self.put_char(x, cy, vt, fg=fg, bg=bg)
            self.put_char(x + w - 1, cy, vt, fg=fg, bg=bg)

        # Title
        if title:
            clean_title = f" {sanitize_terminal_text(title, allow_newlines=False)} "
            self.put_string(x + 2, y, clean_title, fg=fg, bg=bg, bold=True, max_width=w - 4)

    def snapshot(self, frame_id: int = 0, state_revision: int = 0) -> ScreenFrame:
        """Return an immutable snapshot of the current canvas state."""
        frozen_cells = tuple(
            tuple(row) for row in self._grid
        )
        return ScreenFrame(
            width=self.width,
            height=self.height,
            cells=frozen_cells,
            frame_id=frame_id,
            state_revision=state_revision,
            timestamp=time.time(),
        )
