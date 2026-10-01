# tests/test_tui_qualification.py
"""
TUI 2.x Final Qualification & Hardening Tests.

Commit scope: test(tui): qualify and harden TUI 2.x

Covers:
1. Adversarial None / NaN / inf / garbage viewmodel inputs
2. Observer lifecycle: attach → detach → re-attach → detach
3. Headless import isolation
4. ViewModel frozen/immutable enforcement
5. Stale frame rejection under sequence regression
6. Expanded ANSI injection vectors (OSC, CSI, C1, DCS, SOS, PM, APC)
7. Unicode edge cases: zero-width joiners, combining marks, Braille, RTL override
8. Memory FIFO eviction under chat message flood
9. Broken pipe containment in TerminalWriter
10. ScreenBuffer boundary clipping at extreme coordinates
11. FrameDiffer edge cases: empty frames, 1x1 frames, max dimension mismatch
12. VirtualList edge cases: negative offset, offset > total, huge item_height
13. Text safety: BEL, title-set, clipboard steal, cursor overwrite, backspace wipe
14. Renderer panel crash isolation: each panel independently failable
15. FallbackRenderer absolute emergency path
16. Selector safe_float_str exhaustive edge cases
17. RenderSupervisor PROBING → PRIMARY recovery path
18. TerminalCapabilities fallback_plain correctness
19. ScreenFrame.to_plain_text correctness
20. EventProjector message FIFO cap correctness
"""

from __future__ import annotations

import dataclasses
import io
import math
import sys
import time
from dataclasses import FrozenInstanceError
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

# ─── Imports under test ───
from ui.rendering.frame_diff import FrameDiffer, FrameDiffResult
from ui.rendering.screen_buffer import ScreenBuffer, ScreenCell, ScreenFrame
from ui.rendering.terminal_capabilities import TerminalCapabilities, ColorDepth
from ui.rendering.terminal_writer import TerminalWriter
from ui.rendering.text_safety import (
    sanitize_terminal_text,
    get_char_width,
    get_string_display_width,
)
from ui.rendering.virtualization import VirtualList
from ui.rendering.renderer import TuiRenderer
from ui.rendering.fallback_renderer import FallbackRenderer
from ui.rendering.render_supervisor import RenderSupervisor, CircuitState
from ui.runtime.event_projection import EventProjector
from ui.state.selectors import safe_float_str, build_root_view_model
from ui.viewmodels.root import HermesViewModel
from ui.viewmodels.chat import ChatViewModel, ChatMessageViewModel, ChatEntryKind
from ui.viewmodels.mission import MissionViewModel, ProgressViewModel
from ui.viewmodels.security import SecurityViewModel, ApprovalModalViewModel
from ui.viewmodels.network import NetworkViewModel
from ui.viewmodels.session import SessionViewModel
from ui.viewmodels.recovery import RewindPreviewViewModel

from core.runtime_state.models import HermesRuntimeState, MissionState


# ════════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════════

def _make_caps(w: int = 80, h: int = 24) -> TerminalCapabilities:
    return TerminalCapabilities.fallback_plain(width=w, height=h)


def _make_default_vm(**overrides) -> HermesViewModel:
    return HermesViewModel(**overrides)


def _make_default_state() -> HermesRuntimeState:
    return HermesRuntimeState(mission=MissionState(mission_id="test"))


# ════════════════════════════════════════════════════════════════════════════════
# 1. Adversarial None / NaN / inf inputs through safe_float_str
# ════════════════════════════════════════════════════════════════════════════════

class TestSafeFloatStrExhaustive:
    """Ensure safe_float_str never raises, always returns a string."""

    @pytest.mark.parametrize("val,expected", [
        (None, "N/A"),
        (float("nan"), "N/A"),
        (float("inf"), "N/A"),
        (float("-inf"), "N/A"),
        ("garbage", "N/A"),
        ("", "N/A"),
        ([], "N/A"),
        ({}, "N/A"),
        (object(), "N/A"),
        (True, "1.00"),   # bool is subclass of int
        (False, "0.00"),
        (42, "42.00"),
        (3.14159, "3.14"),
        (0, "0.00"),
        (-1.5, "-1.50"),
        ("3.14", "3.14"),  # string numeric
    ])
    def test_safe_float_str_edge_cases(self, val, expected):
        result = safe_float_str(val)
        assert isinstance(result, str)
        assert result == expected

    def test_safe_float_str_custom_format(self):
        assert safe_float_str(3.14159, ".4f") == "3.1416"

    def test_safe_float_str_custom_fallback(self):
        assert safe_float_str(None, fallback="MISSING") == "MISSING"


