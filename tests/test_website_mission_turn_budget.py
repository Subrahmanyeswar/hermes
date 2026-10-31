# tests/test_website_mission_turn_budget.py
"""
Regression tests verifying the 80-turn budget configuration for complex website missions,
preservation of the default 40-turn budget for unrelated missions, and strict enforcement
of progress guards, deadline supervision, and explicit overrides.
"""

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_loop.loop import AgentLoop
from core.agent_loop.mvp_gate import WebsiteMvpGate
from core.agent_loop.types import AgentLoopConfig, AgentDecision, AgentDecisionType
from core.event_bus import EventBus, EventType
from core.mission_planner import Mission
from core.workspace import WorkspaceManager
from models.provider import NormalizedModelResponse
from config.model_config import DEFAULT_MISSION_MAX_TURNS, WEBSITE_MISSION_MAX_TURNS


@pytest.fixture
def test_env():
    """Isolated environment with temporary workspace and event bus."""
    temp_dir = tempfile.mkdtemp(prefix="hermes_turn_budget_test_")
    ws_path = Path(temp_dir)
    bus = EventBus()
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(ws_path))

    yield {
        "workspace_path": ws_path,
        "workspace_manager": ws_mgr,
        "event_bus": bus,
    }

    ws_mgr.unlock()
    shutil.rmtree(temp_dir, ignore_errors=True)


def _create_mock_orchestrator_pondering():
    """Create a mock orchestrator that returns harmless non-completing reasoning."""
    mock_orch = MagicMock()
    mock_orch.mode = "auto"

    async def mock_gen(*args, **kwargs):
        return NormalizedModelResponse(
            text="Iterating simulation step...",
            tool_calls=[],
            success=True,
        )

    mock_orch._generate_t1 = mock_gen
    return mock_orch


# ── Test 1: Complex website mission receives 80-turn ceiling ───────────────────
@pytest.mark.asyncio
async def test_complex_website_mission_receives_80_turn_ceiling(test_env):
    """
    Verify that a complex website-building mission (e.g. Three.js cinematic LVM3 rocket simulation)
    receives an 80-turn ceiling by default in the production agent loop.
    """
    ws_path = test_env["workspace_path"]
    ws_mgr = test_env["workspace_manager"]
    bus = test_env["event_bus"]

    mission_id = "m_lvm3_cinematic_website"
    prompt = "Build a complex cinematic LVM3 rocket simulation website with Three.js multi-file architecture"
    mission = Mission(mission_id=mission_id, user_prompt=prompt, workspace_root=str(ws_path))

    # Production loop instantiation (default AgentLoopConfig with no manual max_turns)
    config = AgentLoopConfig()
    assert config.max_turns == DEFAULT_MISSION_MAX_TURNS  # Initial default 40
    assert config.website_max_turns == 80

    loop = AgentLoop(
        orchestrator=_create_mock_orchestrator_pondering(),
        workspace_manager=ws_mgr,
        event_bus_instance=bus,
        config=config,
    )

    # Mock interpreter to keep reasoning until turn limit
    def mock_interpret(*args, **kwargs):
        text = kwargs.get("text", "") or (args[0].text if args and hasattr(args[0], "text") else "deliberating")
        return AgentDecision(
            decision_type=AgentDecisionType.CONTINUE_REASONING,
            explanation=str(text),
            raw_text=str(text),
        )
    loop._interpreter.interpret = mock_interpret

    # Fast-forward turns count to verify it does not stop at turn 40, but stops at turn 80
    turn_counter = 0

    async def counted_model_turn(*args, **kwargs):
        nonlocal turn_counter
        turn_counter += 1
        # Once we verify it runs past 40, simulate advancing to test the exact 80 ceiling
        if loop._turns_count == 42:
            loop._turns_count = 79
        return NormalizedModelResponse(text="Deliberating...", tool_calls=[], success=True)

    loop._generate_model_turn = counted_model_turn

    result = await loop.run(mission)

    # Must have resolved to 80 turns
    assert loop.config.max_turns == 80
    assert result.success is False
    assert result.status == "FAILED"
    assert "Max turn budget reached (80/80)" in (result.error or "")
    assert "Max turn budget reached (80/80)" in (result.termination_reason or "")


