# ui/rendering/frame_diff.py
"""
Deterministic Screen Frame Diffing.

Computes the minimal delta between two consecutive ScreenFrames:
- Skips identical rows
- Identifies contiguous changed runs within modified rows
- Falls back to full repaint on dimension changes, initial frame, or complete desync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from ui.rendering.screen_buffer import ScreenCell, ScreenFrame


@dataclass(frozen=True)
class DiffRun:
    """A contiguous span of updated cells starting at (x, y)."""
    x: int
    y: int
    cells: Tuple[ScreenCell, ...]


@dataclass(frozen=True)
class FrameDiffResult:
    """The result of comparing two frames."""
    is_full_repaint: bool
    runs: Tuple[DiffRun, ...]
    changed_rows: int
    unchanged_rows: int
    frame_id: int
    state_revision: int


class FrameDiffer:
    """Computes minimal differential update operations between ScreenFrames."""

    @staticmethod
    def diff(
        previous: Optional[ScreenFrame],
        current: ScreenFrame,
        force_full_repaint: bool = False,
    ) -> FrameDiffResult:
        """
        Compare previous frame to current frame and return minimal DiffRuns.
        """
        if (
            force_full_repaint
            or previous is None
            or previous.width != current.width
            or previous.height != current.height
        ):
            # Full repaint: generate runs for every non-empty row
            full_runs = []
            for y in range(current.height):
                row_cells = current.cells[y]
                # Filter out pure trailing empty space if desirable, or take entire row
                full_runs.append(DiffRun(x=0, y=y, cells=row_cells))
            return FrameDiffResult(
                is_full_repaint=True,
                runs=tuple(full_runs),
                changed_rows=current.height,
                unchanged_rows=0,
                frame_id=current.frame_id,
                state_revision=current.state_revision,
            )

        changed_runs: List[DiffRun] = []
        changed_rows_count = 0
        unchanged_rows_count = 0

        for y in range(current.height):
            prev_row = previous.cells[y]
            curr_row = current.cells[y]

            if prev_row == curr_row:
                unchanged_rows_count += 1
                continue

            changed_rows_count += 1
            # Row has changes: find contiguous spans of modified cells
            in_run = False
            run_start_x = 0
            run_cells: List[ScreenCell] = []

            for x in range(current.width):
                if prev_row[x] != curr_row[x]:
                    if not in_run:
                        in_run = True
                        run_start_x = x
                        run_cells = [curr_row[x]]
                    else:
                        run_cells.append(curr_row[x])
                else:
                    if in_run:
                        changed_runs.append(
                            DiffRun(x=run_start_x, y=y, cells=tuple(run_cells))
                        )
                        in_run = False
                        run_cells = []

            if in_run:
                changed_runs.append(
                    DiffRun(x=run_start_x, y=y, cells=tuple(run_cells))
                )

        return FrameDiffResult(
            is_full_repaint=False,
            runs=tuple(changed_runs),
            changed_rows=changed_rows_count,
            unchanged_rows=unchanged_rows_count,
            frame_id=current.frame_id,
            state_revision=current.state_revision,
        )
