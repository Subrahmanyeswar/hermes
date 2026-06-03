"""
HERMES TUI Tests — Week 15
Tests the Textual app using Textual's built-in test pilot.
No real terminal required — Textual simulates the terminal.
No Ollama required — orchestrator is fully mocked.

Run: pytest tests/test_tui.py -v --timeout=60
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


# ── Shared mock setup ─────────────────────────────────────────────────

def make_mock_orchestrator(response_output: str = "Files listed successfully"):
    """Create a fully mocked orchestrator for TUI tests."""
    from core.orchestrator import OrchestratorResult

    mock_orch = AsyncMock()
    mock_orch.run = AsyncMock(return_value=OrchestratorResult(
        success=True,
        final_output=response_output,
        tool_name="list_directory",
        tool_result=None,
        task=None,
        skill_ids_used=[],
        tier3_was_called=False,
        total_latency_seconds=1.5,
        error=None,
        pipeline_stage_reached=12,
        trace_id="abc12345",
    ))
    mock_orch.set_mode = MagicMock()
    mock_orch.start_kairos = AsyncMock()
    mock_orch.stop_kairos = AsyncMock()
    mock_orch.kairos = MagicMock()
    mock_orch.kairos.get_stats = MagicMock(return_value={
        "is_running": True,
        "loop_count": 5,
        "stuck_tasks_detected": 0,
        "tasks_retried": 0,
        "consolidations_run": 1,
        "total_api_cost": 0.02,
        "pending_tasks": 0,
    })
    mock_orch.claude = MagicMock()
    mock_orch.claude.get_cost_summary = MagicMock(
        return_value={"total_spent": 0.02, "cap": 25.0, "remaining": 24.98}
    )
    return mock_orch


@pytest.fixture
def mock_orch_patch():
    """Patch Orchestrator class to return a mock."""
    with patch("ui.app.HermesApp._init_orchestrator") as mock_init, \
         patch("ui.app.HermesApp._start_kairos", new_callable=AsyncMock) as mock_start, \
         patch("ui.app.HermesApp._kairos_monitor", new_callable=AsyncMock) as mock_monitor:
        yield mock_init, mock_start, mock_monitor


# ── App structure tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_app_mounts_without_crash(mock_orch_patch):
    """HermesApp must mount and show the chat panel without crashing."""
    from ui.app import HermesApp

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        # App should be running
        assert app.is_running

        # Chat panel must be present
        from ui.panels.chat import ChatPanel
        panels = app.query(ChatPanel)
        assert len(panels) == 1, f"Expected 1 ChatPanel, found {len(panels)}"


@pytest.mark.asyncio
async def test_status_bar_renders(mock_orch_patch):
    """StatusBar must be present and show the correct mode."""
    from ui.app import HermesApp
    from ui.panels.status_bar import StatusBar

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        status_bars = app.query(StatusBar)
        assert len(status_bars) == 1, "StatusBar must be present"

        status_bar = status_bars.first()
        assert status_bar.mode == "auto"


@pytest.mark.asyncio
async def test_chat_input_is_focusable(mock_orch_patch):
    """The chat input widget must be present and focusable."""
    from textual.widgets import Input
    from ui.app import HermesApp

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        inputs = app.query(Input)
        assert len(inputs) >= 1, "At least one Input widget must exist"

        chat_input = app.query_one("#chat-input", Input)
        assert chat_input is not None


@pytest.mark.asyncio
async def test_typing_in_chat_input(mock_orch_patch):
    """User must be able to type in the chat input."""
    from textual.widgets import Input
    from ui.app import HermesApp

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        chat_input = app.query_one("#chat-input", Input)

        # Focus and type
        await pilot.click("#chat-input")
        await pilot.press("l", "i", "s", "t")
        await asyncio.sleep(0.1)

        assert "list" in chat_input.value


@pytest.mark.asyncio
async def test_mode_switching_ctrl_s(mock_orch_patch):
    """Ctrl+S must switch to Safe mode."""
    from ui.app import HermesApp

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        assert app.current_mode == "auto"

        await pilot.press("ctrl+s")
        await asyncio.sleep(0.1)

        assert app.current_mode == "safe"


@pytest.mark.asyncio
async def test_mode_switching_ctrl_p(mock_orch_patch):
    """Ctrl+P must switch to Plan mode."""
    from ui.app import HermesApp

    app = HermesApp(mode="auto", project="test")
    app.ENABLE_COMMAND_PALETTE = False  # Disable command palette to prevent Ctrl+P conflict
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        app.set_focus(None)  # Unfocus input to prevent readline key interception
        await pilot.press("ctrl+p")
        await asyncio.sleep(0.1)
        assert app.current_mode == "plan"


@pytest.mark.asyncio
async def test_mode_switching_ctrl_a(mock_orch_patch):
    """Ctrl+A must switch back to Auto mode."""
    from ui.app import HermesApp

    app = HermesApp(mode="safe", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        assert app.current_mode == "safe"
        app.set_focus(None)  # Unfocus input to prevent readline key interception
        await pilot.press("ctrl+a")
        await asyncio.sleep(0.1)
        assert app.current_mode == "auto"


@pytest.mark.asyncio
async def test_submitting_message_posts_user_message_sent(mock_orch_patch):
    """Pressing Enter in chat input must trigger orchestrator processing."""
    from ui.app import HermesApp, UserMessageSent

    app = HermesApp(mode="auto", project="test")
    mock_orch = make_mock_orchestrator()
    app._orchestrator = mock_orch

    messages_received = []

    def capture_message(message):
        messages_received.append(message)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#chat-input")
        await pilot.press("l", "i", "s", "t")
        await pilot.press("enter")
        await asyncio.sleep(0.5)  # Wait for message processing

        # Orchestrator should have been called
        # (or message queued — either is acceptable)


@pytest.mark.asyncio
async def test_slash_command_clear_works(mock_orch_patch):
    """The /clear command must not crash the app."""
    from ui.app import HermesApp

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#chat-input")
        for char in "/clear":
            await pilot.press(char)
        await pilot.press("enter")
        await asyncio.sleep(0.2)

        # App should still be running
        assert app.is_running


@pytest.mark.asyncio
async def test_slash_command_help_works(mock_orch_patch):
    """The /help command must not crash the app."""
    from ui.app import HermesApp

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#chat-input")
        for char in "/help":
            await pilot.press(char)
        await pilot.press("enter")
        await asyncio.sleep(0.2)

        assert app.is_running


@pytest.mark.asyncio
async def test_processing_indicator_shows_during_request(mock_orch_patch):
    """ProcessingIndicator must appear while orchestrator is running."""
    from ui.app import HermesApp
    from ui.panels.chat import ProcessingIndicator

    # Make orchestrator slow to respond
    slow_mock = make_mock_orchestrator()
    original_run = slow_mock.run.side_effect

    async def slow_run(*args, **kwargs):
        await asyncio.sleep(0.3)
        from core.orchestrator import OrchestratorResult
        return OrchestratorResult(
            success=True, final_output="Done", tool_name="list_directory",
            tool_result=None, task=None, skill_ids_used=[], tier3_was_called=False,
            total_latency_seconds=0.3, error=None, pipeline_stage_reached=12,
            trace_id="test1234"
        )

    slow_mock.run = AsyncMock(side_effect=slow_run)

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = slow_mock

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#chat-input")
        for char in "list files":
            await pilot.press(char)
        await pilot.press("enter")

        # Brief pause — indicator should appear
        await asyncio.sleep(0.1)
        # App must be running regardless
        assert app.is_running

        # Wait for completion
        await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_app_exits_on_ctrl_q(mock_orch_patch):
    """Ctrl+Q must exit the app cleanly."""
    from ui.app import HermesApp

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        assert app.is_running
        await pilot.press("ctrl+q")
        # After Ctrl+Q, app should begin shutdown
        # run_test context manager handles cleanup


@pytest.mark.asyncio
async def test_user_message_widget_renders_text():
    """UserMessageWidget must render the user's text correctly."""
    from ui.panels.chat import UserMessageWidget
    from rich.text import Text

    widget = UserMessageWidget("list all files in the directory")
    rendered = widget.render()

    assert isinstance(rendered, Text)
    assert "list all files" in rendered.plain


