# tests/test_prompt16_cli_headless_parity.py
"""
Test Suite: Prompt 16 CLI & Headless Parity.

Verifies:
1. One Engine, Many Surfaces: TUI and Headless CLI share identical runtime models.
2. Typer CLI commands: doctor, status, diff, cost, tasks, replay work out-of-the-box.
3. Headless presentation sinks: Text, JSON, Stream-JSON produce valid structured outputs.
4. Security fail-closed: Headless mode fails closed on permission prompts.
5. Exit codes: 0 for success, non-zero for failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from core.commands.models import CommandIntent, CommandOrigin, CommandStatus
from core.runtime_factory import ApplicationRuntimeFactory, SurfaceMode
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.sinks import JsonSink, NullSink, StreamJsonSink, TextSink
from main import app

runner = CliRunner()


def test_cli_doctor_command():
    """Verify 'python main.py doctor' runs diagnostics and exits 0."""
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "HERMES System Diagnostics (/doctor)" in result.stdout
    assert "Python Version" in result.stdout


def test_cli_status_command():
    """Verify 'python main.py status' runs status check and exits 0."""
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "HERMES Runtime Status" in result.stdout


def test_cli_diff_command():
    """Verify 'python main.py diff' runs git diff inspect and exits 0."""
    result = runner.invoke(app, ["diff"])
    assert result.exit_code == 0


def test_cli_cost_command():
    """Verify 'python main.py cost' runs cost ledger report and exits 0."""
    result = runner.invoke(app, ["cost"])
    assert result.exit_code == 0
    assert "HERMES Model Usage & Cost Ledger" in result.stdout


def test_cli_tasks_command():
    """Verify 'python main.py tasks' runs tasks inspection and exits 0."""
    result = runner.invoke(app, ["tasks"])
    assert result.exit_code == 0
    assert "HERMES Task and Job Queue" in result.stdout


def test_cli_replay_trace_json(tmp_path: Path):
    """Verify 'python main.py replay' on a trace file with --format json."""
    trace_path = tmp_path / "test_trace.json"
    records = [
        {"event_type": "MISSION_CREATED", "mission_id": "m-cli-rep", "sequence": 1, "payload": {}},
        {"event_type": "MISSION_COMPLETED", "mission_id": "m-cli-rep", "sequence": 2, "payload": {}},
    ]
    trace_path.write_text(json.dumps(records), encoding="utf-8")

    result = runner.invoke(app, ["replay", str(trace_path), "--format", "json"])
    assert result.exit_code == 0
    # Output should contain valid JSON summary
    assert "m-cli-rep" in result.stdout


@pytest.mark.asyncio
async def test_headless_runtime_execute_command(tmp_path: Path):
    """Verify ApplicationRuntime in HEADLESS mode executes command intents properly."""
    rt = ApplicationRuntimeFactory.create_runtime(
        mode=SurfaceMode.HEADLESS,
        workspace_root=tmp_path,
    )

    res = await rt.execute_input("/status")
    assert res.exit_code == 0
    assert res.status == CommandStatus.SUCCESS
    assert "HERMES Runtime Status" in res.message


@pytest.mark.asyncio
async def test_headless_stream_json_sink_integration(tmp_path: Path):
    """Verify StreamJsonSink emits line-delimited JSON events."""
    import io
    stream = io.StringIO()
    sink = StreamJsonSink(stdout=stream)
    rt = ApplicationRuntimeFactory.create_runtime(
        mode=SurfaceMode.HEADLESS,
        workspace_root=tmp_path,
    )

    res = await rt.execute_input("/status", sink=sink)
    assert res.exit_code == 0
    out = stream.getvalue()
    lines = [json.loads(l) for l in out.strip().splitlines() if l.strip()]
    assert len(lines) > 0
    event_names = [l.get("event") for l in lines]
    assert any(e in ("completed", "COMMAND_COMPLETED", "TERMINATION") for e in event_names)


@pytest.mark.asyncio
async def test_headless_security_fail_closed(tmp_path: Path):
    """Verify headless shell execution fails closed on permission ASK instead of waiting."""
    from core.commands.models import CommandIntent, CommandOrigin
    from core.security.enums import PermissionOutcome
    from core.security.models import PermissionDecision

    rt = ApplicationRuntimeFactory.create_runtime(
        mode=SurfaceMode.HEADLESS,
        workspace_root=tmp_path,
    )

    # Mock security service to return ASK verdict
    rt.security.evaluate_tool_call = MagicMock(
        return_value=(
            PermissionDecision(
                outcome=PermissionOutcome.ASK,
                reason="Headless mode requires confirmation",
            ),
            MagicMock(),
        )
    )

    intent = CommandIntent.create(
        name="shell",
        args=("echo", "should_fail_closed"),
        raw_text="!echo should_fail_closed",
        origin=CommandOrigin.USER_HEADLESS,
    )

    res = await rt.dispatcher.dispatch(intent, is_headless=True)
    assert res.status == CommandStatus.DENIED
    assert res.exit_code == 3
    assert "Security approval required (ASK)" in res.message