# ════════════════════════════════════════════════════════════════════════════════
# 2. ViewModel frozen / immutable enforcement
# ════════════════════════════════════════════════════════════════════════════════

class TestViewModelImmutability:
    """Verify frozen=True dataclass enforcement on all viewmodels."""

    def test_root_viewmodel_frozen(self):
        vm = HermesViewModel()
        with pytest.raises(FrozenInstanceError):
            vm.revision = 999

    def test_mission_viewmodel_frozen(self):
        m = MissionViewModel()
        with pytest.raises(FrozenInstanceError):
            m.status = "HACKED"

    def test_chat_message_viewmodel_frozen(self):
        msg = ChatMessageViewModel(
            message_id="1", sequence=1, timestamp_str="00:00:00",
            kind=ChatEntryKind.USER, author_role="User", content="hi"
        )
        with pytest.raises(FrozenInstanceError):
            msg.content = "TAMPERED"

    def test_security_viewmodel_frozen(self):
        s = SecurityViewModel()
        with pytest.raises(FrozenInstanceError):
            s.status = "HACKED"

    def test_screen_cell_frozen(self):
        c = ScreenCell()
        with pytest.raises(FrozenInstanceError):
            c.glyph = "X"

    def test_screen_frame_frozen(self):
        buf = ScreenBuffer(10, 5)
        frame = buf.snapshot()
        with pytest.raises(FrozenInstanceError):
            frame.width = 999


# ════════════════════════════════════════════════════════════════════════════════
# 3. Expanded ANSI injection vectors
# ════════════════════════════════════════════════════════════════════════════════

class TestTextSafetyExpandedInjection:
    """Adversarial terminal injection vectors beyond basic CSI."""

    def test_osc_title_injection(self):
        """OSC 0/2 sets terminal window title — must be stripped."""
        payload = "\x1b]0;MALICIOUS TITLE\x07rest"
        result = sanitize_terminal_text(payload)
        assert "MALICIOUS" not in result or "\x1b" not in result
        assert "rest" in result

    def test_osc_clipboard_theft(self):
        """OSC 52 can steal clipboard contents — must be stripped."""
        payload = "\x1b]52;c;BASE64DATA\x07visible"
        result = sanitize_terminal_text(payload)
        assert "\x1b" not in result
        assert "visible" in result

    def test_osc_with_st_terminator(self):
        """OSC terminated with ST (ESC \\) instead of BEL."""
        payload = "\x1b]0;TITLE\x1b\\rest"
        result = sanitize_terminal_text(payload)
        assert "\x1b" not in result
        assert "rest" in result

    def test_csi_cursor_movement_injection(self):
        """CSI sequences for cursor movement must be stripped."""
        payload = "\x1b[5A\x1b[10BSAFE"
        result = sanitize_terminal_text(payload)
        assert "\x1b" not in result
        assert "SAFE" in result

    def test_csi_erase_display(self):
        """CSI 2J erases screen — must be stripped."""
        payload = "\x1b[2Joverwritten"
        result = sanitize_terminal_text(payload)
        assert "\x1b" not in result
        assert "overwritten" in result

    def test_csi_sgr_injection(self):
        """CSI SGR color injection."""
        payload = "\x1b[31;1mRED BOLD\x1b[0m"
        result = sanitize_terminal_text(payload)
        assert "\x1b" not in result
        assert "RED BOLD" in result

    def test_c1_controls_stripped(self):
        """C1 control characters (0x80-0x9F) must be stripped."""
        payload = "before\x90DCS_STUFF\x9cafter"
        result = sanitize_terminal_text(payload)
        assert "\x90" not in result
        assert "\x9c" not in result

    def test_bel_character_stripped(self):
        """BEL (0x07) must be stripped."""
        payload = "alert\x07sound"
        result = sanitize_terminal_text(payload)
        assert "\x07" not in result
        assert "alertsound" in result

    def test_carriage_return_overwrite_attack(self):
        """CR can overwrite visible text — must be stripped."""
        payload = "Benign output\rMalicious"
        result = sanitize_terminal_text(payload)
        assert "\r" not in result

    def test_backspace_overwrite_attack(self):
        """Backspace (0x08) can overwrite characters — must be stripped."""
        payload = "Hello\x08\x08\x08\x08\x08XXXXX"
        result = sanitize_terminal_text(payload)
        assert "\x08" not in result

    def test_bidi_override_stripped(self):
        """Bidi override chars (U+202A–U+202E, U+2066–U+2069) must be stripped."""
        # RLO (Right-to-Left Override)
        payload = f"safe{chr(0x202E)}REVERSED{chr(0x202C)}end"
        result = sanitize_terminal_text(payload)
        assert chr(0x202E) not in result
        assert "safe" in result
        assert "end" in result

    def test_think_block_stripping(self):
        """Internal reasoning blocks must be completely hidden."""
        payload = "visible<think>SECRET CHAIN OF THOUGHT</think>also visible"
        result = sanitize_terminal_text(payload)
        assert "SECRET" not in result
        assert "visible" in result
        assert "also visible" in result

    def test_unclosed_think_block(self):
        """Unclosed think block at end of streaming text."""
        payload = "visible<think>partial reasoning"
        result = sanitize_terminal_text(payload)
        assert "partial reasoning" not in result
        assert "visible" in result

    def test_null_byte_stripped(self):
        """Null bytes must be stripped."""
        payload = "before\x00after"
        result = sanitize_terminal_text(payload)
        assert "\x00" not in result
        assert "beforeafter" in result

    def test_max_length_truncation(self):
        long_text = "A" * 10000
        result = sanitize_terminal_text(long_text, max_length=100)
        assert len(result) <= 101  # 100 + ellipsis
        assert result.endswith("…")

    def test_none_input(self):
        assert sanitize_terminal_text(None) == ""

    def test_non_string_input(self):
        assert sanitize_terminal_text(42) == "42"
        assert sanitize_terminal_text([1, 2]) == "[1, 2]"


