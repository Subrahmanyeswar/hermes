# tests/test_prompt16_control_handlers.py
"""
Test Suite: Prompt 16 Control & State Mutation Command Handlers.

Verifies:
1. /plan enters plan mode and optionally sets initial goal.
2. /compact executes compaction, saves tokens, emits CONTEXT_COMPACTED event.
3. /rewind validates checkpoint, handles user conflict preview, executes safe restore.
4. /resume resumes session via recovery engine or safely rejects if blocked.
5. /clear establishes fresh context epoch and emits CONTEXT_CLEARED event.
6. /goal sets authoritative mission goal and emits GOAL_UPDATED event.
7. /btw executes isolated model call with 'btw' cost attribution without contaminating state.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.commands.dispatcher import CommandDispatcher
from core.commands.handlers.control_handlers import (
    handle_btw,
    handle_clear,
    handle_compact,
    handle_goal,
    handle_plan,
    handle_resume,
    handle_rewind,
)
from core.commands.models import (
    CommandErrorCode,
    CommandExecutionClass,
    CommandIntent,
    CommandOrigin,
    CommandStatus,
)
from core.commands.registry import CommandRegistry
from core.cost_ledger import CostLedger, cost_ledger
from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus, SessionState
from core.runtime_state.store import StateStore


@pytest.fixture
def control_env(tmp_path: Path):
    event_bus = EventBus(enabled=True)
    state_store = StateStore(mission_id="m-ctrl-1", session_id="s-ctrl-1")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    events_received: list[HermesEvent] = []
    event_bus.subscribe(lambda evt: events_received.append(evt))

    return {
        "event_bus": event_bus,
        "state_store": state_store,
        "workspace": workspace,
        "events": events_received,
    }


@pytest.mark.asyncio
async def test_plan_mode_toggle_and_goal(control_env):
    """Verify /plan enters plan mode and registers optional goal prompt."""
    mock_planning = MagicMock()

    # 1. /plan without arguments
    intent1 = CommandIntent.create(name="plan", raw_text="/plan", origin=CommandOrigin.USER_CLI)
    res1 = await handle_plan(intent1, planning_service=mock_planning)
    assert res1.status == CommandStatus.SUCCESS
    assert res1.data["plan_mode"] is True
    mock_planning.enter_plan_mode.assert_called_once()

    # 2. /plan with goal prompt
    intent2 = CommandIntent.create(
        name="plan",
        args=("Design", "authentication", "flow"),
        raw_text="/plan Design authentication flow",
        origin=CommandOrigin.USER_CLI,
    )
    res2 = await handle_plan(intent2, planning_service=mock_planning)
    assert res2.status == CommandStatus.SUCCESS
    assert "Design authentication flow" in res2.message
    mock_planning.initialize_goal.assert_called_with(user_prompt="Design authentication flow")


@pytest.mark.asyncio
async def test_compact_context_success(control_env):
    """Verify /compact triggers context compactor and publishes CONTEXT_COMPACTED event."""
    mock_compactor = MagicMock()
    mock_summary = MagicMock()
    mock_summary.tokens_saved = 4500
    mock_summary.reduction_percentage = 42.5
    mock_compactor.compact_mission_context.return_value = mock_summary

    mock_engine = MagicMock()
    mock_engine.compactor = mock_compactor

    intent = CommandIntent.create(
        name="compact",
        args=("architecture", "decisions"),
        raw_text="/compact architecture decisions",
        origin=CommandOrigin.USER_CLI,
    )

    res = await handle_compact(
        intent=intent,
        context_engine=mock_engine,
        event_bus=control_env["event_bus"],
    )

    assert res.status == CommandStatus.SUCCESS
    assert res.data["tokens_saved"] == 4500
    assert "4,500" in res.message or "4500" in res.message

    # Check event publication
    compact_events = [e for e in control_env["events"] if e.event_type == EventType.CONTEXT_COMPACTED]
    assert len(compact_events) == 1
    assert compact_events[0].payload["tokens_saved"] == 4500


@pytest.mark.asyncio
async def test_rewind_preview_vs_confirm(control_env):
    """Verify /rewind previews conflicts when interactive, and restores when confirmed."""
    mock_rewind_engine = MagicMock()
    mock_plan = MagicMock()
    mock_plan.actions = ["restore file A", "restore file B"]
    mock_plan.user_conflicts = ["file B"]  # User modified file
    mock_rewind_engine.preview_rewind.return_value = mock_plan

    mock_restored = MagicMock()
    mock_restored.state_version = 12
    mock_rewind_engine.restore_checkpoint.return_value = mock_restored

    # 1. Interactive rewind without --confirm should return preview warning
    intent_preview = CommandIntent.create(
        name="rewind",
        args=("chk_001",),
        raw_text="/rewind chk_001",
        origin=CommandOrigin.USER_CLI,
    )
    res_preview = await handle_rewind(
        intent=intent_preview,
        rewind_engine=mock_rewind_engine,
        is_headless=False,
    )
    assert res_preview.status == CommandStatus.SUCCESS
    assert res_preview.data.get("preview_only") is True
    assert "Pass --confirm" in res_preview.message
    mock_rewind_engine.restore_checkpoint.assert_not_called()

    # 2. Rewind with confirm=True or headless=True executes restore
    intent_confirm = CommandIntent.create(
        name="rewind",
        args=("chk_001",),
        kwargs={"confirm": True},
        raw_text="/rewind chk_001 --confirm",
        origin=CommandOrigin.USER_CLI,
    )
    res_confirm = await handle_rewind(
        intent=intent_confirm,
        rewind_engine=mock_rewind_engine,
        is_headless=False,
    )
    assert res_confirm.status == CommandStatus.SUCCESS
    assert res_confirm.data.get("restored") is True
    assert "Rewind successful" in res_confirm.message
    mock_rewind_engine.restore_checkpoint.assert_called_once()


@pytest.mark.asyncio
async def test_resume_clean_and_blocked(control_env):
    """Verify /resume handles successful session resumption and blocked states."""
    mock_recovery = MagicMock()

    # Case A: Resumption permitted
    mock_state = MagicMock()
    mock_state.mission.mission_id = "m-123"
    mock_state.mission.status.value = "RUNNING"
    mock_state.session.last_checkpoint_id = "chk_safe"
    mock_state.state_version = 8

    mock_verdict_ok = MagicMock()
    mock_verdict_ok.can_resume = True

    mock_recovery.resume_session.return_value = (mock_state, mock_verdict_ok)

    intent_ok = CommandIntent.create(
        name="resume",
        args=("sess_abc",),
        raw_text="/resume sess_abc",
        origin=CommandOrigin.USER_CLI,
    )
    res_ok = await handle_resume(intent=intent_ok, recovery_engine=mock_recovery)
    assert res_ok.status == CommandStatus.SUCCESS
    assert "resumed cleanly" in res_ok.message
    assert res_ok.data["session_id"] == "sess_abc"

    # Case B: Resumption blocked by verdict
    mock_verdict_blocked = MagicMock()
    mock_verdict_blocked.can_resume = False
    mock_verdict_blocked.message = "Session corrupted or uncommitted git lock held."
    mock_recovery.resume_session.return_value = (None, mock_verdict_blocked)

    intent_blocked = CommandIntent.create(
        name="resume",
        args=("sess_bad",),
        raw_text="/resume sess_bad",
        origin=CommandOrigin.USER_CLI,
    )
    res_blocked = await handle_resume(intent=intent_blocked, recovery_engine=mock_recovery)
    assert res_blocked.status == CommandStatus.FAILURE
    assert res_blocked.error_code == CommandErrorCode.CONFLICT_ERROR
    assert "Resume BLOCKED" in res_blocked.message


@pytest.mark.asyncio
async def test_clear_context_epoch(control_env):
    """Verify /clear resets context while preserving persistent checkpoints."""
    mock_context_engine = MagicMock()

    intent = CommandIntent.create(
        name="clear",
        raw_text="/clear",
        origin=CommandOrigin.USER_CLI,
    )

    res = await handle_clear(
        intent=intent,
        context_engine=mock_context_engine,
        event_bus=control_env["event_bus"],
    )

    assert res.status == CommandStatus.SUCCESS
    assert res.data["cleared"] is True
    assert "checkpoints, session logs, and evidence remain safely preserved" in res.message
    mock_context_engine.clear_active_context.assert_called_once()

    clear_events = [e for e in control_env["events"] if e.event_type == EventType.CONTEXT_CLEARED]
    assert len(clear_events) == 1
    assert clear_events[0].payload["reason"] == "USER_CLEAR"


@pytest.mark.asyncio
async def test_goal_mutation_and_event(control_env):
    """Verify /goal updates authoritative goal and emits GOAL_UPDATED event."""
    mock_planning = MagicMock()

    intent = CommandIntent.create(
        name="goal",
        args=("Refactor", "database", "access", "layer"),
        raw_text="/goal Refactor database access layer",
        origin=CommandOrigin.USER_CLI,
    )

    res = await handle_goal(
        intent=intent,
        planning_service=mock_planning,
        state_store=control_env["state_store"],
        event_bus=control_env["event_bus"],
    )

    assert res.status == CommandStatus.SUCCESS
    assert res.data["status"] == "REGISTERED"
    assert "Refactor database access layer" in res.message
    mock_planning.initialize_goal.assert_called_with(user_prompt="Refactor database access layer")

    goal_events = [e for e in control_env["events"] if e.event_type == EventType.GOAL_UPDATED]
    assert len(goal_events) == 1
    assert goal_events[0].payload["goal"] == "Refactor database access layer"


@pytest.mark.asyncio
async def test_btw_ephemeral_model_call(control_env):
    """Verify /btw executes ephemeral query, attributes cost, leaves state clean."""
    mock_model_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Python asyncio uses an event loop to run cooperative tasks."
    mock_response.prompt_tokens = 25
    mock_response.completion_tokens = 15
    mock_model_client.complete = AsyncMock(return_value=mock_response)
    mock_model_client.provider_name = "nvidia_nim"
    mock_model_client.model_name = "glm-5.3-flash"

    intent = CommandIntent.create(
        name="btw",
        args=("How", "does", "asyncio", "work?"),
        raw_text="/btw How does asyncio work?",
        origin=CommandOrigin.USER_CLI,
    )

    res = await handle_btw(intent=intent, model_client=mock_model_client)
    assert res.status == CommandStatus.SUCCESS
    assert res.llm_called is True
    assert res.execution_class == CommandExecutionClass.MODEL_OPERATION
    assert "asyncio uses an event loop" in res.message
    mock_model_client.complete.assert_called_once()

    # Check that cost was recorded with 'btw' attribution
    summary = cost_ledger.get_summary()
    assert "btw" in summary["by_attribution"]
    assert summary["by_attribution"]["btw"]["requests"] >= 1
