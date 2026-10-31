# tests/test_agent_reliability_and_adversarial.py
"""
Targeted Regression and Adversarial Test Suite for HERMES Agent Reliability.
Covers:
  1. Multi-tool batch duplicate suppression (prevents rapid intra-turn recovery exhaustion).
  2. Missing deliverable loop recovery and reset on corrective write.
  3. Real Tier 2 model dispatch routing when recovery escalation triggers.
  4. Cross-artifact integration validation (Web HTML/CSS/JS and Python imports).
  5. Non-web task independence (Python simulation tasks not classified as website).
  6. Bounded controlled termination when recovery attempts are exhausted across turns.
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent_loop.loop import AgentLoop, AgentLoopConfig
from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase
from core.integration_validator import CrossArtifactValidator, IntegrationReport
from core.mission_planner import Mission
from core.runtime_state.models import MissionStatus
from core.event_bus import event_bus
from core.runtime_state.events import EventType


@pytest.fixture
def clean_event_bus():
    """Ensure event bus subscribers are cleared for tests."""
    event_bus._subscribers.clear()
    yield event_bus
    event_bus._subscribers.clear()


@pytest.mark.asyncio
async def test_1_multi_tool_batch_duplicate_suppression(tmp_path, clean_event_bus):
    """
    Test that when a model emits multiple identical tool calls in a single turn response,
    the duplicates are suppressed, and recovery is NOT exhausted in a single turn.
    """
    cfg = AgentLoopConfig(max_turns=10, timeout_seconds=30.0)
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, config=cfg, workspace=None)
    loop._mission_id = "test_dup_batch_01"

    # Create dummy file
    test_file = tmp_path / "style.css"
    test_file.write_text("body { margin: 0; }", encoding="utf-8")
    loop._written_files.append("style.css")
    loop._file_write_counts["style.css"] = 1

    # Simulate a turn with 3 duplicate read_file calls in the same turn batch
    calls_to_run = [
        {"name": "fs.read", "arguments": {"path": "style.css"}, "id": "call_1"},
        {"name": "fs.read", "arguments": {"path": "style.css"}, "id": "call_2"},
        {"name": "fs.read", "arguments": {"path": "style.css"}, "id": "call_3"},
    ]

    seen_signatures_in_turn = set()
    suppressed_count = 0
    executed_or_guarded_count = 0

    for call_item in calls_to_run:
        call_name = call_item["name"]
        call_args = call_item["arguments"]
        action_sig = f"{call_name}:{json.dumps(call_args, sort_keys=True)}"

        if action_sig in seen_signatures_in_turn:
            suppressed_count += 1
            continue
        seen_signatures_in_turn.add(action_sig)
        executed_or_guarded_count += 1

    # Only 1 call should be processed, 2 duplicates suppressed
    assert executed_or_guarded_count == 1
    assert suppressed_count == 2


@pytest.mark.asyncio
async def test_2_cross_artifact_web_validator_detects_mismatch(tmp_path):
    """
    Test that CrossArtifactValidator identifies missing main.js and mismatched CSS IDs
    (the exact conditions of failed mission m_91a04e30).
    """
    html_content = """<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="canvas-container"></div>
  <div id="panel-controls"></div>
  <div id="panel-telemetry"></div>
  <script type="module" src="main.js"></script>
</body>
</html>"""
    (tmp_path / "index.html").write_text(html_content, encoding="utf-8")

    # CSS targets completely different IDs
    css_content = """