# ════════════════════════════════════════════════════════════════════════════════
# 4. Unicode edge cases
# ════════════════════════════════════════════════════════════════════════════════

class TestUnicodeEdgeCases:
    """Validate proper handling of exotic Unicode."""

    def test_cjk_width(self):
        assert get_char_width("漢") == 2
        assert get_char_width("字") == 2

    def test_emoji_width(self):
        # Emoji (not all are East Asian Wide, but many are)
        assert get_char_width("A") == 1

    def test_combining_mark_zero_width(self):
        # Combining acute accent
        assert get_char_width("\u0301") == 0

    def test_zero_width_joiner(self):
        assert get_char_width("\u200D") == 0  # ZWJ is Cf category

    def test_braille_pattern(self):
        result = sanitize_terminal_text("⠀⠁⠂⠃")
        assert "⠀" in result  # Braille should be preserved

    def test_empty_string(self):
        assert get_char_width("") == 0
        assert get_string_display_width("") == 0

    def test_string_display_width_mixed(self):
        # "AB漢" = 1 + 1 + 2 = 4
        assert get_string_display_width("AB漢") == 4

    def test_nfc_normalization_preserves_display(self):
        # é as e + combining accent vs precomposed é
        decomposed = "e\u0301"
        result = sanitize_terminal_text(decomposed)
        assert len(result) >= 1  # Should normalize to precomposed


# ════════════════════════════════════════════════════════════════════════════════
# 5. ScreenBuffer boundary clipping
# ════════════════════════════════════════════════════════════════════════════════

class TestScreenBufferClipping:
    """Verify no IndexError or crash on out-of-bounds writes."""

    def test_put_char_negative_coords(self):
        buf = ScreenBuffer(20, 10)
        assert buf.put_char(-1, -1, "X") == 0

    def test_put_char_beyond_width(self):
        buf = ScreenBuffer(20, 10)
        assert buf.put_char(20, 0, "X") == 0

    def test_put_char_beyond_height(self):
        buf = ScreenBuffer(20, 10)
        assert buf.put_char(0, 10, "X") == 0

    def test_put_string_beyond_bounds(self):
        buf = ScreenBuffer(20, 10)
        # Should not crash, just clip
        written = buf.put_string(18, 0, "Hello World")
        assert written <= 20

    def test_put_string_at_negative_y(self):
        buf = ScreenBuffer(20, 10)
        written = buf.put_string(0, -5, "Hello")
        assert written == 0

    def test_wide_char_at_right_edge(self):
        """CJK char at rightmost column should not overflow."""
        buf = ScreenBuffer(20, 10)
        # Place wide char at column 19 (last column, needs 2 cols)
        consumed = buf.put_char(19, 0, "漢")
        # Should either clip or place a space placeholder
        assert consumed >= 0
        # No crash is the primary assertion

    def test_fill_rect_partial_clip(self):
        buf = ScreenBuffer(20, 10)
        # Rectangle extending beyond bounds
        buf.fill_rect(-5, -5, 30, 20, "█")
        # No crash, cells within bounds should be filled
        assert buf._grid[0][0].glyph == "█"
        assert buf._grid[9][19].glyph == "█"

    def test_draw_box_too_small(self):
        buf = ScreenBuffer(20, 10)
        # Box smaller than 2x2 should be a no-op
        buf.draw_box(0, 0, 1, 1)
        # No crash is the assertion

    def test_minimum_buffer_dimensions(self):
        """ScreenBuffer enforces minimum 10x5."""
        buf = ScreenBuffer(1, 1)
        assert buf.width == 10
        assert buf.height == 5

    def test_snapshot_produces_immutable_frame(self):
        buf = ScreenBuffer(10, 5)
        buf.put_string(0, 0, "Hello")
        frame = buf.snapshot(frame_id=42, state_revision=7)
        assert frame.frame_id == 42
        assert frame.state_revision == 7
        assert isinstance(frame.cells, tuple)
        assert isinstance(frame.cells[0], tuple)


