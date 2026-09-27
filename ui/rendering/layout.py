# ui/rendering/layout.py
"""
Deterministic Terminal Layout Engine.

Calculates panel geometry rectangles based on terminal capabilities and dimensions.
Features prioritized degradation down to 20x5 without negative sizes or overflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Rect:
    """A 2D bounding box on the screen."""
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


@dataclass(frozen=True)
class LayoutGeometry:
    """Complete layout partitioning for a frame."""
    header: Rect
    chat: Rect
    right_panel: Optional[Rect]
    active_operation: Rect
    input_bar: Rect
    modal: Optional[Rect] = None


class LayoutEngine:
    """Computes deterministic layout rectangles."""

    @staticmethod
    def compute(
        width: int,
        height: int,
        has_modal: bool = False,
        split_ratio: float = 0.55,
    ) -> LayoutGeometry:
        w = max(10, width)
        h = max(5, height)

        # 1. Tiny screen (< 40x12)
        if w < 50 or h < 14:
            header_rect = Rect(x=0, y=0, w=w, h=1)
            input_rect = Rect(x=0, y=max(1, h - 1), w=w, h=1)
            active_rect = Rect(x=0, y=1, w=w, h=min(1, max(0, h - 2)))
            chat_h = max(0, h - 3)
            chat_rect = Rect(x=0, y=2, w=w, h=chat_h)
            modal_rect = None
            if has_modal and w >= 20 and h >= 8:
                modal_rect = Rect(x=2, y=2, w=w - 4, h=h - 4)
            return LayoutGeometry(
                header=header_rect,
                chat=chat_rect,
                right_panel=None,
                active_operation=active_rect,
                input_bar=input_rect,
                modal=modal_rect,
            )

        # 2. Medium screen (< 90 width or < 22 height) -> Single column (chat only)
        if w < 90 or h < 20:
            header_h = 2
            input_h = 2
            active_h = 1
            chat_h = max(2, h - header_h - input_h - active_h)

            header_rect = Rect(x=0, y=0, w=w, h=header_h)
            active_rect = Rect(x=0, y=header_h, w=w, h=active_h)
            chat_rect = Rect(x=0, y=header_h + active_h, w=w, h=chat_h)
            input_rect = Rect(x=0, y=h - input_h, w=w, h=input_h)

            modal_rect = None
            if has_modal:
                mw = min(60, max(20, w - 8))
                mh = min(12, max(6, h - 6))
                modal_rect = Rect(x=(w - mw) // 2, y=(h - mh) // 2, w=mw, h=mh)

            return LayoutGeometry(
                header=header_rect,
                chat=chat_rect,
                right_panel=None,
                active_operation=active_rect,
                input_bar=input_rect,
                modal=modal_rect,
            )

        # 3. Standard / Full screen (>= 90 width, >= 20 height)
        header_h = 3
        input_h = 3
        active_h = 1
        main_h = max(4, h - header_h - input_h - active_h)

        header_rect = Rect(x=0, y=0, w=w, h=header_h)
        active_rect = Rect(x=0, y=header_h, w=w, h=active_h)

        left_w = int(w * split_ratio)
        right_w = w - left_w

        chat_rect = Rect(x=0, y=header_h + active_h, w=left_w, h=main_h)
        right_rect = Rect(x=left_w, y=header_h + active_h, w=right_w, h=main_h)
        input_rect = Rect(x=0, y=h - input_h, w=w, h=input_h)

        modal_rect = None
        if has_modal:
            mw = min(70, max(30, int(w * 0.7)))
            mh = min(16, max(8, int(h * 0.6)))
            modal_rect = Rect(x=(w - mw) // 2, y=(h - mh) // 2, w=mw, h=mh)

        return LayoutGeometry(
            header=header_rect,
            chat=chat_rect,
            right_panel=right_rect,
            active_operation=active_rect,
            input_bar=input_rect,
            modal=modal_rect,
        )