# ── Test 2: Unrelated mission retains default 40-turn ceiling ───────────────────
@pytest.mark.asyncio
async def test_unrelated_mission_retains_default_40_turn_ceiling(test_env):
    """
    Verify that an unrelated non-website mission retains the standard 40-turn ceiling.
    """
    ws_path = test_env["workspace_path"]
    ws_mgr = test_env["workspace_manager"]
    bus = test_env["event_bus"]

    mission_id = "m_python_cli_pipeline"
    prompt = "Create a python CLI data processor for CSV files and generate summary statistics"
    mission = Mission(mission_id=mission_id, user_prompt=prompt, workspace_root=str(ws_path))

    config = AgentLoopConfig()
    loop = AgentLoop(
        orchestrator=_create_mock_orchestrator_pondering(),
        workspace_manager=ws_mgr,
        event_bus_instance=bus,
        config=config,
    )

    def mock_interpret(*args, **kwargs):
        text = kwargs.get("text", "") or (args[0].text if args and hasattr(args[0], "text") else "deliberating")
        return AgentDecision(
            decision_type=AgentDecisionType.CONTINUE_REASONING,
            explanation=str(text),
            raw_text=str(text),
        )
    loop._interpreter.interpret = mock_interpret

    async def counted_model_turn(*args, **kwargs):
        if loop._turns_count == 20:
            loop._turns_count = 39
        return NormalizedModelResponse(text="Processing...", tool_calls=[], success=True)

    loop._generate_model_turn = counted_model_turn

    result = await loop.run(mission)

    # Must retain 40 turns
    assert loop.config.max_turns == 40
    assert result.success is False
    assert result.status == "FAILED"
    assert "Max turn budget reached (40/40)" in (result.error or "")
    assert "Max turn budget reached (40/40)" in (result.termination_reason or "")


# ── Test 3: Explicit turn budget override is strictly preserved ────────────────
@pytest.mark.asyncio
async def test_explicit_turn_budget_override_preserved(test_env):
    """
    Verify that if a caller explicitly configures max_turns (e.g. max_turns=15),
    it is preserved even if the mission prompt describes a complex website.
    """
    ws_path = test_env["workspace_path"]
    ws_mgr = test_env["workspace_manager"]
    bus = test_env["event_bus"]

    mission_id = "m_explicit_override"
    prompt = "Build a Three.js rocket simulation website with canvas and webgl"
    mission = Mission(mission_id=mission_id, user_prompt=prompt, workspace_root=str(ws_path))

    # Explicit override to 15 turns
    config = AgentLoopConfig(max_turns=15)
    loop = AgentLoop(
        orchestrator=_create_mock_orchestrator_pondering(),
        workspace_manager=ws_mgr,
        event_bus_instance=bus,
        config=config,
    )

    def mock_interpret(*args, **kwargs):
        text = kwargs.get("text", "") or (args[0].text if args and hasattr(args[0], "text") else "deliberating")
        return AgentDecision(
            decision_type=AgentDecisionType.CONTINUE_REASONING,
            explanation=str(text),
            raw_text=str(text),
        )
    loop._interpreter.interpret = mock_interpret

    async def counted_model_turn(*args, **kwargs):
        if loop._turns_count == 5:
            loop._turns_count = 14
        return NormalizedModelResponse(text="Deliberating...", tool_calls=[], success=True)

    loop._generate_model_turn = counted_model_turn

    result = await loop.run(mission)

    assert loop.config.max_turns == 15
    assert "Max turn budget reached (15/15)" in (result.error or "")


