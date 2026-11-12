"""
HERMES 2.x — Phase 3: Provider Failover State Machine Test Suite (P0.7)
Covers Scenarios 7, 8, 9, 10, 13:
  Test 7: Tier 1 returns HTTP 401 -> classified AUTHENTICATION_ERROR, permanent exclusion, no retries.
  Test 8: Tier 1 fails, Tier 2 succeeds -> operation succeeds without restoring Tier 1 in same operation.
  Test 9: Tier 1 & 2 fail, Tier 3 succeeds -> correct Tier 3 recovery.
  Test 10: All 3 tiers fail -> single bounded terminal failure (MultiTierRoutingExhaustedError), no infinite thinking.
  Test 13: Two missions execute independently -> no cross-mission state leakage.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.adaptive_routing import get_adaptive_router, ProviderHealthState
from core.orchestrator import Orchestrator, MultiTierRoutingExhaustedError
from core.runtime_failover import (
    ErrorClassification,
    classify_runtime_error,
    global_attempt_ledger,
    LogicalOperationBudget,
)
from models.common_adapter import NormalizedModelResponse


@pytest.fixture(autouse=True)
def clean_environment():
    """Ensure clean router and attempt ledger for every test."""
    router = get_adaptive_router()
    router.reset_state()
    if hasattr(router, "_mission_excluded_tiers"):
        router._mission_excluded_tiers.clear()
    global_attempt_ledger.clear_all()
    yield
    router.reset_state()
    if hasattr(router, "_mission_excluded_tiers"):
        router._mission_excluded_tiers.clear()
    global_attempt_ledger.clear_all()


@pytest.mark.asyncio
async def test_07_tier1_http_401_permanent_exclusion_no_retries():
    """Test 7: Tier 1 returns HTTP 401 -> classified AUTHENTICATION_ERROR, permanent exclusion, no retries."""
    orch = Orchestrator(mode="auto", project="test_p07_7")

    mock_t1 = AsyncMock()
    mock_t1.generate = AsyncMock(return_value=NormalizedModelResponse(
        text="",
        error="AUTH_ERROR: HTTP 401 invalid api key provided",
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        provider="nvidia_nim",
        success=False,
    ))
    orch.tier1 = mock_t1

    mock_t2 = AsyncMock()
    mock_t2.generate = AsyncMock(return_value=NormalizedModelResponse(
        text='{"tool": "browser_preview", "parameters": {}}',
        model="gemini-3.8-flash",
        provider="gemini",
        success=True,
    ))
    orch.ollama = mock_t2

    resp = await orch._generate_t1(
        prompt="Generate hero section",
        mission_id="m_auth_perm",
        turn_id="turn_1",
        timeout_seconds=20.0
    )

    assert resp.success is True
    # Exactly 1 attempt on Tier 1 (no retries for permanent authentication error)
    assert mock_t1.generate.call_count == 1
    assert mock_t2.generate.call_count == 1

    attempts = global_attempt_ledger.get_attempts_for_mission("m_auth_perm")
    assert len(attempts) == 2
    assert attempts[0].tier == 1
    assert attempts[0].success is False
    assert attempts[0].error_classification == ErrorClassification.AUTHENTICATION_ERROR.value
    assert attempts[1].tier == 2
    assert attempts[1].success is True

    # Tier 1 must be permanently excluded for this mission
    router = get_adaptive_router()
    assert router.is_tier_excluded_for_mission(1, "m_auth_perm") is True

    # Next turn in same mission must bypass Tier 1 completely!
    resp_turn2 = await orch._generate_t1(
        prompt="Generate navigation",
        mission_id="m_auth_perm",
        turn_id="turn_2",
        timeout_seconds=20.0
    )
    assert resp_turn2.success is True
    assert mock_t1.generate.call_count == 1  # Not called again!
    assert mock_t2.generate.call_count == 2


@pytest.mark.asyncio
async def test_08_tier1_fail_tier2_success_no_cycle_back():
    """Test 8: Tier 1 fails, Tier 2 succeeds -> operation succeeds without restoring Tier 1 in same operation."""
    orch = Orchestrator(mode="auto", project="test_p07_8")

    mock_t1 = AsyncMock()
    mock_t1.generate = AsyncMock(side_effect=RuntimeError("Transient upstream 502 bad gateway"))
    orch.tier1 = mock_t1

    mock_t2 = AsyncMock()
    mock_t2.generate = AsyncMock(return_value=NormalizedModelResponse(
        text='{"tool": "fs_write", "parameters": {"path": "index.html"}}',
        model="gemini-3.8-flash",
        provider="gemini",
        success=True,
    ))
    orch.ollama = mock_t2

    resp = await orch._generate_t1(
        prompt="Build landing page",
        mission_id="m_no_cycle",
        turn_id="turn_1",
        timeout_seconds=20.0
    )

    assert resp.success is True
    assert getattr(resp, "tier", 2) == 2
    assert orch._active_tier == 2
    assert mock_t1.generate.call_count == 1
    assert mock_t2.generate.call_count == 1

    # Tier 1 must remain excluded for this mission
    router = get_adaptive_router()
    assert router.is_tier_excluded_for_mission(1, "m_no_cycle") is True


@pytest.mark.asyncio
async def test_09_tier1_and_tier2_fail_tier3_recovers():
    """Test 9: Tier 1 & 2 fail, Tier 3 succeeds -> correct Tier 3 recovery with proper attribution."""
    orch = Orchestrator(mode="auto", project="test_p07_9")

    mock_t1 = AsyncMock()
    mock_t1.generate = AsyncMock(side_effect=RuntimeError("Tier 1 HTTP 503"))
    orch.tier1 = mock_t1

    mock_t2 = AsyncMock()
    mock_t2.generate = AsyncMock(side_effect=RuntimeError("Tier 2 HTTP 500"))
    orch.tier2 = mock_t2
    orch.ollama = mock_t2

    mock_t3 = AsyncMock()
    mock_t3.generate = AsyncMock(return_value=NormalizedModelResponse(
        text='{"tool": "fs_write", "parameters": {"path": "index.html"}}',
        model="qwen-2.5-coder-32b",
        provider="ollama",
        success=True,
    ))
    orch.tier3 = mock_t3

    with patch("config.model_config.TIER3_MODEL", "qwen-2.5-coder-32b"), \
         patch("config.model_config.TIER3_PROVIDER", "ollama"):
        resp = await orch._generate_t1(
            prompt="Build landing page",
            mission_id="m_t3_recovery",
            turn_id="turn_1",
            timeout_seconds=25.0
        )

    assert resp.success is True
    assert getattr(resp, "tier", 3) == 3
    assert orch._active_tier == 3
    assert mock_t1.generate.call_count == 1
    assert mock_t2.generate.call_count == 1
    assert mock_t3.generate.call_count == 1

    attempts = global_attempt_ledger.get_attempts_for_mission("m_t3_recovery")
    assert len(attempts) == 3
    assert attempts[0].tier == 1 and attempts[0].success is False
    assert attempts[1].tier == 2 and attempts[1].success is False
    assert attempts[2].tier == 3 and attempts[2].success is True


@pytest.mark.asyncio
async def test_10_all_tiers_fail_terminal_failure_no_infinite_thinking():
    """Test 10: All 3 tiers fail -> single bounded terminal failure (MultiTierRoutingExhaustedError), no infinite thinking."""
    orch = Orchestrator(mode="auto", project="test_p07_10")

    mock_t1 = AsyncMock()
    mock_t1.generate = AsyncMock(side_effect=RuntimeError("Tier 1 connection refused"))
    orch.tier1 = mock_t1

    mock_t2 = AsyncMock()
    mock_t2.generate = AsyncMock(side_effect=RuntimeError("Tier 2 rate limit exceeded"))
    orch.tier2 = mock_t2
    orch.ollama = mock_t2

    mock_t3 = AsyncMock()
    mock_t3.generate = AsyncMock(side_effect=RuntimeError("Tier 3 internal error"))
    orch.tier3 = mock_t3

    t0 = time.monotonic()
    with patch("config.model_config.TIER3_MODEL", "qwen-2.5-coder-32b"), \
         patch("config.model_config.TIER3_PROVIDER", "ollama"):
        with pytest.raises(MultiTierRoutingExhaustedError) as exc_info:
            await orch._generate_t1(
                prompt="Build landing page",
                mission_id="m_all_fail",
                turn_id="turn_1",
                timeout_seconds=25.0
            )
    elapsed = time.monotonic() - t0

    assert "All configured model tiers failed" in str(exc_info.value)
    # Bounded termination: stopped immediately after trying all tiers without hanging
    assert elapsed < 5.0

    attempts = global_attempt_ledger.get_attempts_for_mission("m_all_fail")
    assert len(attempts) == 3
    assert all(not a.success for a in attempts)


@pytest.mark.asyncio
async def test_13_mission_isolation_no_cross_mission_leakage():
    """Test 13: Two missions execute independently -> no cross-mission state leakage."""
    orch = Orchestrator(mode="auto", project="test_p07_13")
    router = get_adaptive_router()

    # Mission A: Tier 1 fails, so Tier 1 is excluded for Mission A
    router.exclude_tier_for_mission(1, "mission_alpha", permanent=False, reason="Mission A failover")
    assert router.is_tier_excluded_for_mission(1, "mission_alpha") is True

    # Mission B: Should NOT inherit Mission A's exclusion
    assert router.is_tier_excluded_for_mission(1, "mission_beta") is False

    # Route decision for Mission A routes to Tier 2 (bypassed)
    decision_a = router.route_primary(mission_id="mission_alpha")
    assert decision_a.tier == 2
    assert decision_a.bypassed is True

    # Route decision for Mission B routes directly to Tier 1
    decision_b = router.route_primary(mission_id="mission_beta")
    assert decision_b.tier == 1
    assert decision_b.bypassed is False
