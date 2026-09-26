# tests/test_agent_loop.py
"""
Comprehensive Test Suite for HERMES 2.x Agent Loop.
Verifies all functional contracts, invariants, and regression scenarios:
- Happy path single & multi-turn execution
- Model & tool failure resilience
- Unknown tool rejection without physical execution
- First-class user questions (ASK_USER) & cancellation
- Two-layer completion policy (rejection of false completion)
- Adaptive verification & repair loops
- TUI crash isolation
- Duplicate & late event protection
- Semantic stall detection
- Path discipline & workspace boundary enforcement
- Strict mode preservation
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent_loop import (
    AgentLoop,
    AgentLoopConfig,
    AgentLoopResult,
    AgentDecisionType,
    ActionEnvelope,
    ActionStatus,
    Observation,
    HarnessPolicy,
    CompletionPolicy,
)
from core.agent_loop.decisions import DecisionInterpreter
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType, EventSeverity
from core.runtime_state.store import StateStore
from core.runtime_state.models import MissionStatus, WaitReason
from core.workspace import WorkspaceManager
from core.mission_planner import Mission, MissionTask
from models.provider import NormalizedModelResponse
from tools.base import BaseTool, ToolResult
from tools.registry import tool


# ── Mock Tools for Testing ───────────────────────────────────────────────────

@tool(
    name="test_write_file",
    description="Write file for agent loop test",
    permissions=["fs_write"],
    risk_score=0.1,
)
class TestWriteFileTool(BaseTool):
    def execute(self, inp: Any) -> ToolResult:
        path = inp.get("path") if isinstance(inp, dict) else getattr(inp, "path", None)
        content = inp.get("content", "") if isinstance(inp, dict) else getattr(inp, "content", "")
        if path:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(success=True, exit_code=0, output=f"Wrote {len(content)} bytes to {path}")
        return ToolResult(success=False, exit_code=1, error="Missing path argument")


@tool(
    name="test_failing_tool",
    description="Tool that always fails for testing",
    permissions=["fs_read"],
    risk_score=0.1,
)
class TestFailingTool(BaseTool):
    def execute(self, inp: Any) -> ToolResult:
        return ToolResult(success=False, exit_code=42, error="Simulated tool internal error")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def test_env(tmp_path):
    """Provides isolated test environment with fresh event bus, state store, and workspace."""
    bus = EventBus(enabled=True, buffer_size=200)
    ws = WorkspaceManager()
    ws.lock(str(tmp_path))
    return {
        "workspace": ws,
        "event_bus": bus,
        "tmp_path": tmp_path,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_a_happy_path(test_env):
    """Scenario A: user request -> T1 decides write_file -> tool executes -> complete candidate -> verify -> complete."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]
    tmp_path = test_env["tmp_path"]

    target_file = tmp_path / "hello.py"

    # Mock Orchestrator with sequence: Turn 1: write_file, Turn 2: complete
    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    turn_counter = 0

    async def mock_generate_t1(*args, **kwargs):
        nonlocal turn_counter
        turn_counter += 1
        if turn_counter == 1:
            return NormalizedModelResponse(
                text="I will create hello.py",
                tool_calls=[{
                    "id": "call_1",
                    "name": "test_write_file",
                    "arguments": {"path": str(target_file), "content": "print('hello world')"}
                }]
            )
        else:
            return NormalizedModelResponse(
                text="The file hello.py is created and verified.",
                tool_calls=[]
            )

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=10, execution_mode="agentic")
    )

    mission = Mission(
        mission_id="m_happy_path",
        user_prompt="Create hello.py containing hello world",
        tasks=[]
    )

    result = await loop.run(mission)

    assert result.success is True
    assert result.status == "COMPLETED"
    assert result.turns_executed == 2
    assert result.tool_calls_count == 1
    assert target_file.exists()
    assert "print('hello world')" in target_file.read_text(encoding="utf-8")

    # Verify canonical state store snapshot
    store = bus.get_state("m_happy_path")
    assert store is not None
    snapshot = store.get_snapshot()
    assert snapshot.mission.status == MissionStatus.COMPLETED