# ── Test 4: Hard no-progress termination occurs well before 80 turns ───────────
@pytest.mark.asyncio
async def test_no_progress_termination_occurs_before_ceiling(test_env):
    """
    Verify that an 80-turn budget does not permit an unprogressing inspection or read loop
    to continue indefinitely. Hard no-progress guard must terminate the mission.
    """
    ws_path = test_env["workspace_path"]
    ws_mgr = test_env["workspace_manager"]
    bus = test_env["event_bus"]

    mission_id = "m_no_progress_termination"
    prompt = "Build cinematic Three.js LVM3 rocket simulation website"
    mission = Mission(mission_id=mission_id, user_prompt=prompt, workspace_root=str(ws_path))

    # Create an unchanging file in workspace
    static_file = ws_path / "existing_doc.txt"
    static_file.write_text("fixed static content", encoding="utf-8")

    config = AgentLoopConfig()
    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws_mgr,
        event_bus_instance=bus,
        config=config,
    )

    # Orchestrator repeatedly issues identical fs.read on the unchanged file
    call_idx = 0
    async def mock_read_loop(*args, **kwargs):
        nonlocal call_idx
        call_idx += 1
        return NormalizedModelResponse(
            text="Reading file again...",
            tool_calls=[{
                "id": f"call_read_{call_idx}",
                "name": "fs.read",
                "arguments": {"path": "existing_doc.txt"},
            }],
            success=True,
        )

    loop._generate_model_turn = mock_read_loop

    result = await loop.run(mission)

    # Budget was resolved to 80
    assert loop.config.website_max_turns == 80
    # But termination MUST happen way before 80 turns due to no-progress guard
    assert result.success is False
    assert result.status == "FAILED"
    assert result.turns_executed < 10
    assert "AGENT_NO_PROGRESS" in (result.termination_reason or "") or "no-progress" in (result.error or "").lower()


# ── Test 5: Deadline supervision strictly terminates before 80 turns ──────────
@pytest.mark.asyncio
async def test_deadline_supervision_terminates_before_ceiling(test_env):
    """
    Verify that the 80-turn budget never overrides wall-clock limits and verification reserve.
    If wall time budget is exhausted, termination occurs immediately.
    """
    ws_path = test_env["workspace_path"]
    ws_mgr = test_env["workspace_manager"]
    bus = test_env["event_bus"]

    mission_id = "m_deadline_test"
    prompt = "Build cinematic Three.js LVM3 rocket simulation website"
    mission = Mission(mission_id=mission_id, user_prompt=prompt, workspace_root=str(ws_path))

    # Give a tiny wall time of 5 seconds (insufficient for 25s reserve)
    config = AgentLoopConfig(max_wall_time_seconds=5.0)
    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws_mgr,
        event_bus_instance=bus,
        config=config,
    )

    result = await loop.run(mission)

    assert result.success is False
    assert result.status == "FAILED"
    assert result.turns_executed == 0
    assert "Insufficient remaining wall time budget" in (result.error or "")


# ── Test 6: Deliverable creation dynamically upgrades turn budget ──────────────
@pytest.mark.asyncio
async def test_deliverable_creation_dynamically_upgrades_budget(test_env):
    """
    Verify that if a mission begins with a generic prompt but writes website deliverables
    (such as index.html), the loop dynamically upgrades the budget to 80 turns.
    """
    ws_path = test_env["workspace_path"]
    ws_mgr = test_env["workspace_manager"]
    bus = test_env["event_bus"]

    mission_id = "m_dynamic_upgrade"
    # Generic prompt that does not immediately match web cues
    prompt = "Initialize project deliverables and set up core structure"
    mission = Mission(mission_id=mission_id, user_prompt=prompt, workspace_root=str(ws_path))

    config = AgentLoopConfig()
    loop = AgentLoop(
        orchestrator=MagicMock(),
        workspace_manager=ws_mgr,
        event_bus_instance=bus,
        config=config,
    )

    # Initially before website cues, it resolves to 40
    loop.config.resolve_for_mission(mission, workspace_root=ws_path)
    assert loop.config.max_turns == 40

    # Simulate creating index.html deliverable
    (ws_path / "index.html").write_text("<html><head><script src='main.js'></script></head><body></body></html>", encoding="utf-8")
    loop.config.resolve_for_mission(mission, workspace_root=ws_path, written_files={"index.html"})
    assert loop.config.max_turns == 80
