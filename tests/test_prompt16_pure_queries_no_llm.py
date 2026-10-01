# tests/test_prompt16_pure_queries_no_llm.py
"""
Test Suite: Prompt 16 Pure Queries & Zero-LLM Invariant.

Verifies:
1. /status, /context, /cost, /doctor, /diff, /tasks are pure queries.
2. Under no circumstance do pure queries invoke the LLM.
3. Query handlers return well-structured data and user messages.
4. State mutations like /clear or read-only /goal also strictly make 0 LLM calls.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.commands.dispatcher import CommandDispatcher
from core.commands.models import (
    CommandExecutionClass,
    CommandIntent,
    CommandOrigin,
    CommandStatus,
    LlmPolicy,
)
from core.commands.parser import UnifiedInputParser
from core.commands.registry import CommandRegistry
from core.cost_ledger import CostLedger, cost_ledger
from core.event_bus import EventBus
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus, TaskState, TaskStatus
from core.runtime_state.store import StateStore


@pytest.fixture
def mock_model_client():
    mock = MagicMock()
    mock.generate = AsyncMock(side_effect=AssertionError("LLM MUST NOT BE CALLED FOR PURE QUERIES"))
    mock.complete = AsyncMock(side_effect=AssertionError("LLM MUST NOT BE CALLED FOR PURE QUERIES"))
    mock.chat = AsyncMock(side_effect=AssertionError("LLM MUST NOT BE CALLED FOR PURE QUERIES"))
    return mock


@pytest.fixture
def test_env(tmp_path: Path):
    event_bus = EventBus(enabled=True)
    state_store = StateStore(mission_id="m-test-1", session_id="s-test-1")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Pre-populate state
    state_store._state.mission = MissionState(
        mission_id="m-test-1",
        status=MissionStatus.RUNNING,
        title="Test Mission",
    )
    state_store._state.tasks["task-1"] = TaskState(
        task_id="task-1",
        mission_id="m-test-1",
        title="Implement test harness",
        description="Implement test harness",
        status=TaskStatus.RUNNING,
    )

    registry = CommandRegistry()
    return {
        "event_bus": event_bus,
        "state_store": state_store,
        "workspace": workspace,
        "registry": registry,
    }


@pytest.mark.asyncio
async def test_pure_query_registry_llm_policy(test_env):
    """Verify registry policy marks pure queries as LlmPolicy.NEVER."""
    registry = test_env["registry"]
    pure_queries = ["status", "context", "cost", "doctor", "diff", "tasks"]

    for cmd_name in pure_queries:
        defn = registry.get_definition(cmd_name)
        assert defn is not None, f"Command /{cmd_name} missing from registry"
        assert defn.llm_policy == LlmPolicy.NEVER, f"/{cmd_name} must have LlmPolicy.NEVER"
        assert defn.execution_class == CommandExecutionClass.PURE_QUERY, f"/{cmd_name} must be PURE_QUERY"


@pytest.mark.asyncio
async def test_status_query_no_llm(test_env, mock_model_client):
    """Verify /status executes purely from StateStore and makes 0 LLM calls."""
    dispatcher = CommandDispatcher(
        registry=test_env["registry"],
        workspace_root=test_env["workspace"],
        state_store=test_env["state_store"],
        event_bus=test_env["event_bus"],
        model_client=mock_model_client,
    )

    intent = CommandIntent.create(
        name="status",
        args=(),
        raw_text="/status",
        origin=CommandOrigin.USER_CLI,
    )

    res = await dispatcher.dispatch(intent)
    assert res.status == CommandStatus.SUCCESS
    assert res.llm_called is False
    assert res.execution_class == CommandExecutionClass.PURE_QUERY
    assert "m-test-1" in res.message or "RUNNING" in res.message
    assert res.data.get("mission_status") == "RUNNING"
    mock_model_client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_context_query_no_llm(test_env, mock_model_client):
    """Verify /context inspects context budget without LLM."""
    mock_context_engine = MagicMock()
    mock_report = MagicMock()
    mock_report.health_state.value = "HEALTHY"
    mock_report.total_capacity_tokens = 8000
    mock_report.used_tokens = 1250
    mock_report.utilization_percent = 15.6
    mock_report.remaining_tokens = 6750
    mock_report.breakdown_by_section = {"system": 500, "history": 750}
    mock_report.warnings = []
    mock_context_engine.budgeter.get_budget_report.return_value = mock_report

    dispatcher = CommandDispatcher(
        registry=test_env["registry"],
        workspace_root=test_env["workspace"],
        state_store=test_env["state_store"],
        event_bus=test_env["event_bus"],
        context_engine=mock_context_engine,
        model_client=mock_model_client,
    )

    intent = CommandIntent.create(
        name="context",
        args=(),
        raw_text="/context",
        origin=CommandOrigin.USER_CLI,
    )

    res = await dispatcher.dispatch(intent)
    assert res.status == CommandStatus.SUCCESS
    assert res.llm_called is False
    assert "1,250" in res.message or "1250" in res.message
    assert res.data["used_tokens"] == 1250
    mock_model_client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_cost_query_no_llm(test_env, mock_model_client):
    """Verify /cost retrieves CostLedger data without calling LLM."""
    cost_ledger.record_usage(
        tier="T1",
        provider="nvidia_nim",
        model="glm-5.3-flash",
        attribution="primary",
        prompt_tokens=100,
        completion_tokens=50,
        latency_seconds=0.1,
    )
    cost_ledger.record_usage(
        tier="T2",
        provider="ollama",
        model="gpt-oss:120b-cloud",
        attribution="repair",
        prompt_tokens=500,
        completion_tokens=200,
        latency_seconds=0.5,
    )

    dispatcher = CommandDispatcher(
        registry=test_env["registry"],
        workspace_root=test_env["workspace"],
        state_store=test_env["state_store"],
        event_bus=test_env["event_bus"],
        model_client=mock_model_client,
    )

    intent = CommandIntent.create(
        name="cost",
        args=(),
        raw_text="/cost",
        origin=CommandOrigin.USER_CLI,
    )

    res = await dispatcher.dispatch(intent)
    assert res.status == CommandStatus.SUCCESS
    assert res.llm_called is False
    assert "HERMES Model Usage & Cost Ledger" in res.message
    assert "T1" in res.message
    assert "T2" in res.message
    assert res.data["total_tokens"] >= 850
    mock_model_client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_doctor_query_no_llm(test_env, mock_model_client):
    """Verify /doctor inspects system environment locally without calling LLM."""
    dispatcher = CommandDispatcher(
        registry=test_env["registry"],
        workspace_root=test_env["workspace"],
        state_store=test_env["state_store"],
        event_bus=test_env["event_bus"],
        model_client=mock_model_client,
    )

    intent = CommandIntent.create(
        name="doctor",
        args=(),
        raw_text="/doctor",
        origin=CommandOrigin.USER_CLI,
    )

    res = await dispatcher.dispatch(intent)
    assert res.status == CommandStatus.SUCCESS
    assert res.llm_called is False
    assert "HERMES System Diagnostics (/doctor)" in res.message
    assert "Python Version" in res.message
    assert res.data["all_pass"] is True
    mock_model_client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_diff_query_no_llm(test_env, mock_model_client):
    """Verify /diff checks git diff safely without LLM."""
    dispatcher = CommandDispatcher(
        registry=test_env["registry"],
        workspace_root=test_env["workspace"],
        state_store=test_env["state_store"],
        event_bus=test_env["event_bus"],
        model_client=mock_model_client,
    )

    intent = CommandIntent.create(
        name="diff",
        args=(),
        raw_text="/diff",
        origin=CommandOrigin.USER_CLI,
    )

    res = await dispatcher.dispatch(intent)
    assert res.status == CommandStatus.SUCCESS
    assert res.llm_called is False
    assert res.execution_class == CommandExecutionClass.PURE_QUERY
    mock_model_client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_tasks_query_no_llm(test_env, mock_model_client):
    """Verify /tasks queries StateStore task list without LLM."""
    dispatcher = CommandDispatcher(
        registry=test_env["registry"],
        workspace_root=test_env["workspace"],
        state_store=test_env["state_store"],
        event_bus=test_env["event_bus"],
        model_client=mock_model_client,
    )

    intent = CommandIntent.create(
        name="tasks",
        args=(),
        raw_text="/tasks",
        origin=CommandOrigin.USER_CLI,
    )

    res = await dispatcher.dispatch(intent)
    assert res.status == CommandStatus.SUCCESS
    assert res.llm_called is False
    assert "task-1" in res.message or "Implement test harness" in res.message
    assert res.data["tasks_count"] == 1
    mock_model_client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_clear_and_goal_query_no_llm(test_env, mock_model_client):
    """Verify /clear and read-only /goal do not invoke LLM."""
    dispatcher = CommandDispatcher(
        registry=test_env["registry"],
        workspace_root=test_env["workspace"],
        state_store=test_env["state_store"],
        event_bus=test_env["event_bus"],
        model_client=mock_model_client,
    )

    # 1. /goal without arguments (pure query)
    res_goal = await dispatcher.dispatch(
        CommandIntent.create(name="goal", args=(), raw_text="/goal", origin=CommandOrigin.USER_CLI)
    )
    assert res_goal.status == CommandStatus.SUCCESS
    assert res_goal.llm_called is False
    assert res_goal.execution_class == CommandExecutionClass.PURE_QUERY

    # 2. /clear (state mutation, no LLM)
    res_clear = await dispatcher.dispatch(
        CommandIntent.create(name="clear", args=(), raw_text="/clear", origin=CommandOrigin.USER_CLI)
    )
    assert res_clear.status == CommandStatus.SUCCESS
    assert res_clear.llm_called is False
    assert res_clear.execution_class == CommandExecutionClass.STATE_MUTATION

    mock_model_client.generate.assert_not_called()