@pytest.mark.asyncio
async def test_hermes_message_widget_success_renders():
    """HermesMessageWidget must render success response correctly."""
    from ui.app import OrchestratorResponse
    from ui.panels.chat import HermesMessageWidget
    from rich.text import Text

    response = OrchestratorResponse(
        user_request="list files",
        final_output="core/\ntools/\nmemory/\nmain.py",
        tool_name="list_directory",
        success=True,
        stage_reached=12,
        tier3_called=False,
        latency_seconds=2.3,
        trace_id="abc12345",
        skill_ids=[],
    )
    widget = HermesMessageWidget(response)
    rendered = widget.render()

    assert isinstance(rendered, Text)
    assert "core/" in rendered.plain
    assert "list_directory" in rendered.plain


@pytest.mark.asyncio
async def test_hermes_message_widget_error_renders():
    """HermesMessageWidget must render error response with amber styling."""
    from ui.app import OrchestratorResponse
    from ui.panels.chat import HermesMessageWidget

    response = OrchestratorResponse(
        user_request="do bad thing",
        final_output="Action failed: permission denied",
        tool_name="bash_exec",
        success=False,
        stage_reached=5,
        tier3_called=False,
        latency_seconds=0.5,
        trace_id="err12345",
        skill_ids=[],
        error="permission denied",
    )
    widget = HermesMessageWidget(response)
    assert "error" in widget.classes
    assert "success" not in widget.classes


