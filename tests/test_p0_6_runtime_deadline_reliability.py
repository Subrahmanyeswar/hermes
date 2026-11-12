"""
HERMES 2.x — Phase 3: Runtime Deadline Reliability Test Suite (P0.6)
Covers Scenarios 1 to 6:
  Test 1: Tier 1 returns successfully -> no unnecessary fallback.
  Test 2: Tier 1 hangs beyond attempt deadline -> request cancelled, Tier 2 attempted, no repeat Tier 1.
  Test 3: Tier 1 returns empty response -> classified EMPTY_RESPONSE, immediate failover.
  Test 4: Tier 1 returns HTTP 503 -> classified HTTP_503_UNAVAILABLE, bounded failover.
  Test 5: Tier 1 returns HTTP 504 -> classified HTTP_504_GATEWAY_TIMEOUT, bounded failover.
  Test 6: Tier 1 returns HTTP 429 with large Retry-After -> skips wait, immediate failover.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.adaptive_routing import get_adaptive_router, ProviderHealthState
from core.orchestrator import Orchestrator
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
async def test_01_tier1_success_no_fallback():
    """Test 1: Tier 1 returns successfully -> no unnecessary fallback to Tier 2 or Tier 3."""
    orch = Orchestrator(mode="auto", project="test_p06_1")
    
    mock_t1 = AsyncMock()
    mock_t1.generate = AsyncMock(return_value=NormalizedModelResponse(
        text='{"tool": "browser_preview", "parameters": {}}',
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        provider="nvidia_nim",
        success=True,
    ))
    orch.tier1 = mock_t1

    mock_t2 = AsyncMock()
    orch.ollama = mock_t2

    resp = await orch._generate_t1(prompt="Generate hero section", mission_id="m_t1_success", turn_id="turn_1")

    assert resp.success is True
    assert mock_t1.generate.call_count == 1
    assert mock_t2.generate.call_count == 0

    # Ledger audit verification
    attempts = global_attempt_ledger.get_attempts_for_mission("m_t1_success")
    assert len(attempts) == 1
    assert attempts[0].tier == 1
    assert attempts[0].success is True


@pytest.mark.asyncio
async def test_02_tier1_hang_attempt_deadline_failover_to_tier2():
    """Test 2: Tier 1 hangs beyond attempt deadline -> request cancelled, Tier 2 attempted, no repeat Tier 1."""
    orch = Orchestrator(mode="auto", project="test_p06_2")

    async def hanging_t1(**kwargs):
        # Hang longer than attempt timeout
        await asyncio.sleep(15.0)
        return NormalizedModelResponse(text="late response", success=True)

    mock_t1 = AsyncMock()
    mock_t1.generate = AsyncMock(side_effect=hanging_t1)
    orch.tier1 = mock_t1

    mock_t2 = AsyncMock()
    mock_t2.generate = AsyncMock(return_value=NormalizedModelResponse(
        text='{"tool": "browser_preview", "parameters": {}}',
        model="gemini-3.8-flash",
        provider="gemini",
        success=True,
    ))
    orch.ollama = mock_t2

    t0 = time.monotonic()
    resp = await orch._generate_t1(
        prompt="Generate hero section",
        mission_id="m_t1_hang",
        turn_id="turn_1",
        timeout_seconds=25.0
    )
    duration = time.monotonic() - t0

    assert resp.success is True
    assert mock_t1.generate.call_count == 1
    assert mock_t2.generate.call_count == 1
    # Bounded execution: Tier 1 was capped around 10.0s, leaving ample time for Tier 2
    assert duration < 14.0

    # Verify attempt ledger
    attempts = global_attempt_ledger.get_attempts_for_mission("m_t1_hang")
    assert len(attempts) == 2
    assert attempts[0].tier == 1
    assert attempts[0].success is False
    assert attempts[0].error_classification in (ErrorClassification.ATTEMPT_TIMEOUT.value, "ATTEMPT_TIMEOUT")
    assert attempts[1].tier == 2
    assert attempts[1].success is True

    # Tier 1 must be excluded for this mission to prevent restoration loops
    router = get_adaptive_router()
    assert router.is_tier_excluded_for_mission(1, "m_t1_hang") is True


@pytest.mark.asyncio
async def test_03_tier1_empty_response_immediate_failover():
    """Test 3: Tier 1 returns empty response -> classified EMPTY_RESPONSE, immediate failover to Tier 2."""
    orch = Orchestrator(mode="auto", project="test_p06_3")

    mock_t1 = AsyncMock()
    # Empty content and no tool calls
    mock_t1.generate = AsyncMock(return_value=NormalizedModelResponse(
        text="   ",
        tool_calls=[],
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        provider="nvidia_nim",
        success=True,
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
        mission_id="m_empty_resp",
        turn_id="turn_1",
        timeout_seconds=20.0
    )

    assert resp.success is True
    assert mock_t1.generate.call_count == 1
    assert mock_t2.generate.call_count == 1

    attempts = global_attempt_ledger.get_attempts_for_mission("m_empty_resp")
    assert len(attempts) == 2
    assert attempts[0].tier == 1
    assert attempts[0].success is False
    assert attempts[0].error_classification == ErrorClassification.EMPTY_RESPONSE.value
    assert attempts[1].tier == 2
    assert attempts[1].success is True


@pytest.mark.asyncio
async def test_04_tier1_http_503_unavailable_failover():
    """Test 4: Tier 1 returns HTTP 503 -> classified HTTP_503_UNAVAILABLE, bounded failover to Tier 2."""
    orch = Orchestrator(mode="auto", project="test_p06_4")

    mock_t1 = AsyncMock()
    mock_t1.generate = AsyncMock(return_value=NormalizedModelResponse(
        text="",
        error="SERVICE_UNAVAILABLE: HTTP 503 Backend server temporarily unavailable",
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
        mission_id="m_503_test",
        turn_id="turn_1",
        timeout_seconds=20.0
    )

    assert resp.success is True
    assert mock_t1.generate.call_count == 1
    assert mock_t2.generate.call_count == 1

    attempts = global_attempt_ledger.get_attempts_for_mission("m_503_test")
    assert len(attempts) == 2
    assert attempts[0].tier == 1
    assert attempts[0].success is False
    assert attempts[0].error_classification == ErrorClassification.HTTP_503_UNAVAILABLE.value
    assert attempts[1].tier == 2
    assert attempts[1].success is True


@pytest.mark.asyncio
async def test_05_tier1_http_504_gateway_timeout_failover():
    """Test 5: Tier 1 returns HTTP 504 -> classified HTTP_504_GATEWAY_TIMEOUT, bounded failover to Tier 2."""
    orch = Orchestrator(mode="auto", project="test_p06_5")

    mock_t1 = AsyncMock()
    mock_t1.generate = AsyncMock(return_value=NormalizedModelResponse(
        text="",
        error="GATEWAY_TIMEOUT: HTTP 504 upstream gateway timed out",
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
        mission_id="m_504_test",
        turn_id="turn_1",
        timeout_seconds=20.0
    )

    assert resp.success is True
    assert mock_t1.generate.call_count == 1
    assert mock_t2.generate.call_count == 1

    attempts = global_attempt_ledger.get_attempts_for_mission("m_504_test")
    assert len(attempts) == 2
    assert attempts[0].tier == 1
    assert attempts[0].success is False
    assert attempts[0].error_classification == ErrorClassification.HTTP_504_GATEWAY_TIMEOUT.value
    assert attempts[1].tier == 2
    assert attempts[1].success is True


@pytest.mark.asyncio
async def test_06_tier1_http_429_large_retry_after_skips_wait():
    """Test 6: Tier 1 returns HTTP 429 with large Retry-After -> skips wait, immediate failover to Tier 2."""
    orch = Orchestrator(mode="auto", project="test_p06_6")

    mock_t1 = AsyncMock()
    # 429 with 60 second retry-after
    mock_t1.generate = AsyncMock(return_value=NormalizedModelResponse(
        text="",
        error="RATE_LIMIT_EXCEEDED: HTTP 429 quota exhausted retry after 60s",
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

    t0 = time.monotonic()
    resp = await orch._generate_t1(
        prompt="Generate hero section",
        mission_id="m_429_test",
        turn_id="turn_1",
        timeout_seconds=20.0
    )
    elapsed = time.monotonic() - t0

    assert resp.success is True
    # Fast-failover: did NOT wait 60 seconds
    assert elapsed < 5.0
    assert mock_t1.generate.call_count == 1
    assert mock_t2.generate.call_count == 1

    attempts = global_attempt_ledger.get_attempts_for_mission("m_429_test")
    assert len(attempts) == 2
    assert attempts[0].tier == 1
    assert attempts[0].success is False
    assert attempts[0].error_classification == ErrorClassification.HTTP_429_RATE_LIMIT.value
    assert attempts[1].tier == 2
    assert attempts[1].success is True
