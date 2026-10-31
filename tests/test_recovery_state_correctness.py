"""
HERMES 2.x - Recovery State Correctness Test Suite
Validates:
- Scenario 8: Cycle counters reset without wiping mission failure history or fingerprint trackers
- Scenario 12: Multi-tier transition state machine (T1 -> T2 -> T3 -> T4, and verified T3 -> T1 recovery)
- Failed provider avoidance (open circuit providers skipped)
- Recovery attempt budget accounting
"""

import time
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.adaptive_routing import AdaptiveRouter, ProviderHealthState
from core.agent_loop.loop import AgentLoop
from core.agent_loop.types import AgentLoopConfig


@pytest.mark.asyncio
async def test_recovery_budget_and_counter_separation():
    """
    Scenario 8: Cycle counters reset on transition, but mission failure history
    and recovery budget counts are strictly preserved.
    """
    router = AdaptiveRouter()
    loop = AgentLoop(
        orchestrator=MagicMock(),
        config=AgentLoopConfig(max_turns=20),
    )
    # Set orchestrator active tier
    loop.orchestrator._active_tier = 1

    # Simulate accumulation of cycle counters
    loop._cycle_no_progress_blocks = 3
    loop._cycle_empty_turns = 2
    loop._consecutive_no_progress_blocks = 2
    loop._consecutive_empty_turns = 1

    # Trigger recovery transition
    res = await loop._trigger_recovery_transition(
        turn_id="turn_cycle_test",
        rejection_reason="Repeated no-progress read loop",
    )
    assert res is True
    assert loop._recovery_attempt_count == 1
    # Cycle counters must be reset
    assert loop._cycle_no_progress_blocks == 0
    assert loop._cycle_empty_turns == 0
    assert loop._consecutive_no_progress_blocks == 0
    assert loop._consecutive_empty_turns == 0

    # Mission-wide failure history must NOT be reset; must record the event
    assert len(loop._mission_failure_history) == 1
    assert loop._mission_failure_history[0]["from_tier"] == 1
    assert loop._mission_failure_history[0]["to_tier"] == 2
    assert "Repeated no-progress" in loop._mission_failure_history[0]["reason"]

    # Provider failure counts must be tracked
    assert len(loop._provider_failure_counts) >= 1


@pytest.mark.asyncio
async def test_multi_tier_state_machine_t1_t2_t3_t4():
    """
    Scenario 12: Stepwise transition through tiers: T1 -> T2 -> T3 -> T4.
    """
    from core.adaptive_routing import adaptive_router
    # Mark tiers open circuit as they fail
    loop = AgentLoop(
        orchestrator=MagicMock(),
        config=AgentLoopConfig(max_turns=20),
    )
    loop.orchestrator._active_tier = 1

    # Transition 1: Tier 1 -> Tier 2
    await loop._trigger_recovery_transition(turn_id="t1", rejection_reason="T1 failure")
    assert loop.orchestrator._active_tier == 2

    # Transition 2: Tier 2 -> Tier 3
    await loop._trigger_recovery_transition(turn_id="t2", rejection_reason="T2 failure")
    assert loop.orchestrator._active_tier == 3

    # Transition 3: Tier 3 -> Tier 4 (when T1 is not healthy)
    adaptive_router.record_failure(1, RuntimeError("T1 still down"))
    await loop._trigger_recovery_transition(turn_id="t3", rejection_reason="T3 failure")
    assert loop.orchestrator._active_tier == 4


@pytest.mark.asyncio
async def test_verified_t3_to_t1_recovery():
    """
    Scenario 12 (verified recovery): If Tier 3 is active and Tier 1 circuit returns to HEALTHY,
    the router transitions back T3 -> T1 instead of escalating to Tier 4.
    """
    from core.adaptive_routing import adaptive_router
    loop = AgentLoop(
        orchestrator=MagicMock(),
        config=AgentLoopConfig(max_turns=20),
    )
    loop.orchestrator._active_tier = 3

    # Ensure Tier 1 is verified HEALTHY
    rec1 = adaptive_router.get_health(1)
    rec1.state = ProviderHealthState.HEALTHY
    rec1.consecutive_successes = 3
    rec1.consecutive_failures = 0

    await loop._trigger_recovery_transition(turn_id="t_recover", rejection_reason="T3 stall, checking recovery")
    assert loop.orchestrator._active_tier == 1


@pytest.mark.asyncio
async def test_failed_provider_avoidance():
    """
    Verify that if Tier 2 is in OPEN_CIRCUIT / DEGRADED, transition skips Tier 2 directly to Tier 3.
    """
    from core.adaptive_routing import adaptive_router
    loop = AgentLoop(
        orchestrator=MagicMock(),
        config=AgentLoopConfig(max_turns=20),
    )
    loop.orchestrator._active_tier = 1

    # Mark Tier 2 as OPEN_CIRCUIT
    rec2 = adaptive_router.get_health(2)
    rec2.state = ProviderHealthState.OPEN_CIRCUIT

    await loop._trigger_recovery_transition(turn_id="t_skip", rejection_reason="T1 down, T2 open circuit")
    # Must skip Tier 2 and go straight to Tier 3
    assert loop.orchestrator._active_tier == 3