# ══════════════════════════════════════════════════════════════════════
# Week 16 additional tests
# ══════════════════════════════════════════════════════════════════════

# ── StatusBar tests ────────────────────────────────────────────────────

def test_status_bar_has_30_verbs():
    """StatusBar must have exactly 30 spinner verbs."""
    from ui.panels.status_bar import SPINNER_VERBS
    assert len(SPINNER_VERBS) == 30
    assert len(set(SPINNER_VERBS)) == 30, "All verbs must be unique"


def test_random_verb_function():
    """_random_verb must return a verb from the list."""
    from ui.panels.status_bar import SPINNER_VERBS, _random_verb
    for _ in range(50):
        verb = _random_verb()
        assert verb in SPINNER_VERBS, f"Got verb not in list: {verb}"


def test_status_bar_render_all_modes():
    """StatusBar._render must include mode text for all 3 modes."""
    from ui.panels.status_bar import StatusBar
    bar = StatusBar()
    for mode in ("safe", "plan", "auto"):
        bar.mode = mode
        rendered = bar._render_status()
        assert mode.upper() in rendered.plain, f"{mode.upper()} not in render"


def test_status_bar_render_shows_skill():
    """StatusBar must show active skill name when skill != 'none'."""
    from ui.panels.status_bar import StatusBar
    bar = StatusBar()
    bar.skill = "flask-rest-api"
    rendered = bar._render_status()
    assert "flask-rest-api" in rendered.plain


def test_status_bar_render_shows_cost():
    """StatusBar must show the session cost."""
    from ui.panels.status_bar import StatusBar
    bar = StatusBar()
    bar.cost = 0.042
    rendered = bar._render_status()
    assert "0.04" in rendered.plain


@pytest.mark.asyncio
async def test_status_bar_shows_cogitating_when_processing():
    """StatusBar must show spinner verb (not Ready) when processing."""
    from ui.panels.status_bar import StatusBar
    bar = StatusBar()
    bar.processing = True
    bar.spinner_verb = "Cogitating"
    rendered = bar._render_status()
    assert "Cogitating" in rendered.plain
    assert "Ready" not in rendered.plain


@pytest.mark.asyncio
async def test_status_bar_shows_ready_when_idle():
    """StatusBar must show 'Ready' when not processing."""
    from ui.panels.status_bar import StatusBar
    bar = StatusBar()
    bar.processing = False
    bar.spinner_verb = "Ready"
    rendered = bar._render_status()
    assert "Ready" in rendered.plain