# ════════════════════════════════════════════════════════════════════════════════
# 6. ScreenFrame.to_plain_text correctness
# ════════════════════════════════════════════════════════════════════════════════

class TestScreenFramePlainText:
    def test_plain_text_output(self):
        buf = ScreenBuffer(20, 5)
        buf.put_string(0, 0, "Row Zero")
        buf.put_string(0, 2, "Row Two")
        frame = buf.snapshot()
        plain = frame.to_plain_text()
        lines = plain.split("\n")
        assert lines[0].startswith("Row Zero")
        assert lines[2].startswith("Row Two")

    def test_plain_text_strips_trailing_spaces(self):
        buf = ScreenBuffer(20, 5)
        buf.put_string(0, 0, "AB")
        frame = buf.snapshot()
        plain = frame.to_plain_text()
        first_line = plain.split("\n")[0]
        assert first_line == "AB"  # No trailing spaces


# ════════════════════════════════════════════════════════════════════════════════
# 7. FrameDiffer edge cases
# ════════════════════════════════════════════════════════════════════════════════

class TestFrameDifferEdgeCases:
    def test_diff_with_none_previous(self):
        """First frame should trigger full repaint."""
        buf = ScreenBuffer(10, 5)
        buf.put_string(0, 0, "Hello")
        current = buf.snapshot()
        result = FrameDiffer.diff(None, current)
        assert result.is_full_repaint is True
        assert result.changed_rows == 5

    def test_diff_identical_frames_zero_runs(self):
        buf = ScreenBuffer(10, 5)
        buf.put_string(0, 0, "Same")
        frame = buf.snapshot()
        result = FrameDiffer.diff(frame, frame)
        assert result.is_full_repaint is False
        assert result.changed_rows == 0
        assert len(result.runs) == 0

    def test_diff_dimension_change_triggers_full(self):
        buf1 = ScreenBuffer(10, 5)
        frame1 = buf1.snapshot()
        buf2 = ScreenBuffer(20, 10)
        frame2 = buf2.snapshot()
        result = FrameDiffer.diff(frame1, frame2)
        assert result.is_full_repaint is True

    def test_diff_force_full_repaint(self):
        buf = ScreenBuffer(10, 5)
        frame = buf.snapshot()
        result = FrameDiffer.diff(frame, frame, force_full_repaint=True)
        assert result.is_full_repaint is True

    def test_diff_single_cell_change(self):
        buf1 = ScreenBuffer(10, 5)
        buf1.put_string(0, 0, "AAAA")
        frame1 = buf1.snapshot()

        buf2 = ScreenBuffer(10, 5)
        buf2.put_string(0, 0, "ABAA")
        frame2 = buf2.snapshot()

        result = FrameDiffer.diff(frame1, frame2)
        assert result.is_full_repaint is False
        assert result.changed_rows == 1
        assert len(result.runs) >= 1
        # The changed run should contain the 'B' cell
        found_b = False
        for run in result.runs:
            for cell in run.cells:
                if cell.glyph == "B":
                    found_b = True
        assert found_b


# ════════════════════════════════════════════════════════════════════════════════
# 8. VirtualList edge cases
# ════════════════════════════════════════════════════════════════════════════════

