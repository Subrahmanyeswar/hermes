# tests/test_tui_chaos.py
"""Chaos and stress testing for TUI 2.x renderer and scheduler."""

import io
import pytest
from ui.rendering.fallback_renderer import FallbackRenderer
from ui.rendering.render_scheduler import RenderScheduler
from ui.rendering.render_supervisor import RenderSupervisor
from ui.rendering.renderer import TuiRenderer
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.rendering.terminal_writer import TerminalWriter
from ui.viewmodels.chat import ChatEntryKind, ChatMessageViewModel
from ui.viewmodels.mission import MissionViewModel
from ui.viewmodels.root import HermesViewModel


def test_event_burst_coalescing():
    """Verify that 1,000 rapid state changes coalesce into a bounded number of renders."""
    output_stream = io.StringIO()
    caps = TerminalCapabilities.fallback_plain(80, 24)
    writer = TerminalWriter(stream=output_stream, capabilities=caps)
    supervisor = RenderSupervisor(primary_renderer=TuiRenderer(), fallback_renderer=FallbackRenderer())
    scheduler = RenderScheduler(supervisor=supervisor, writer=writer, target_fps=30.0)

    # Fire 1,000 rapid non-urgent view-model updates
    for i in range(1000):
        vm = HermesViewModel(
            revision=i + 1,
            mission=MissionViewModel(title=f"Burst Step {i}", status="RUNNING"),
        )
        scheduler.request_render(vm, urgent=False)

    scheduler.flush_pending()

    # Renders must be heavily coalesced (far fewer than 1,000 frames)
    assert scheduler.frames_rendered < 50
    assert scheduler.coalesced_count > 900
    assert scheduler.frames_skipped == 0


def test_resize_storm_stability():
    """Rapidly resize terminal dimensions across extreme values."""
    renderer = TuiRenderer()
    vm = HermesViewModel(
        mission=MissionViewModel(title="Resize Storm", status="RUNNING"),
    )

    dimensions = [
        (120, 40), (80, 24), (100, 30), (60, 20),
        (40, 12), (20, 5), (10, 5), (150, 50), (80, 24)
    ]

    for w, h in dimensions:
        caps = TerminalCapabilities.fallback_plain(w, h)
        frame = renderer.build_frame(vm, caps)
        assert frame.width == max(10, w)
        assert frame.height == max(5, h)
        assert len(frame.cells) == max(5, h)


def test_stale_frame_rejection():
    """Frames delivered with older revision numbers are safely discarded."""
    output_stream = io.StringIO()
    caps = TerminalCapabilities.fallback_plain(80, 24)
    writer = TerminalWriter(stream=output_stream, capabilities=caps)
    supervisor = RenderSupervisor(primary_renderer=TuiRenderer())
    scheduler = RenderScheduler(supervisor=supervisor, writer=writer)

    vm_new = HermesViewModel(revision=100, mission=MissionViewModel(title="New State"))
    vm_old = HermesViewModel(revision=50, mission=MissionViewModel(title="Old Stale State"))

    # Render revision 100
    scheduler.request_render(vm_new, urgent=True)

    # Attempt to render older revision 50
    accepted = scheduler.request_render(vm_old, urgent=True)
    assert accepted is False
    assert scheduler.frames_skipped == 1


def test_malicious_text_full_frame_rendering():
    """Full frame renders without executing or leaking malicious sequences."""
    renderer = TuiRenderer()
    caps = TerminalCapabilities.fallback_plain(80, 24)

    evil_msg = ChatMessageViewModel(
        message_id="m_evil",
        sequence=1,
        timestamp_str="12:00:00",
        kind=ChatEntryKind.USER,
        author_role="User",
        content="Injected \033[2J\033[H\033]0;Hacked\007<think>Secret reasoning</think>Normal text\rOverwriting text",
    )

    vm = HermesViewModel(
        chat=ChatMessageViewModel(
            message_id="1", sequence=1, timestamp_str="12:00",
            kind=ChatEntryKind.USER, author_role="User", content=evil_msg.content
        ),
    )

    frame = renderer.build_frame(vm, caps)
    plain = frame.to_plain_text()

    assert "\033" not in plain
    assert "<think>" not in plain
    assert "Secret reasoning" not in plain