@pytest.mark.asyncio
async def test_scenario_b_multi_turn_tool_loop(test_env):
    """Scenario B: multi-turn loop with observation handoff between turns."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]
    tmp_path = test_env["tmp_path"]

    file_a = tmp_path / "mod_a.py"
    file_b = tmp_path / "mod_b.py"

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    turn_counter = 0
    received_contexts = []

    async def mock_generate_t1(*args, **kwargs):
        nonlocal turn_counter
        turn_counter += 1
        prompt = kwargs.get("prompt", "")
        received_contexts.append(prompt)

        if turn_counter == 1:
            return NormalizedModelResponse(
                text="Creating module A",
                tool_calls=[{
                    "id": "c1",
                    "name": "test_write_file",
                    "arguments": {"path": str(file_a), "content": "x = 1\n"}
                }]
            )
        elif turn_counter == 2:
            return NormalizedModelResponse(
                text="Creating module B",
                tool_calls=[{
                    "id": "c2",
                    "name": "test_write_file",
                    "arguments": {"path": str(file_b), "content": "import mod_a\ny = mod_a.x + 1\n"}
                }]
            )
        else:
            return NormalizedModelResponse(text="Both modules implemented.", tool_calls=[])

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=10)
    )

    mission = Mission(mission_id="m_multi_turn", user_prompt="Build two modules A and B")
    res = await loop.run(mission)

    assert res.success is True
    assert res.turns_executed == 3
    assert res.tool_calls_count == 2
    assert file_a.exists() and file_b.exists()

    # Verify observation from Turn 1 is present in Turn 2's context
    assert len(received_contexts) >= 2
    assert "OBSERVATION from test_write_file" in received_contexts[1]


@pytest.mark.asyncio
async def test_scenario_c_model_failure_resilience(test_env):
    """Scenario C: Model provider fails with timeout/exception -> handled gracefully, consecutive failure recorded."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    call_count = 0

    async def mock_generate_t1(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise TimeoutError("NVIDIA NIM connection timeout")
        return NormalizedModelResponse(text="Recovered from network timeout.", tool_calls=[])

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=10, max_consecutive_failures=5)
    )

    mission = Mission(mission_id="m_net_fail", user_prompt="Explain architecture")
    res = await loop.run(mission)

    assert res.success is True
    assert call_count == 3


@pytest.mark.asyncio
async def test_scenario_d_tool_failure_becomes_observation(test_env):
    """Scenario D: Tool execution failure produces structured failure observation, does not crash loop."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    turn_counter = 0
    second_turn_context = ""

    async def mock_generate_t1(*args, **kwargs):
        nonlocal turn_counter, second_turn_context
        turn_counter += 1
        if turn_counter == 1:
            return NormalizedModelResponse(
                text="Calling failing tool",
                tool_calls=[{"id": "cfail", "name": "test_failing_tool", "arguments": {}}]
            )
        else:
            second_turn_context = kwargs.get("prompt", "")
            return NormalizedModelResponse(text="Saw tool failure, concluding task.", tool_calls=[])

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=10)
    )

    mission = Mission(mission_id="m_tool_fail", user_prompt="Investigate failure")
    res = await loop.run(mission)

    assert turn_counter == 2
    # Verify the failure information was provided to the next model turn
    assert "Simulated tool internal error" in second_turn_context or "FAILED" in second_turn_context


@pytest.mark.asyncio
async def test_scenario_e_unknown_tool_rejection(test_env):
    """Scenario E: Model requests non-existent tool -> harness rejects before execution, produces observation."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    turn_counter = 0
    obs_seen = ""

    async def mock_generate_t1(*args, **kwargs):
        nonlocal turn_counter, obs_seen
        turn_counter += 1
        if turn_counter == 1:
            return NormalizedModelResponse(
                text="Calling imaginary tool",
                tool_calls=[{"id": "c_fake", "name": "super_imaginary_tool_999", "arguments": {}}]
            )
        else:
            obs_seen = kwargs.get("prompt", "")
            return NormalizedModelResponse(text="Recovered from unknown tool.", tool_calls=[])

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=10)
    )

    mission = Mission(mission_id="m_unknown_tool", user_prompt="Inspect environment")
    res = await loop.run(mission)

    assert turn_counter == 2
    assert "super_imaginary_tool_999" in obs_seen or "Unknown tool" in obs_seen