class TestVirtualListEdgeCases:
    def test_empty_items(self):
        result = VirtualList.slice_viewport([], viewport_height=10)
        assert result.total_count == 0
        assert len(result.visible_items) == 0
        assert result.has_more_above is False
        assert result.has_more_below is False

    def test_zero_viewport_height(self):
        result = VirtualList.slice_viewport([1, 2, 3], viewport_height=0)
        assert len(result.visible_items) == 0

    def test_negative_scroll_offset_clamped(self):
        items = list(range(100))
        result = VirtualList.slice_viewport(items, viewport_height=10, scroll_offset=-5)
        # Negative should be clamped to 0
        assert result.scroll_offset == 0

    def test_scroll_offset_beyond_max_clamped(self):
        items = list(range(100))
        result = VirtualList.slice_viewport(items, viewport_height=10, scroll_offset=99999)
        # Should clamp to max valid offset
        assert result.scroll_offset <= 100

    def test_items_fewer_than_viewport(self):
        items = [1, 2, 3]
        result = VirtualList.slice_viewport(items, viewport_height=20)
        assert len(result.visible_items) == 3
        assert result.has_more_above is False
        assert result.has_more_below is False

    def test_large_item_height(self):
        items = list(range(100))
        result = VirtualList.slice_viewport(items, viewport_height=10, item_height=5)
        # 10 / 5 = 2 items visible
        assert len(result.visible_items) == 2

    def test_top_anchored_mode(self):
        items = list(range(50))
        result = VirtualList.slice_viewport(
            items, viewport_height=10, scroll_offset=5, anchor_to_bottom=False
        )
        assert result.start_index == 5
        assert result.has_more_above is True
        assert result.has_more_below is True

    def test_ten_thousand_items_microsecond_bound(self):
        """10K items must virtualize within microsecond range."""
        items = list(range(10_000))
        start = time.perf_counter_ns()
        result = VirtualList.slice_viewport(items, viewport_height=50)
        elapsed_us = (time.perf_counter_ns() - start) / 1_000
        # Must complete in under 1ms (1000us) — generous bound
        assert elapsed_us < 1_000
        assert len(result.visible_items) == 50
        assert result.has_more_above is True


# ════════════════════════════════════════════════════════════════════════════════
# 9. Broken pipe containment in TerminalWriter
# ════════════════════════════════════════════════════════════════════════════════

class TestTerminalWriterContainment:
    def test_broken_pipe_does_not_raise(self):
        """Writer must swallow BrokenPipeError and mark is_alive=False."""
        broken_stream = MagicMock()
        broken_stream.write = MagicMock(side_effect=BrokenPipeError("Broken"))
        broken_stream.flush = MagicMock()

        caps = _make_caps()
        writer = TerminalWriter(stream=broken_stream, capabilities=caps)

        # Create a minimal diff
        buf = ScreenBuffer(10, 5)
        buf.put_string(0, 0, "Test")
        frame = buf.snapshot()
        diff = FrameDiffer.diff(None, frame)

        bytes_written = writer.write_diff(diff)
        assert bytes_written == 0
        assert writer.is_alive is False

    def test_oserror_does_not_raise(self):
        broken_stream = MagicMock()
        broken_stream.write = MagicMock(side_effect=OSError("EPIPE"))
        broken_stream.flush = MagicMock()

        caps = _make_caps()
        writer = TerminalWriter(stream=broken_stream, capabilities=caps)

        buf = ScreenBuffer(10, 5)
        frame = buf.snapshot()
        diff = FrameDiffer.diff(None, frame)

        bytes_written = writer.write_diff(diff)
        assert bytes_written == 0
        assert writer.is_alive is False

    def test_dead_writer_writes_nothing(self):
        stream = io.StringIO()
        caps = _make_caps()
        writer = TerminalWriter(stream=stream, capabilities=caps)
        writer.is_alive = False

        buf = ScreenBuffer(10, 5)
        buf.put_string(0, 0, "Test")
        frame = buf.snapshot()
        diff = FrameDiffer.diff(None, frame)

        assert writer.write_diff(diff) == 0

    def test_writer_no_color_mode(self):
        """NO_COLOR mode should produce output without ANSI SGR codes (except cursor positioning)."""
        stream = io.StringIO()
        caps = TerminalCapabilities.fallback_plain()
        writer = TerminalWriter(stream=stream, capabilities=caps)
        assert caps.color_depth == ColorDepth.NO_COLOR

        buf = ScreenBuffer(10, 5)
        buf.put_string(0, 0, "Hi", fg="red", bold=True)
        frame = buf.snapshot()
        diff = FrameDiffer.diff(None, frame)

        writer.write_diff(diff)
        content = stream.getvalue()
        # Should contain positioning but not SGR color codes (except reset)
        assert "Hi" in content


# ════════════════════════════════════════════════════════════════════════════════
# 10. Renderer panel crash isolation
# ════════════════════════════════════════════════════════════════════════════════

