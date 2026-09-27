# tests/test_tui_screen_buffer_and_diff.py
"""Tests for ScreenBuffer, ScreenFrame, and FrameDiffer."""

import pytest
from ui.rendering.screen_buffer import ScreenBuffer, ScreenCell
from ui.rendering.frame_diff import FrameDiffer


def test_screen_buffer_put_char_and_clipping():
    buf = ScreenBuffer(80, 24)

    # Basic write
    w = buf.put_char(0, 0, "A", fg="red", bold=True)
    assert w == 1
    cell = buf.snapshot().get_cell(0, 0)
    assert cell.glyph == "A"
    assert cell.fg == "red"
    assert cell.bold is True

    # Wide char write
    w2 = buf.put_char(2, 0, "你")
    assert w2 == 2
    frame = buf.snapshot()
    assert frame.get_cell(2, 0).glyph == "你"
    assert frame.get_cell(2, 0).width == 2
    assert frame.get_cell(3, 0).width == 0  # Continuation cell

    # Out of bounds clipping - must not throw IndexError
    w_oob = buf.put_char(100, 50, "Z")
    assert w_oob == 0
    w_neg = buf.put_char(-5, -5, "Z")
    assert w_neg == 0


def test_screen_buffer_put_string_and_box():
    buf = ScreenBuffer(40, 10)
    buf.put_string(0, 0, "Hello World", fg="cyan")
    frame = buf.snapshot()
    assert frame.to_plain_text().startswith("Hello World")

    buf.draw_box(0, 2, 20, 5, title="Box Title")
    frame_box = buf.snapshot()
    text = frame_box.to_plain_text()
    assert "Box Title" in text
    assert "┌" in text or "╭" in text


def test_frame_diff_identical_frames():
    buf = ScreenBuffer(40, 10)
    buf.put_string(0, 0, "Static Frame Content")
    frame_a = buf.snapshot(frame_id=1, state_revision=1)
    frame_b = buf.snapshot(frame_id=2, state_revision=2)

    diff = FrameDiffer.diff(frame_a, frame_b)
    assert diff.is_full_repaint is False
    assert diff.changed_rows == 0
    assert len(diff.runs) == 0


def test_frame_diff_partial_modification():
    buf_a = ScreenBuffer(40, 10)
    buf_a.put_string(0, 0, "Line 0 Unchanged")
    buf_a.put_string(0, 1, "Line 1 Old")
    frame_a = buf_a.snapshot(frame_id=1, state_revision=1)

    buf_b = ScreenBuffer(40, 10)
    buf_b.put_string(0, 0, "Line 0 Unchanged")
    buf_b.put_string(0, 1, "Line 1 New")
    frame_b = buf_b.snapshot(frame_id=2, state_revision=2)

    diff = FrameDiffer.diff(frame_a, frame_b)
    assert diff.is_full_repaint is False
    assert diff.changed_rows == 1
    assert diff.unchanged_rows == 9
    assert len(diff.runs) >= 1
    # Only row 1 has diff run
    assert diff.runs[0].y == 1


def test_frame_diff_dimension_change_triggers_full_repaint():
    buf_a = ScreenBuffer(80, 24)
    frame_a = buf_a.snapshot(frame_id=1, state_revision=1)

    buf_b = ScreenBuffer(100, 30)
    frame_b = buf_b.snapshot(frame_id=2, state_revision=2)

    diff = FrameDiffer.diff(frame_a, frame_b)
    assert diff.is_full_repaint is True
    assert diff.changed_rows == 30
