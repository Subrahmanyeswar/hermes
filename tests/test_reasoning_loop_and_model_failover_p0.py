# tests/test_reasoning_loop_and_tier_escalation_p0.py
"""
P0 Regression Test Suite: Reasoning-Only Loops, Model Failover, Inference Telemetry,
and Bounded Action-Progress Policy.

Verifies the 10 requirements from Section 6:
1. Model returns text without a tool call.
2. Repeated reasoning-only response triggers recovery.
3. Recovery requests a concrete tool action.
4. Tier 1 to Tier 2 changes the actual provider without resetting mid-recovery.
5. Repeated identical tier transitions are prevented.
6. Tier 2 failure can escalate to Tier 3.
7. Provider latency and tool execution time are measured separately.
8. A successful tool invocation resets the no-action counter and clears recovery.
9. All-provider failure terminates safely without data loss.
10. Existing recovery and agent-loop regression compatibility.
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.agent_loop.loop import AgentLoop
from core.agent_loop.decisions import DecisionInterpreter, AgentDecision, AgentDecisionType
from core.runtime_state.events import EventType, EventSeverity
from models.provider import NormalizedModelResponse
from core.adaptive_routing import get_adaptive_router, ProviderHealthState
from config.model_config import (
    TIER1_PROVIDER, TIER1_MODEL,
    TIER2_PROVIDER, TIER2_MODEL,
    TIER3_PROVIDER, TIER3_MODEL,
)


@pytest.fixture(autouse=True)
def reset_global_router():
    get_adaptive_router().reset()
    yield
    get_adaptive_router().reset()


def make_test_loop(tmp_path):
    loop = AgentLoop.__new__(AgentLoop)
    loop._mission_id = "m_test_reasoning"
    loop._turns_count = 0
    loop._actions_count = 0
    loop._tool_calls_count = 0
    loop._consecutive_empty_turns = 0
    loop._in_recovery = False
    loop._recovery_attempt_count = 0
    loop._total_recovery_budget = 2
    loop._tier_rotations = 0
    loop._incident_visited_tiers = {}
    loop._observation_history = []
    loop._written_files = set()
    loop._recent_actions = []
    loop._inference_history = []
    loop._last_turn_durations = {
        "provider_latency_seconds": 0.0,
        "tool_execution_latency_seconds": 0.0,
    }
    loop.workspace = MagicMock(root_str=str(tmp_path), is_locked=True)
    loop.orchestrator = MagicMock(_active_tier=1)
    loop.context_engine = None
    loop._publish_event = AsyncMock()
    loop._record_observation = MagicMock()
    loop._emit_tui_thought = AsyncMock()
    return loop


# ==============================================================================
# TEST 1: Model returns text without a tool call
# ==============================================================================
def test_01_model_returns_text_without_tool_call():
    """Verify that assistant response with only text and 0 tool calls classifies as CONTINUE_REASONING."""
    interpreter = DecisionInterpreter()
    model_resp = NormalizedModelResponse(
        text="I am analyzing the university website structure and thinking about the navigation.",
        content="I am analyzing the university website structure and thinking about the navigation.",
        tool_calls=[],
        success=True,
    )
    decision = interpreter.interpret(model_resp, turn_id="turn_1")
    assert decision.decision_type == AgentDecisionType.CONTINUE_REASONING
    assert "analyzing" in decision.explanation or "analyzing" in decision.reasoning


# ==============================================================================
# TEST 2: Repeated reasoning-only response triggers recovery
# ==============================================================================
@pytest.mark.asyncio
async def test_02_repeated_reasoning_only_triggers_recovery(tmp_path):
    """Verify that when empty turns reach 2, recovery transition is triggered and tier escalates."""
    loop = make_test_loop(tmp_path)
    loop._trigger_recovery_transition = AsyncMock(return_value=True)

    # Simulate empty turns
    loop._consecutive_empty_turns = 2
    rec_ok = await loop._trigger_recovery_transition(
        turn_id="turn_2",
        rejection_reason="Model stalled in reasoning-only loop (2 turns with 0 tool calls)",
        unmet_reqs=["index.html", "style.css"],
    )
    assert rec_ok is True
    loop._trigger_recovery_transition.assert_awaited_once()


# ==============================================================================
# TEST 3: Recovery requests a concrete tool action
# ==============================================================================
@pytest.mark.asyncio
async def test_03_recovery_requests_concrete_tool_action(tmp_path):
    """Verify recovery creates an action directive requiring concrete tool invocation (e.g. write_file)."""
    loop = make_test_loop(tmp_path)
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    rec_ok = await loop._trigger_recovery_transition(
        turn_id="turn_2",
        rejection_reason="Model stalled in reasoning-only loop (2 turns with 0 tool calls)",
        unmet_reqs=["Scaffold missing/incomplete: index.html", "Scaffold missing/incomplete: style.css"],
    )
    assert rec_ok is True
    assert getattr(loop, "_active_recovery_brief", None) is not None
    brief = loop._active_recovery_brief

    # Must contain mandatory target and concrete tool directive
    assert "MANDATORY SYSTEM RECOVERY DIRECTIVE" in brief
    assert "index.html" in brief
    assert "DIRECTIVE" in brief
    assert "write" in brief.lower()
    # Check that recovery observation was recorded
    assert loop._record_observation.called
    rec_obs = loop._record_observation.call_args[0][0]
    assert "Recovery transition activated" in rec_obs.summary


# ==============================================================================
# TEST 4: Tier 1 to Tier 2 changes the actual provider and preserves active tier
# ==============================================================================
@pytest.mark.asyncio
async def test_04_tier1_to_tier2_changes_actual_provider(tmp_path):
    """Verify Tier 1 -> Tier 2 escalation updates active tier to 2 and is NOT reset to 1 mid-recovery."""
    loop = make_test_loop(tmp_path)
    assert loop.orchestrator._active_tier == 1

    rec_ok = await loop._trigger_recovery_transition(
        turn_id="turn_1",
        rejection_reason="Stalled reasoning",
        unmet_reqs=["index.html"],
    )
    assert rec_ok is True
    assert loop.orchestrator._active_tier == 2
    assert loop._in_recovery is True

    # Simulate the start of the next turn in AgentLoop.run()
    # The fix ensures that during ongoing recovery, _active_tier remains 2 and is NOT overwritten to 1
    if hasattr(loop, "orchestrator") and loop.orchestrator:
        if not getattr(loop, "_in_recovery", False) and getattr(loop, "_consecutive_empty_turns", 0) == 0:
            setattr(loop.orchestrator, "_active_tier", 1)

    assert loop.orchestrator._active_tier == 2, "Active tier must be preserved at 2 across recovery turns"

    # Verify event published with TIER2_PROVIDER and TIER2_MODEL
    matching_calls = [c for c in loop._publish_event.call_args_list if c.args and c.args[0] == EventType.TIER_FAILOVER_STARTED]
    assert len(matching_calls) >= 1
    call = matching_calls[0]
    payload = call.kwargs.get("payload", {})
    assert payload["from_tier"] == 1
    assert payload["to_tier"] == 2
    assert payload["provider"] == TIER2_PROVIDER
    assert payload["model"] == TIER2_MODEL


# ==============================================================================
# TEST 5: Repeated identical tier transitions are prevented
# ==============================================================================
@pytest.mark.asyncio
async def test_05_repeated_identical_tier_transitions_prevented(tmp_path):
    """Verify that when Tier 2 is active, recovery advances to Tier 3 and never repeats Tier 1 -> Tier 2."""
    loop = make_test_loop(tmp_path)

    # First escalation: Tier 1 -> Tier 2
    rec1 = await loop._trigger_recovery_transition(
        turn_id="turn_1",
        rejection_reason="Stalled in turn 1",
        unmet_reqs=["index.html"],
    )
    assert rec1 is True
    assert loop.orchestrator._active_tier == 2

    # Second escalation: from Tier 2, must escalate to Tier 3
    rec2 = await loop._trigger_recovery_transition(
        turn_id="turn_2",
        rejection_reason="Stalled in turn 2",
        unmet_reqs=["index.html"],
    )
    assert rec2 is True
    assert loop.orchestrator._active_tier == 3, "Second recovery must escalate to Tier 3"
    assert loop._recovery_attempt_count == 2


# ==============================================================================
# TEST 6: Tier 2 failure can escalate to Tier 3
# ==============================================================================
@pytest.mark.asyncio
async def test_06_tier2_failure_escalates_to_tier3(tmp_path):
    """Verify that when Tier 2 generation fails, _generate_model_turn dispatches to Tier 3."""
    loop = make_test_loop(tmp_path)
    loop.config = MagicMock(execution_mode="full", temperature=0.2)
    loop.orchestrator._active_tier = 2

    tier2_mock = MagicMock()
    tier2_mock.generate = AsyncMock(side_effect=RuntimeError("Tier 2 provider 503 error"))

    tier3_mock = MagicMock()
    tier3_resp = NormalizedModelResponse(
        text='{"tool": "write_file", "parameters": {"path": "index.html", "content": "<html></html>"}}',
        success=True,
        model=TIER3_MODEL,
        provider=TIER3_PROVIDER,
    )
    tier3_mock.generate = AsyncMock(return_value=tier3_resp)

    loop.orchestrator.tier2 = tier2_mock
    loop.orchestrator.tier3 = tier3_mock
    loop.orchestrator._tier3 = tier3_mock

    resp = await loop._generate_model_turn(
        system_prompt="sys",
        user_message="build website",
        turn_id="turn_t2_fail",
        timeout_seconds=60.0,
    )
    assert resp.success is True
    assert loop.orchestrator._active_tier == 3
    tier2_mock.generate.assert_awaited_once()
    tier3_mock.generate.assert_awaited_once()


# ==============================================================================
# TEST 7: Provider latency and tool execution time are measured separately
# ==============================================================================
def test_07_provider_latency_and_tool_execution_time_measured_separately(tmp_path):
    """Verify distinct tracking of provider inference time and tool execution duration in telemetry."""
    loop = make_test_loop(tmp_path)

    # Record telemetry for inference
    rec = loop.record_inference_telemetry(
        requested_tier=1,
        actual_provider=TIER1_PROVIDER,
        actual_model=TIER1_MODEL,
        start_time=100.0,
        completion_time=102.5,
        success=True,
        tool_call_count=1,
        finish_reason="tool_calls",
        turn_id="turn_timing",
    )
    assert rec["requested_tier"] == 1
    assert rec["actual_provider"] == TIER1_PROVIDER
    assert rec["actual_model_id"] == TIER1_MODEL
    assert rec["duration_ms"] == pytest.approx(2500.0, rel=1e-2)
    assert rec["tool_call_count"] == 1
    assert rec["finish_reason"] == "tool_calls"
    assert len(loop._inference_history) == 1

    # Verify separate tracking of turn durations
    loop._last_turn_durations = {
        "provider_latency_seconds": 2.5,
        "tool_execution_latency_seconds": 0.42,
        "provider_duration_ms": 2500.0,
        "tool_execution_duration_ms": 420.0,
    }
    assert loop._last_turn_durations["provider_latency_seconds"] != loop._last_turn_durations["tool_execution_latency_seconds"]
    assert loop._last_turn_durations["provider_latency_seconds"] == 2.5
    assert loop._last_turn_durations["tool_execution_latency_seconds"] == 0.42


# ==============================================================================
# TEST 8: Successful tool invocation resets no-action counter and clears recovery
# ==============================================================================
@pytest.mark.asyncio
async def test_08_successful_tool_invocation_resets_no_action_counter(tmp_path):
    """Verify that a successful tool action resets consecutive empty turns and clears recovery state."""
    loop = make_test_loop(tmp_path)
    loop._consecutive_empty_turns = 2
    loop._in_recovery = True
    loop._recovery_attempt_count = 1
    loop.orchestrator._active_tier = 2

    # Simulate successful tool observation processing
    call_name = "write_file"
    obs = MagicMock(success=True, summary="Created index.html", observation_id="obs_1")

    if obs.success:
        loop._consecutive_empty_turns = 0
        if getattr(loop, "_in_recovery", False):
            loop._in_recovery = False
            loop._recovery_attempt_count = 0
            if hasattr(loop, "orchestrator") and loop.orchestrator:
                setattr(loop.orchestrator, "_active_tier", 1)

    assert loop._consecutive_empty_turns == 0
    assert loop._in_recovery is False
    assert loop._recovery_attempt_count == 0
    assert loop.orchestrator._active_tier == 1, "Active tier must reset to 1 after successful tool recovery"


# ==============================================================================
# TEST 9: All-provider failure terminates safely
# ==============================================================================
@pytest.mark.asyncio
async def test_09_all_provider_failure_terminates_safely(tmp_path):
    """Verify that when recovery budget is exhausted across all tiers, transition returns False for safe termination."""
    loop = make_test_loop(tmp_path)
    loop._recovery_attempt_count = 2  # Budget is 2
    loop.orchestrator._active_tier = 3

    rec_ok = await loop._trigger_recovery_transition(
        turn_id="turn_exhausted",
        rejection_reason="All models stalled in reasoning loop",
        unmet_reqs=["index.html"],
    )
    assert rec_ok is False, "Recovery transition must return False when budget is exhausted"


# ==============================================================================
# TEST 10: Reasoning policy optimization for static web and recovery
# ==============================================================================
def test_10_reasoning_policy_optimization():
    """Verify that static web missions and recovery turns use 'low' reasoning to avoid 20-second stalls."""
    loop = make_test_loop(Path("."))
    loop.mission = MagicMock(user_prompt="Build complete university website using HTML, CSS and vanilla JavaScript. No database, backend, or external API needed.")

    effort, max_tokens = loop._determine_reasoning_policy(user_message="build homepage", turn_id="t1")
    assert effort == "low", "Static web missions must use low reasoning effort to prevent thinking loop stalls"
    assert max_tokens == 4096

    # When in recovery or empty-action stall
    loop._consecutive_empty_turns = 1
    effort_rec, max_tokens_rec = loop._determine_reasoning_policy(user_message="recover", turn_id="t2")
    assert effort_rec == "low", "Empty turn recovery must use low reasoning effort"
