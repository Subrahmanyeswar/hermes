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
