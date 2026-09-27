# tests/test_tui_renderer.py
"""Tests for TuiRenderer layout, determinism, and panel error containment."""

import pytest
from ui.rendering.layout import LayoutEngine
from ui.rendering.renderer import TuiRenderer
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.viewmodels.chat import ChatEntryKind, ChatMessageViewModel
from ui.viewmodels.mission import MissionViewModel
from ui.viewmodels.root import HermesViewModel
from ui.viewmodels.security import ApprovalModalViewModel, SecurityViewModel


def test_tui_renderer_determinism():
    renderer = TuiRenderer()
    caps = TerminalCapabilities.fallback_plain(100, 30)

    vm = HermesViewModel(
        mission=MissionViewModel(title="Deterministic Check", status="RUNNING"),
        chat=ChatMessageViewModel(
            message_id="1", sequence=1, timestamp_str="12:00:00",
            kind=ChatEntryKind.USER, author_role="User", content="Hello"
        ),
    )

    frame1 = renderer.build_frame(vm, caps, frame_id=1)
    frame2 = renderer.build_frame(vm, caps, frame_id=2)

    # Frame cells must be 100% identical
    assert frame1.cells == frame2.cells
    assert frame1.to_plain_text() == frame2.to_plain_text()


def test_tui_renderer_small_dimensions_degradation():
    renderer = TuiRenderer()
    vm = HermesViewModel(
        mission=MissionViewModel(title="Tiny Screen Mission", status="RUNNING"),
    )

    # Small screen: 40x12
    caps_small = TerminalCapabilities.fallback_plain(40, 12)
    frame_small = renderer.build_frame(vm, caps_small)
    assert frame_small.width == 40
    assert frame_small.height == 12
    assert "HERMES" in frame_small.to_plain_text()

    # Extreme tiny screen: 20x5
    caps_tiny = TerminalCapabilities.fallback_plain(20, 5)
    frame_tiny = renderer.build_frame(vm, caps_tiny)
    assert frame_tiny.width == 20
    assert frame_tiny.height == 5
    assert len(frame_tiny.cells) == 5


def test_tui_renderer_security_modal():
    renderer = TuiRenderer()
    caps = TerminalCapabilities.fallback_plain(100, 30)

    modal_vm = ApprovalModalViewModel(
        visible=True,
        action_summary="Write critical config",
        risk_level="HIGH",
        explanation="Dangerous operation",
    )
    sec_vm = SecurityViewModel(modal=modal_vm)
    vm = HermesViewModel(security=sec_vm)

    frame = renderer.build_frame(vm, caps)
    plain = frame.to_plain_text()

    assert "Security Authorization Required" in plain
    assert "Write critical config" in plain
    assert "[y] Approve" in plain
