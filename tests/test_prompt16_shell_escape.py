# tests/test_prompt16_shell_escape.py
"""Tests for ! shell command execution, security enforcement, and text safety."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from core.commands.models import CommandIntent, CommandOrigin, CommandStatus
from core.commands.shell import ShellExecutor
from core.event_bus import EventBus
from core.runtime_state.events import EventType
from core.security.config import SecurityPolicy
from core.security.enums import PermissionOutcome
from core.security.models import ActionDescriptor, PermissionDecision
from core.security.service import SecurityService


@pytest.fixture
def temp_workspace():
    import shutil
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir).resolve()
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_safe_shell_execution(temp_workspace):
    """Verify safe harmless command executes directly without calling model."""
    executor = ShellExecutor(workspace_root=temp_workspace)
    intent = CommandIntent.create("shell", "!python -c \"print('HERMES_SHELL_OK')\"")

    res = await executor.execute_command(intent)

    assert res.status == CommandStatus.SUCCESS
    assert res.exit_code == 0
    assert "HERMES_SHELL_OK" in res.message
    assert res.llm_called is False


@pytest.mark.asyncio
async def test_shell_non_zero_exit_code(temp_workspace):
    """Verify non-zero exit code propagates correctly."""
    executor = ShellExecutor(workspace_root=temp_workspace)
    intent = CommandIntent.create("shell", "!python -c \"import sys; sys.exit(7)\"")

    res = await executor.execute_command(intent)

    assert res.status == CommandStatus.FAILURE
    assert res.exit_code == 7
    assert res.llm_called is False


@pytest.mark.asyncio
async def test_shell_security_denial_blocks_execution(temp_workspace):
    """Verify Prompt 13 security policy can DENY a shell command."""
    mock_security = MagicMock(spec=SecurityService)
    # Configure security to DENY
    mock_security.evaluate_tool_call.return_value = (
        PermissionDecision(
            outcome=PermissionOutcome.DENY,
            reason="Destructive shell commands prohibited by policy",
        ),
        MagicMock(spec=ActionDescriptor),
    )

    executor = ShellExecutor(workspace_root=temp_workspace, security_service=mock_security)
    intent = CommandIntent.create("shell", "!format C:")

    res = await executor.execute_command(intent)

    assert res.status == CommandStatus.DENIED
    assert res.exit_code == 3
    assert "Security policy denied" in res.message


@pytest.mark.asyncio
async def test_shell_headless_ask_fails_closed(temp_workspace):
    """Verify ASK outcome fails closed (DENIED) in headless mode."""
    mock_security = MagicMock(spec=SecurityService)
    mock_security.evaluate_tool_call.return_value = (
        PermissionDecision(
            outcome=PermissionOutcome.ASK,
            reason="Requires operator review",
        ),
        MagicMock(spec=ActionDescriptor),
    )

    executor = ShellExecutor(workspace_root=temp_workspace, security_service=mock_security)
    intent = CommandIntent.create("shell", "!npm publish")

    res = await executor.execute_command(intent, is_headless=True)

    assert res.status == CommandStatus.DENIED
    assert res.exit_code == 3
    assert "no interactive channel" in res.message


@pytest.mark.asyncio
async def test_shell_timeout_containment(temp_workspace):
    """Verify long-running command times out safely."""
    executor = ShellExecutor(workspace_root=temp_workspace)
    # Sleep command for 5 seconds with 0.5s timeout
    intent = CommandIntent.create("shell", "!python -c \"import time; time.sleep(5)\"")

    res = await executor.execute_command(intent, timeout_seconds=0.5)

    assert res.status == CommandStatus.FAILURE
    assert res.exit_code == 124
    assert res.data.get("timed_out") is True


@pytest.mark.asyncio
async def test_shell_output_sanitization(temp_workspace):
    """Verify ANSI escape injection in stdout is neutralized by text safety."""
    executor = ShellExecutor(workspace_root=temp_workspace)
    # Output raw ANSI clear screen and color
    script = "import sys; sys.stdout.write('\\x1b[2J\\x1b[31mMALICIOUS\\x1b[0m\\n')"
    intent = CommandIntent.create("shell", f'!python -c "{script}"')

    res = await executor.execute_command(intent)

    assert res.status == CommandStatus.SUCCESS
    # Terminal text sanitizer must strip escape codes
    assert "\x1b" not in res.message
    assert "MALICIOUS" in res.message


@pytest.mark.asyncio
async def test_shell_publishes_lifecycle_events(temp_workspace):
    """Verify EventBus receives job start and completion events."""
    event_bus = EventBus()
    events_received = []

    event_bus.subscribe(lambda evt: events_received.append(evt))

    executor = ShellExecutor(workspace_root=temp_workspace, event_bus=event_bus)
    intent = CommandIntent.create("shell", "!python -c \"print('ok')\"")

    await executor.execute_command(intent)

    event_types = [e.event_type.value for e in events_received]
    assert "BACKGROUND_JOB_STARTED" in event_types
    assert "BACKGROUND_JOB_COMPLETED" in event_types