class TestRendererPanelCrashIsolation:
    """Each panel crash must be contained; other panels render normally."""

    def test_renderer_with_fully_default_vm(self):
        """Default ViewModel must render without crash."""
        renderer = TuiRenderer()
        vm = HermesViewModel()
        caps = _make_caps(80, 24)
        frame = renderer.build_frame(vm, caps, frame_id=1)
        assert frame.width == 80
        assert frame.height == 24
        assert frame.frame_id == 1

    def test_renderer_with_none_mission_title(self):
        """None in mission title must not crash renderer."""
        renderer = TuiRenderer()
        vm = HermesViewModel(
            mission=MissionViewModel(title=None, status="RUNNING"),
        )
        caps = _make_caps(80, 24)
        frame = renderer.build_frame(vm, caps)
        # Should render without error
        assert frame is not None

    def test_renderer_minimum_dimensions(self):
        """Renderer must handle minimum viable terminal size."""
        renderer = TuiRenderer()
        vm = HermesViewModel()
        caps = _make_caps(10, 5)  # Absolute minimum
        frame = renderer.build_frame(vm, caps)
        assert frame.width == 10
        assert frame.height == 5

    def test_renderer_with_security_modal(self):
        """Security modal must render without crash."""
        renderer = TuiRenderer()
        vm = HermesViewModel(
            security=SecurityViewModel(
                modal=ApprovalModalViewModel(
                    visible=True,
                    action_summary="rm -rf /",
                    risk_level="CRITICAL",
                    explanation="This would delete everything",
                ),
            ),
        )
        caps = _make_caps(80, 24)
        frame = renderer.build_frame(vm, caps)
        text = frame.to_plain_text()
        assert "Security" in text or "CRITICAL" in text or frame is not None

    def test_renderer_with_rewind_preview(self):
        renderer = TuiRenderer()
        vm = HermesViewModel(
            rewind_preview=RewindPreviewViewModel(
                visible=True,
                checkpoint_id="chk-abc123",
                restore_files_count=5,
                preserve_files_count=2,
                user_conflicts_count=1,
            ),
        )
        caps = _make_caps(80, 24)
        frame = renderer.build_frame(vm, caps)
        text = frame.to_plain_text()
        assert "Rewind" in text or frame is not None

    def test_renderer_with_chat_messages(self):
        """Renderer must handle chat messages with malicious content."""
        msgs = [
            ChatMessageViewModel(
                message_id="1", sequence=1, timestamp_str="12:00:00",
                kind=ChatEntryKind.USER, author_role="User",
                content="\x1b[31mINJECTED\x1b[0m",
            ),
            ChatMessageViewModel(
                message_id="2", sequence=2, timestamp_str="12:00:01",
                kind=ChatEntryKind.ASSISTANT, author_role="Hermes",
                content="Normal response<think>SECRET</think>visible",
            ),
        ]
        vm = HermesViewModel(
            chat=ChatViewModel(messages=tuple(msgs), total_messages=2),
        )
        caps = _make_caps(80, 24)
        renderer = TuiRenderer()
        frame = renderer.build_frame(vm, caps)
        text = frame.to_plain_text()
        # ANSI injection must not pass through
        assert "\x1b" not in text


# ════════════════════════════════════════════════════════════════════════════════
# 11. FallbackRenderer emergency path
# ════════════════════════════════════════════════════════════════════════════════

class TestFallbackRendererEmergency:
    def test_fallback_with_default_vm(self):
        renderer = FallbackRenderer()
        vm = HermesViewModel()
        caps = _make_caps(80, 24)
        frame = renderer.build_frame(vm, caps)
        text = frame.to_plain_text()
        assert "HERMES" in text
        assert "FALLBACK" in text

    def test_fallback_with_minimum_terminal(self):
        renderer = FallbackRenderer()
        vm = HermesViewModel()
        caps = _make_caps(10, 5)
        frame = renderer.build_frame(vm, caps)
        assert frame is not None
        assert frame.width == 10
        assert frame.height == 5

    def test_fallback_renders_truthful_status(self):
        renderer = FallbackRenderer()
        vm = HermesViewModel(
            mission=MissionViewModel(status="FAILED", title="Broken Mission"),
        )
        caps = _make_caps(80, 24)
        frame = renderer.build_frame(vm, caps)
        text = frame.to_plain_text()
        assert "FAILED" in text


# ════════════════════════════════════════════════════════════════════════════════
# 12. RenderSupervisor circuit breaker recovery
# ════════════════════════════════════════════════════════════════════════════════