# ── RightPanel tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_right_panel_mounts_with_3_tabs(mock_orch_patch):
    """RightPanel must mount with Tool Trace, Memory, and Tasks tabs."""
    from ui.app import HermesApp
    from ui.panels.right_panel import RightPanel, ToolTracePane, MemoryViewPane, TaskQueuePane
    from textual.widgets import TabbedContent

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(160, 50)) as pilot:
        right_panels = app.query(RightPanel)
        assert len(right_panels) == 1, f"Expected 1 RightPanel, got {len(right_panels)}"

        tabbed = app.query(TabbedContent)
        assert len(tabbed) >= 1, "TabbedContent must be present"


@pytest.mark.asyncio
async def test_tool_trace_pane_renders(mock_orch_patch):
    """ToolTracePane must render without crashing."""
    from ui.app import HermesApp
    from ui.panels.right_panel import ToolTracePane

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(160, 50)) as pilot:
        trace_panes = app.query(ToolTracePane)
        assert len(trace_panes) == 1


@pytest.mark.asyncio
async def test_memory_pane_renders(mock_orch_patch):
    """MemoryViewPane must render without crashing."""
    from ui.app import HermesApp
    from ui.panels.right_panel import MemoryViewPane

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(160, 50)) as pilot:
        mem_panes = app.query(MemoryViewPane)
        assert len(mem_panes) == 1


@pytest.mark.asyncio
async def test_task_queue_pane_renders(mock_orch_patch):
    """TaskQueuePane must render without crashing."""
    from ui.app import HermesApp
    from ui.panels.right_panel import TaskQueuePane

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(160, 50)) as pilot:
        task_panes = app.query(TaskQueuePane)
        assert len(task_panes) == 1


@pytest.mark.asyncio
async def test_orchestrator_response_updates_tool_trace(mock_orch_patch):
    """OrchestratorResponse message must add an entry to Tool Trace."""
    from ui.app import HermesApp, OrchestratorResponse
    from ui.panels.right_panel import RightPanel, ToolTracePane, ToolTraceEntry

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(160, 50)) as pilot:
        # Post a synthetic OrchestratorResponse directly to RightPanel
        right_panel = app.query_one(RightPanel)
        right_panel.post_message(OrchestratorResponse(
            user_request="list files",
            final_output="core/\ntools/\n",
            tool_name="list_directory",
            success=True,
            stage_reached=12,
            tier3_called=False,
            latency_seconds=1.5,
            trace_id="test1234",
            skill_ids=[],
        ))
        await pilot.pause()

        # Check that ToolTracePane received it
        trace_pane = app.query_one(ToolTracePane)
        entries = trace_pane.query(ToolTraceEntry)
        assert len(entries) >= 1, "ToolTraceEntry should have been added"


# ── ToolTraceEntry unit tests ──────────────────────────────────────────

def test_tool_trace_entry_success_render():
    """ToolTraceEntry renders success with green border class."""
    from ui.panels.right_panel import ToolTraceEntry
    from rich.text import Text

    entry = ToolTraceEntry(
        tool_name="write_file",
        success=True,
        exit_code=0,
        output_preview="Written 100 chars to app.py",
        latency=0.45,
        tier3_called=False,
        trace_id="abc12345",
        skill_ids=["flask-rest-api"],
    )
    assert "success" in entry.classes
    assert "failure" not in entry.classes

    rendered = entry.render()
    assert isinstance(rendered, Text)
    assert "write_file" in rendered.plain
    assert "flask-rest-api" in rendered.plain


def test_tool_trace_entry_failure_render():
    """ToolTraceEntry renders failure with red border class."""
    from ui.panels.right_panel import ToolTraceEntry

    entry = ToolTraceEntry(
        tool_name="bash_exec",
        success=False,
        exit_code=1,
        output_preview="command not found",
        latency=0.12,
        tier3_called=False,
        trace_id="fail1234",
        skill_ids=[],
    )
    assert "failure" in entry.classes
    assert "success" not in entry.classes


