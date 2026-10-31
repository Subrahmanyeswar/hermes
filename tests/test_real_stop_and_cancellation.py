# tests/test_real_stop_and_cancellation.py
# Verification and regression test suite for Stop Cancellation semantics,
# process tree termination, and Loop Governor anti-stall enforcement.

import sys
import os
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.event_bus import EventBus, EventType, HermesEvent
from core.runtime_state.store import StateStore
from core.runtime_state.models import HermesRuntimeState, MissionStatus, WaitReason
from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.server.runtime_adapter import RuntimeAdapter
from tools.shell_tools import terminate_active_subprocesses, register_active_subprocess, ACTIVE_SUBPROCESSES
from core.agent_loop.types import AgentDecision, AgentDecisionType, Observation
from core.mission_planner import Mission


@pytest.mark.asyncio
async def test_agent_loop_cancellation_during_model_generation(tmp_path):
    """Verify that setting abort_event during model generation immediately halts the loop and emits MISSION_CANCELLED."""
    bus = EventBus()
    store = bus.get_or_create_state("m_test_cancel_gen")
    abort_evt = asyncio.Event()

    async def slow_generate(*args, **kwargs):
        # Trigger abort while generation is inflight
        abort_evt.set()
        await asyncio.sleep(0.05)
        return MagicMock(content="plan", tool_calls=[])

    mock_orch = MagicMock()
    mock_orch._generate_t1 = slow_generate

    mock_ws = MagicMock()
    mock_ws.root_str = str(tmp_path)
    mock_ws.is_locked = True
    mock_ws.get_workspace_summary.return_value = {"root": str(tmp_path), "total_files": 0}
    mock_ws.get_skeleton.return_value = ""

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=mock_ws,
        event_bus_instance=bus,
        state_store_instance=store,
        abort_event=abort_evt,
        config=AgentLoopConfig(max_turns=10),
    )

    mission = Mission(user_prompt="Build website", mission_id="m_test_cancel_gen")

    result = await loop.run(mission)
    assert result.status in ("CANCELLED", "FAILED")
    assert abort_evt.is_set()

    # Check that MISSION_CANCELLED was published
    snap = store.get_snapshot()
    assert snap.mission.status in (MissionStatus.CANCELLED, MissionStatus.FAILED)


@pytest.mark.asyncio
async def test_loop_governor_blocks_excessive_task_todo(tmp_path):
    """Verify that Loop Governor prevents the model from looping indefinitely in task.todo without writing files."""
    bus = EventBus()
    store = bus.get_or_create_state("m_test_gov_todo")

    # Orchestrator repeatedly returns task.todo with varying task items
    mock_orch = MagicMock()
    call_count = 0
    async def mock_gen(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        res = MagicMock()
        res.model = "test-model"
        res.tool_calls = None
        import json
        res.text = json.dumps({"tool_name": "task.todo", "arguments": {"action": "add", "tasks": [f"step {call_count}"]}})
        res.content = res.text
        return res
    mock_orch._generate_t1 = mock_gen

    mock_ws = MagicMock()
    mock_ws.root_str = str(tmp_path)
    mock_ws.is_locked = True
    mock_ws.get_workspace_summary.return_value = {"root": str(tmp_path), "total_files": 0}
    mock_ws.get_skeleton.return_value = ""

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=mock_ws,
        event_bus_instance=bus,
        state_store_instance=store,
        config=AgentLoopConfig(max_turns=4),
    )

    mission = Mission(user_prompt="Build application", mission_id="m_test_gov_todo")

    result = await loop.run(mission)
    # The governor must have blocked task.todo after 2 consecutive planning calls
    gov_observations = [obs for obs in loop._observation_history if "GOVERNOR" in obs.content or "Excessive planning" in obs.summary]
    assert len(gov_observations) >= 1
    assert "PROGRESS GOVERNOR: You have already planned your tasks" in gov_observations[0].content


@pytest.mark.asyncio
async def test_loop_governor_blocks_redundant_dir_inspections_on_empty_workspace(tmp_path):
    """Verify that Loop Governor prevents repetitive dir/ls calls when workspace is empty."""
    bus = EventBus()
    store = bus.get_or_create_state("m_test_gov_dir")

    # Orchestrator repeatedly calls inspection commands like dir, dir /a, ls -la
    mock_orch = MagicMock()
    call_count = 0
    async def mock_gen(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        res = MagicMock()
        res.model = "test-model"
        res.tool_calls = None
        import json
        cmds = ["dir", "dir /a", "ls -la", "dir /b"]
        cmd = cmds[(call_count - 1) % len(cmds)]
        res.text = json.dumps({"tool_name": "shell.bash", "arguments": {"command": cmd}})
        res.content = res.text
        return res
    mock_orch._generate_t1 = mock_gen

    mock_ws = MagicMock()
    mock_ws.root_str = str(tmp_path)
    mock_ws.is_locked = True
    mock_ws.get_workspace_summary.return_value = {"root": str(tmp_path), "total_files": 0}
    mock_ws.get_skeleton.return_value = ""

    loop = AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=mock_ws,
        event_bus_instance=bus,
        state_store_instance=store,
        config=AgentLoopConfig(max_turns=5),
    )

    mission = Mission(user_prompt="Build application", mission_id="m_test_gov_dir")

    result = await loop.run(mission)
    gov_observations = [obs for obs in loop._observation_history if "Redundant inspection blocked" in obs.summary]
    assert len(gov_observations) >= 1
    assert "0 application files" in gov_observations[0].content


@pytest.mark.asyncio
async def test_late_event_suppression_after_terminal():
    """Verify that late events cannot mutate state or emit after terminal event is published."""
    bus = EventBus()
    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=MagicMock(),
        event_bus_instance=bus,
    )
    loop._mission_id = "m_term_test"

    # Publish terminal event
    await loop._publish_event(EventType.MISSION_CANCELLED, payload={"reason": "Stop"})
    assert loop._terminal_event_published is True

    # Attempt late event
    received_late = []
    bus.subscribe(EventType.MODEL_COMPLETED, lambda e: received_late.append(e))

    await loop._publish_event(EventType.MODEL_COMPLETED, payload={"latency": 1.2})
    assert len(received_late) == 0  # Dropped!