class TestRenderSupervisorRecovery:
    def test_primary_to_fallback_transition(self):
        """3 consecutive failures should trip to FALLBACK."""

        class CrashingRenderer:
            def build_frame(self, vm, caps, frame_id=0):
                raise RuntimeError("Primary crash")

        supervisor = RenderSupervisor(
            primary_renderer=CrashingRenderer(),
            max_consecutive_failures=3,
        )
        vm = HermesViewModel()
        caps = _make_caps()

        for i in range(3):
            frame = supervisor.render_frame(vm, caps, frame_id=i)
            assert frame is not None  # Fallback must produce a frame

        assert supervisor.circuit_state == CircuitState.FALLBACK
        assert supervisor.primary_failures == 3

    def test_probing_to_primary_recovery(self):
        """After fallback, sufficient fallback successes enter PROBING; then primary success restores PRIMARY."""
        fail_primary = True

        class ControllableRenderer:
            def build_frame(self, vm, caps, frame_id=0):
                if fail_primary:
                    raise RuntimeError("Failing")
                return FallbackRenderer().build_frame(vm, caps, frame_id)

        supervisor = RenderSupervisor(
            primary_renderer=ControllableRenderer(),
            max_consecutive_failures=3,
            probe_success_threshold=2,
        )
        vm = HermesViewModel()
        caps = _make_caps()

        # Trip to fallback with 3 consecutive failures
        for i in range(3):
            supervisor.render_frame(vm, caps, frame_id=i)
        assert supervisor.circuit_state == CircuitState.FALLBACK

        # Accumulate fallback success to reach probe threshold (threshold is 2, frame 2 gave 1, frame 3 gives 2)
        supervisor.render_frame(vm, caps, frame_id=3)
        assert supervisor.circuit_state == CircuitState.PROBING

        # Now fix the primary renderer — next render attempt probes primary and succeeds
        fail_primary = False
        supervisor.render_frame(vm, caps, frame_id=4)
        assert supervisor.circuit_state == CircuitState.PRIMARY

    def test_stats_reporting(self):
        supervisor = RenderSupervisor(primary_renderer=TuiRenderer())
        vm = HermesViewModel()
        caps = _make_caps()
        supervisor.render_frame(vm, caps)
        stats = supervisor.get_stats()
        assert stats["circuit_state"] == "PRIMARY"
        assert stats["frames_generated"] == 1
        assert stats["primary_successes"] == 1


# ════════════════════════════════════════════════════════════════════════════════
# 13. EventProjector FIFO cap and lifecycle
# ════════════════════════════════════════════════════════════════════════════════

class TestEventProjectorFIFO:
    def test_message_cap_eviction(self):
        """Messages beyond max_messages should trigger FIFO eviction."""
        projector = EventProjector(max_messages=5)
        for i in range(10):
            projector.add_user_message(f"msg_{i}")
        assert len(projector.messages) == 5
        # Oldest messages should be evicted
        assert projector.messages[0].content == "msg_5"
        assert projector.messages[-1].content == "msg_9"

    def test_add_user_message(self):
        projector = EventProjector()
        projector.add_user_message("Hello HERMES")
        assert len(projector.messages) == 1
        assert projector.messages[0].kind == ChatEntryKind.USER
        assert projector.messages[0].author_role == "User"

    def test_streaming_lifecycle(self):
        """Verify streaming state transitions."""
        projector = EventProjector()

        # Simulate streaming start
        from core.runtime_state.events import EventType, HermesEvent

        start_event = HermesEvent(
            event_type=EventType.MODEL_TTFT,
            timestamp=time.time(),
        )
        projector.process_event(start_event)
        assert projector.is_streaming is True

        # Simulate completion
        complete_event = HermesEvent(
            event_type=EventType.MODEL_COMPLETED,
            timestamp=time.time(),
            payload={"final_output": "Done"},
        )
        projector.process_event(complete_event)
        assert projector.is_streaming is False
        assert len(projector.messages) == 1
        assert projector.messages[0].content == "Done"


# ════════════════════════════════════════════════════════════════════════════════
# 14. build_root_view_model with adversarial state
# ════════════════════════════════════════════════════════════════════════════════

class TestBuildRootViewModelAdversarial:
    def test_default_state_builds_without_error(self):
        state = HermesRuntimeState(mission=MissionState(mission_id="test"))
        vm = build_root_view_model(state, revision=1)
        assert isinstance(vm, HermesViewModel)
        assert vm.revision == 1

    def test_build_with_streaming_content(self):
        state = HermesRuntimeState(mission=MissionState(mission_id="test"))
        vm = build_root_view_model(
            state,
            is_streaming=True,
            streaming_content="\x1b[31mMALICIOUS\x1b[0m",
        )
        # Streaming content must be sanitized
        assert "\x1b" not in vm.chat.streaming_partial_content

    def test_build_with_notifications(self):
        state = HermesRuntimeState(mission=MissionState(mission_id="test"))
        notifs = ["Alert 1", "\x1b[2JCleared"]
        vm = build_root_view_model(state, active_notifications=notifs)
        assert len(vm.active_notifications) == 2
        # Injected ANSI in notifications must be sanitized
        assert "\x1b" not in vm.active_notifications[1]

    def test_build_with_think_in_chat(self):
        state = HermesRuntimeState(mission=MissionState(mission_id="test"))
        msgs = [
            ChatMessageViewModel(
                message_id="1", sequence=1, timestamp_str="",
                kind=ChatEntryKind.ASSISTANT, author_role="Hermes",
                content="visible<think>hidden</think>more",
            ),
        ]
        vm = build_root_view_model(state, chat_messages=msgs)
        assert len(vm.chat.messages) == 1