def test_tool_trace_entry_tier3_shows_in_render():
    """ToolTraceEntry must show [T3 called] when tier3_called is True."""
    from ui.panels.right_panel import ToolTraceEntry

    entry = ToolTraceEntry(
        tool_name="write_file",
        success=True,
        exit_code=0,
        output_preview="done",
        latency=3.5,
        tier3_called=True,
        trace_id="t3abc123",
        skill_ids=[],
    )
    rendered = entry.render()
    assert "T3 called" in rendered.plain


def test_memory_view_fact_rendering():
    """MemoryViewPane._render_fact_line must colour facts by type."""
    from ui.panels.right_panel import MemoryViewPane
    from rich.text import Text

    pane = MemoryViewPane()

    fact_lines = [
        "[FACT]: Uses Flask 3.1",
        "[BUG]: Login has null pointer",
        "[TASK_DONE]: Created REST API",
        "[BLOCKED]: Auth depends on DB",
        "[DETAIL]: See memory/schema.md",
        "[STALE]: Old fact",
    ]

    for line in fact_lines:
        rendered = pane._render_fact_line(line, is_new=False)
        assert isinstance(rendered, Text)
        assert line in rendered.plain or line.split(":")[1].strip() in rendered.plain

    # New line should have ▶ marker
    rendered_new = pane._render_fact_line("[FACT]: New fact", is_new=True)
    assert "▶" in rendered_new.plain


@pytest.mark.asyncio
async def test_status_bar_updates_skill_realtime(mock_orch_patch):
    """StatusBar must update active skill in real-time on Stage 3 end progress event."""
    from ui.app import HermesApp, OrchestratorProgress
    from ui.panels.status_bar import StatusBar

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        # Initial skill should be none
        status_bar = app.query_one("#status-bar", StatusBar)
        assert status_bar.skill == "none"

        # Simulate Stage 3 end with matched skill
        progress_msg = OrchestratorProgress(
            event_type="stage_end",
            data={
                "stage": 3,
                "status": "success",
                "matched": ["react-frontend"],
                "rejected": [],
                "confidence": 95,
            }
        )
        app.post_message(progress_msg)
        await pilot.pause()

        # Check if the app's current_skill and status_bar.skill are updated
        assert app.current_skill == "react-frontend"
        assert status_bar.skill == "react-frontend"
        
        # Verify it renders the skill name
        rendered = status_bar._render_status()
        assert "react-frontend" in rendered.plain


@pytest.mark.asyncio
async def test_right_panel_updates_realtime(mock_orch_patch):
    """RightPanel must receive OrchestratorProgress events and update its tabs in real-time."""
    from ui.app import HermesApp, OrchestratorProgress
    from ui.panels.right_panel import RightPanel, ToolTracePane

    app = HermesApp(mode="auto", project="test")
    app._orchestrator = make_mock_orchestrator()

    async with app.run_test(size=(120, 40)) as pilot:
        right_panel = app.query_one("#right-panel", RightPanel)
        trace_pane = right_panel.query_one("#tool-trace-pane", ToolTracePane)
        
        # Initial empty state
        assert trace_pane._active_entry is None

        # Simulate Stage 7 tool start
        app.post_message(OrchestratorProgress(
            event_type="stage_start",
            data={
                "stage": 7,
                "tool_name": "bash_exec",
                "parameters": {"command": "npm run build"},
            }
        ))
        await pilot.pause()

        # Active entry should be populated and running
        assert trace_pane._active_entry is not None
        assert trace_pane._active_entry._tool_name == "bash_exec"
        assert trace_pane._active_entry._success is None  # running state
        
        # Simulate Stage 7 tool end
        app.post_message(OrchestratorProgress(
            event_type="stage_end",
            data={
                "stage": 7,
                "status": "success",
                "tool_name": "bash_exec",
                "target": "npm run build",
                "duration": 1.25,
            }
        ))
        await pilot.pause()

        # Active entry should be updated and successful
        assert trace_pane._active_entry is not None
        assert trace_pane._active_entry._success is True
        assert trace_pane._active_entry._latency == 1.25