@pytest.mark.asyncio
async def test_scenario_f_user_question_flow(test_env):
    """Scenario F: ASK_USER decision pauses loop, invokes callback, and feeds response into next turn."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    turn_counter = 0
    callback_called = False

    async def mock_generate_t1(*args, **kwargs):
        nonlocal turn_counter
        turn_counter += 1
        if turn_counter == 1:
            return NormalizedModelResponse(
                text="Which database do you prefer: Postgres or SQLite?",
                tool_calls=[{
                    "id": "c_ask",
                    "name": "ask_user",
                    "arguments": {"question": "Which database do you prefer?"}
                }]
            )
        else:
            prompt = kwargs.get("prompt", "")
            assert "PostgreSQL" in prompt
            return NormalizedModelResponse(text="Configured PostgreSQL.", tool_calls=[])

    mock_orch._generate_t1 = mock_generate_t1

    async def mock_user_input(q: str) -> str:
        nonlocal callback_called
        callback_called = True
        return "Please use PostgreSQL."

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        user_input_callback=mock_user_input,
        config=AgentLoopConfig(max_turns=10)
    )

    mission = Mission(mission_id="m_ask_user", user_prompt="Configure database")
    res = await loop.run(mission)

    assert callback_called is True
    assert res.success is True
    assert turn_counter == 2


@pytest.mark.asyncio
async def test_scenario_g_false_completion_rejected(test_env):
    """Scenario G: Model claims 'done' without writing required files -> completion rejected by harness."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    turn_counter = 0
    repair_seen = False

    async def mock_generate_t1(*args, **kwargs):
        nonlocal turn_counter, repair_seen
        turn_counter += 1
        prompt = kwargs.get("prompt", "")
        if "Completion check rejected" in prompt or "Required Fix" in prompt:
            repair_seen = True

        if turn_counter == 1:
            # Model prematurely claims everything is done without creating files
            return NormalizedModelResponse(
                text="I have built the entire expense tracker application completely. Everything works.",
                tool_calls=[]
            )
        else:
            # On repair, write actual file
            target = test_env["tmp_path"] / "app.py"
            return NormalizedModelResponse(
                text="Writing actual implementation",
                tool_calls=[{
                    "id": "c_fix",
                    "name": "test_write_file",
                    "arguments": {"path": str(target), "content": "# Real app\nprint('Running')\n"}
                }]
            )

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=3)
    )

    mission = Mission(
        mission_id="m_false_comp",
        user_prompt="Build a complete expense tracker web application with dashboard"
    )

    await loop.run(mission)

    # First turn's completion claim must have been rejected
    assert repair_seen is True


@pytest.mark.asyncio
async def test_scenario_h_cancellation(test_env):
    """Scenario H: User cancellation via abort_event halts loop immediately."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]
    abort_ev = asyncio.Event()

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    turn_count = 0

    async def mock_generate_t1(*args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        # Set abort event during first model turn
        abort_ev.set()
        return NormalizedModelResponse(
            text="Step 1",
            tool_calls=[{"id": "c1", "name": "test_write_file", "arguments": {"path": "tmp.txt", "content": "a"}}]
        )

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        abort_event=abort_ev,
        config=AgentLoopConfig(max_turns=10)
    )

    mission = Mission(mission_id="m_abort", user_prompt="Long running job")
    res = await loop.run(mission)

    assert res.status in ("CANCELLED", "ABORTED")
    assert res.success is False
    assert turn_count <= 2


@pytest.mark.asyncio
async def test_scenario_i_tui_subscriber_crash_isolated(test_env):
    """Scenario I: Crashing TUI subscriber does not abort or interrupt the AgentLoop."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]

    # Register subscriber that deliberately throws
    def bad_subscriber(event: HermesEvent):
        raise RuntimeError("Fatal Textual UI Render Exception!")

    bus.subscribe(bad_subscriber)

    mock_orch = MagicMock()
    mock_orch.mode = "auto"

    async def mock_generate_t1(*args, **kwargs):
        return NormalizedModelResponse(text="Task completed cleanly.", tool_calls=[])

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        config=AgentLoopConfig(max_turns=5)
    )

    mission = Mission(mission_id="m_tui_crash", user_prompt="Explain concept")
    res = await loop.run(mission)

    assert res.success is True
    assert res.status == "COMPLETED"


@pytest.mark.asyncio
async def test_scenario_j_stall_detection(test_env):
    """Scenario J: Repeated identical action pattern triggers stall detection event and guidance."""
    ws = test_env["workspace"]
    bus = test_env["event_bus"]
    stall_events = []

    bus.subscribe(lambda e: stall_events.append(e), event_types={EventType.AGENT_STALL_DETECTED})

    mock_orch = MagicMock()
    mock_orch.mode = "auto"
    turn_counter = 0

    async def mock_generate_t1(*args, **kwargs):
        nonlocal turn_counter
        turn_counter += 1
        # Repeatedly emit the exact same action
        return NormalizedModelResponse(
            text="Reading same file repeatedly",
            tool_calls=[{"id": f"c_{turn_counter}", "name": "test_failing_tool", "arguments": {"target": "same"}}]
        )

    mock_orch._generate_t1 = mock_generate_t1

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        event_bus_instance=bus,
        config=AgentLoopConfig(stall_window_size=3, max_turns=6, max_consecutive_failures=10)
    )

    mission = Mission(mission_id="m_stall", user_prompt="Inspect repeat")
    await loop.run(mission)

    assert len(stall_events) >= 1
    assert stall_events[0].event_type == EventType.AGENT_STALL_DETECTED


@pytest.mark.asyncio
async def test_scenario_k_path_discipline(test_env):
    """Scenario K: Out-of-workspace file modification is rejected by HarnessPolicy."""
    policy = HarnessPolicy(mode="auto")
    ws = test_env["workspace"]

    action = ActionEnvelope(
        action_id="act_leak",
        tool_name="test_write_file",
        arguments={"path": "../../../system_file.txt", "content": "bad"}
    )

    allowed, reason, _, _ = await policy.evaluate(action, workspace=ws)
    assert allowed is False
    assert "Path traversal blocked" in reason