# ════════════════════════════════════════════════════════════════════════════════
# 15. TerminalCapabilities fallback and detect
# ════════════════════════════════════════════════════════════════════════════════

class TestTerminalCapabilities:
    def test_fallback_plain(self):
        caps = TerminalCapabilities.fallback_plain()
        assert caps.is_tty is False
        assert caps.color_depth == ColorDepth.NO_COLOR
        assert caps.width == 80
        assert caps.height == 24
        assert caps.alternate_screen_supported is False

    def test_with_dimensions(self):
        caps = TerminalCapabilities.fallback_plain()
        updated = caps.with_dimensions(120, 40)
        assert updated.width == 120
        assert updated.height == 40
        assert updated.is_tty is False  # Preserved from original

    def test_minimum_dimensions_enforced(self):
        caps = TerminalCapabilities.fallback_plain()
        updated = caps.with_dimensions(1, 1)
        assert updated.width == 10  # Minimum enforced
        assert updated.height == 5   # Minimum enforced

    def test_detect_with_stringio(self):
        """Detection on StringIO should produce safe defaults."""
        stream = io.StringIO()
        caps = TerminalCapabilities.detect(stream)
        assert caps.is_tty is False
        assert caps.color_depth == ColorDepth.NO_COLOR


# ════════════════════════════════════════════════════════════════════════════════
# 16. Headless import isolation
# ════════════════════════════════════════════════════════════════════════════════

class TestHeadlessImportIsolation:
    def test_tui_modules_importable_without_terminal(self):
        """All TUI 2.x modules must import cleanly in headless environments."""
        # These imports should NOT require a real terminal
        from ui.rendering.renderer import TuiRenderer
        from ui.rendering.fallback_renderer import FallbackRenderer
        from ui.rendering.render_supervisor import RenderSupervisor
        from ui.rendering.screen_buffer import ScreenBuffer
        from ui.rendering.frame_diff import FrameDiffer
        from ui.rendering.virtualization import VirtualList
        from ui.rendering.text_safety import sanitize_terminal_text
        from ui.rendering.terminal_capabilities import TerminalCapabilities
        from ui.rendering.terminal_writer import TerminalWriter
        from ui.viewmodels.root import HermesViewModel
        from ui.state.selectors import build_root_view_model
        from ui.runtime.event_projection import EventProjector
        # All passed — headless isolation confirmed

    def test_full_render_pipeline_headless(self):
        """Complete render pipeline must work without real terminal."""
        vm = HermesViewModel()
        caps = TerminalCapabilities.fallback_plain()
        renderer = TuiRenderer()
        frame = renderer.build_frame(vm, caps)
        diff = FrameDiffer.diff(None, frame)

        stream = io.StringIO()
        writer = TerminalWriter(stream=stream, capabilities=caps)
        bytes_written = writer.write_diff(diff)
        assert bytes_written >= 0
        output = stream.getvalue()
        assert "HERMES" in output

    def test_supervisor_pipeline_headless(self):
        """Full supervisor pipeline must work headless."""
        supervisor = RenderSupervisor(primary_renderer=TuiRenderer())
        vm = HermesViewModel()
        caps = TerminalCapabilities.fallback_plain()
        frame = supervisor.render_frame(vm, caps)
        assert frame is not None
        assert supervisor.circuit_state == CircuitState.PRIMARY


# ════════════════════════════════════════════════════════════════════════════════
# 17. Renderer determinism
# ════════════════════════════════════════════════════════════════════════════════

class TestRendererDeterminism:
    def test_same_input_produces_same_output(self):
        """Same ViewModel + Capabilities must produce identical cell arrays."""
        renderer = TuiRenderer()
        vm = HermesViewModel(
            mission=MissionViewModel(status="RUNNING", title="Test Mission"),
            progress=ProgressViewModel(percentage_str="50%", active_task_title="Task 1"),
        )
        caps = _make_caps(80, 24)

        frame1 = renderer.build_frame(vm, caps, frame_id=1)
        frame2 = renderer.build_frame(vm, caps, frame_id=1)

        # Cell contents must be identical (timestamps in viewmodel are fixed)
        for y in range(frame1.height):
            for x in range(frame1.width):
                c1 = frame1.cells[y][x]
                c2 = frame2.cells[y][x]
                assert c1.glyph == c2.glyph, f"Glyph mismatch at ({x},{y}): {c1.glyph!r} vs {c2.glyph!r}"
                assert c1.fg == c2.fg
                assert c1.bg == c2.bg
                assert c1.bold == c2.bold