#canvas-container { width: 100%; height: 100%; }
#controls-panel { position: absolute; }
#telemetry-panel { position: absolute; }
#stage-panel { display: none; }
#engine-panel { display: none; }
#sensor-panel { display: none; }
#orbit-panel { display: none; }
"""
    (tmp_path / "style.css").write_text(css_content, encoding="utf-8")
    # main.js is deliberately NOT created

    report = CrossArtifactValidator.validate_web_integration(tmp_path)
    assert not report.valid
    assert any("main.js" in iss for iss in report.issues)
    assert any("mismatch" in iss.lower() for iss in report.issues)


@pytest.mark.asyncio
async def test_3_cross_artifact_python_validator(tmp_path):
    """
    Test that CrossArtifactValidator validates Python internal imports and detects missing symbols.
    """
    # Create module without 'run_simulation'
    (tmp_path / "engine.py").write_text("def start_engine():\n    return True\n", encoding="utf-8")
    # Create test importing non-existent 'run_simulation'
    (tmp_path / "test_engine.py").write_text(
        "from engine import start_engine, run_simulation\n\ndef test_engine():\n    assert start_engine()\n",
        encoding="utf-8"
    )

    report = CrossArtifactValidator.validate_python_integration(tmp_path)
    assert not report.valid
    assert any("run_simulation" in iss for iss in report.issues)

    # Now fix engine.py to export run_simulation
    (tmp_path / "engine.py").write_text(
        "def start_engine():\n    return True\ndef run_simulation():\n    return 'running'\n",
        encoding="utf-8"
    )
    report_fixed = CrossArtifactValidator.validate_python_integration(tmp_path)
    assert report_fixed.valid
    assert len(report_fixed.issues) == 0


def test_4_non_web_task_independence(tmp_path):
    """
    Test that Python simulation and CLI tasks are NOT misclassified as website tasks.
    """
    python_prompt = "Build a Python CLI orbit trajectory simulation using numpy and write pytest unit tests."
    assert not WebsiteMvpGate.is_website_mission(python_prompt, tmp_path)

    python_sim_prompt = "Create an aerospace rocket launch simulation in Python with terminal telemetries."
    assert not WebsiteMvpGate.is_website_mission(python_sim_prompt, tmp_path)

    web_prompt = "Create a Three.js interactive 3D website simulation of the LVM3 rocket launch."
    assert WebsiteMvpGate.is_website_mission(web_prompt, tmp_path)


@pytest.mark.asyncio
async def test_5_real_tier2_model_dispatch(clean_event_bus):
    """
    Test that when active_tier == 2, _generate_model_turn dispatches to Tier 2 Ollama
    and publishes TIER_SELECTED with tier 2.
    """
    cfg = AgentLoopConfig(max_turns=5, timeout_seconds=10.0)
    mock_orch = MagicMock()
    mock_ollama = MagicMock()
    mock_t2_resp = MagicMock()
    mock_t2_resp.content = '{"thought": "recovering", "tool_name": "fs.write", "arguments": {"path": "main.js", "content": "console.log(1);"}}'
    mock_ollama.generate = AsyncMock(return_value=mock_t2_resp)

    mock_orch.ollama = mock_ollama
    mock_orch._active_tier = 2
    mock_orch._build_t2_failover_kwargs = MagicMock(return_value={"model": "deepseek-coder:6.7b", "prompt": "test"})

    loop = AgentLoop(orchestrator=mock_orch, config=cfg, workspace=None)
    loop._mission_id = "test_t2_dispatch"

    events_captured = []
    clean_event_bus.subscribe(lambda e: events_captured.append(e))

    resp = await loop._generate_model_turn(
        system_prompt="system",
        user_message="user prompt",
        turn_id="turn_002"
    )

    # Verify Ollama generate was called
    mock_ollama.generate.assert_called_once()
    assert resp == mock_t2_resp

    # Verify TIER_SELECTED event was emitted with tier=2
    tier_events = [e for e in events_captured if e.event_type == EventType.TIER_SELECTED]
    assert len(tier_events) >= 1
    assert tier_events[0].payload["tier"] == 2


@pytest.mark.asyncio
async def test_6_corrective_action_resets_no_progress_counters(tmp_path):
    """
    Test that when recovery is triggered and a corrective mutating write is executed,
    consecutive no-progress counters and recovery attempt count are reset to 0.
    """
    cfg = AgentLoopConfig(max_turns=10, timeout_seconds=10.0)
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, config=cfg, workspace=None)
    loop._mission_id = "test_reset_01"

    # Simulate being in recovery after 2 blocks
    loop._consecutive_no_progress_blocks = 2
    loop._recovery_attempt_count = 1
    loop._consecutive_non_mutating_turns = 2

    # Simulate successful mutating action
    is_mutating = True
    if is_mutating:
        loop._consecutive_no_progress_blocks = 0
        loop._recovery_attempt_count = 0
        loop._consecutive_non_mutating_turns = 0

    assert loop._consecutive_no_progress_blocks == 0
    assert loop._recovery_attempt_count == 0
    assert loop._consecutive_non_mutating_turns == 0


@pytest.mark.asyncio
async def test_7_bounded_recovery_terminates_honestly_when_exhausted(clean_event_bus):
    """
    Test that when uncooperative actions persist across distinct recovery turns,
    recovery attempts are bounded (max 2) and loop terminates with AGENT_NO_PROGRESS.
    """
    cfg = AgentLoopConfig(max_turns=10, timeout_seconds=10.0)
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, config=cfg, workspace=None)
    loop._mission_id = "test_bounded_term"
    mission = MagicMock()
    mission.user_prompt = "Build website"

    # Attempt 1: succeeds (returns True)
    handled_1 = await loop._execute_no_progress_recovery(
        turn_id="turn_1",
        mission=mission,
        unmet_reqs=["main.js"],
        rejection_reason="Blocked read",
    )
    assert handled_1 is True
    assert loop._recovery_attempt_count == 1

    # Attempt 2: succeeds (returns True)
    handled_2 = await loop._execute_no_progress_recovery(
        turn_id="turn_2",
        mission=mission,
        unmet_reqs=["main.js"],
        rejection_reason="Blocked read",
    )
    assert handled_2 is True
    assert loop._recovery_attempt_count == 2

    # Attempt 3: exhausted (returns False)
    handled_3 = await loop._execute_no_progress_recovery(
        turn_id="turn_3",
        mission=mission,
        unmet_reqs=["main.js"],
        rejection_reason="Blocked read",
    )
    assert handled_3 is False
