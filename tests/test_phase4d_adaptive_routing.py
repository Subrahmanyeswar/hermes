# tests/test_phase4d_adaptive_routing.py
"""
HERMES Phase 4D Test Suite:
Adaptive Model Routing, Zero-Wait Failover, Provider Health State Machine,
Circuit Breaker, Background Recovery Probing, and Chaos Resilience.
"""

import os
import sys
import time
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Canonical runtime verification
from core.runtime_identity import get_canonical_python_executable
canonical_py = get_canonical_python_executable()
assert sys.executable.lower() == canonical_py.lower(), f"Must run under canonical runtime: {canonical_py}"

from core.adaptive_routing import (
    ProviderHealthState,
    ProviderHealthRecord,
    RouteDecision,
    AdaptiveRouter,
    get_adaptive_router,
)
from models.provider import NormalizedModelResponse


@pytest.fixture
def clean_router():
    """Returns a fresh AdaptiveRouter instance with default healthy state."""
    router = AdaptiveRouter()
    router.reset()
    return router


def test_provider_health_state_machine_initial_state(clean_router):
    """Verify initial state of all tiers is HEALTHY with zero failures."""
    for tier in (1, 2, 3):
        health = clean_router.get_health(tier)
        assert health.state == ProviderHealthState.HEALTHY
        assert health.failure_count == 0
        assert health.consecutive_first_token_failures == 0
        assert health.probe_in_flight is False
        assert clean_router.is_tier_healthy(tier) is True


def test_t1_healthy_direct_dispatch(clean_router):
    """When T1 is healthy, route_primary returns T1 immediately with zero wait."""
    decision = clean_router.route_primary()
    assert decision.tier == 1
    assert decision.bypassed is False
    assert decision.avoided_timeout_ms == 0.0
    assert "T1 is healthy" in decision.reason
    assert decision.decision_latency_ms <= 10.0  # Must be ultra-fast (< 10ms)


def test_t1_circuit_breaker_trips_on_timeout(clean_router):
    """A first token timeout trips T1 into OPEN_CIRCUIT state."""
    t0 = time.time()
    fake_exc = TimeoutError("NVIDIA NIM first token timed out after 15.0s")
    clean_router.record_failure(tier=1, error=fake_exc, timeout_type="FIRST_TOKEN_TIMEOUT", latency=15.0)

    t1_health = clean_router.get_health(1)
    assert t1_health.state == ProviderHealthState.OPEN_CIRCUIT
    assert t1_health.failure_count == 1
    assert t1_health.consecutive_first_token_failures == 1
    assert t1_health.circuit_open_ts is not None
    assert t1_health.circuit_open_ts >= t0
    assert clean_router.is_tier_healthy(1) is False


def test_zero_wait_t2_failover_when_t1_circuit_open(clean_router):
    """When T1 circuit is open, subsequent calls route to T2 immediately without waiting 15s."""
    # Trip circuit
    clean_router.record_failure(tier=1, error=TimeoutError("timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert clean_router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    from config.model_config import MODEL_FIRST_TOKEN_TIMEOUT
    expected_avoided_ms = MODEL_FIRST_TOKEN_TIMEOUT * 1000.0

    # Subsequent route calls should bypass T1 in <= 5ms
    decision1 = clean_router.route_primary()
    assert decision1.tier == 2
    assert decision1.bypassed is True
    assert decision1.avoided_timeout_ms == expected_avoided_ms
    assert decision1.decision_latency_ms <= 10.0
    assert "T1 circuit OPEN_CIRCUIT" in decision1.reason

    decision2 = clean_router.route_primary()
    assert decision2.tier == 2
    assert decision2.bypassed is True
    assert decision2.avoided_timeout_ms == expected_avoided_ms

    # Verify telemetry cumulative savings
    telem = clean_router.telemetry
    assert telem.avoided_timeout_count == 2
    assert telem.avoided_timeout_ms == expected_avoided_ms * 2
    assert telem.t2_circuit_bypass_dispatches == 2


@pytest.mark.asyncio
async def test_background_probe_restores_t1_when_healthy(clean_router):
    """Background probe detects recovery and restores T1 to HEALTHY automatically."""
    # 1. Trip circuit
    clean_router.record_failure(tier=1, error=TimeoutError("timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert clean_router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    # 2. Mock client probe that succeeds
    mock_client = AsyncMock()
    mock_client.is_running = AsyncMock(return_value=True)

    # 3. Run background probe
    success = await clean_router._run_probe(tier=1, client=mock_client)
    assert success is True

    # 4. State must be restored to HEALTHY
    t1_health = clean_router.get_health(1)
    assert t1_health.state == ProviderHealthState.HEALTHY
    assert t1_health.consecutive_first_token_failures == 0
    assert t1_health.circuit_close_ts is not None
    assert clean_router.is_tier_healthy(1) is True

    # 5. Next route request must return T1 again!
    decision = clean_router.route_primary()
    assert decision.tier == 1
    assert decision.bypassed is False
    assert "T1 is healthy" in decision.reason


@pytest.mark.asyncio
async def test_background_probe_failure_keeps_circuit_open(clean_router):
    """If probe fails, circuit remains open and routing continues to bypass T1."""
    clean_router.record_failure(tier=1, error=TimeoutError("timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert clean_router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    mock_client = AsyncMock()
    mock_client.is_running = AsyncMock(return_value=False)

    success = await clean_router._run_probe(tier=1, client=mock_client)
    assert success is False

    assert clean_router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT
    decision = clean_router.route_primary()
    assert decision.tier == 2
    assert decision.bypassed is True


@pytest.mark.asyncio
async def test_orchestrator_integration_zero_wait_failover():
    """Verify Orchestrator._generate_t1 bypasses stalled T1 when circuit is open."""
    from core.orchestrator import Orchestrator
    orch = Orchestrator(mode="auto", project="test_p4d")

    router = get_adaptive_router()
    router.reset()

    # Configure mock tier1 client that raises timeout
    from models.nvidia_client import NvidiaTimeoutError
    orch.tier1 = AsyncMock()
    orch.tier1.generate = AsyncMock(side_effect=NvidiaTimeoutError("stalled", timeout_type="FIRST_TOKEN_TIMEOUT"))

    # Configure mock ollama client
    orch.ollama = AsyncMock()
    orch.ollama.generate = AsyncMock(return_value=NormalizedModelResponse(
        text='{"tool": "write_file", "parameters": {"path": "test.txt", "content": "hello"}}',
        model="gpt-oss:120b-cloud",
        provider="ollama",
        latency_ms=250.0,
        success=True
    ))

    # Task 1: First call hits T1 timeout and fails over to T2
    resp1 = await orch._generate_t1(prompt="task 1", system="sys")
    assert resp1.success is True
    assert orch.tier1.generate.call_count == 1
    assert orch.ollama.generate.call_count == 1
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    # Task 2: Second call should bypass T1 completely (tier1.generate is NOT called again!)
    resp2 = await orch._generate_t1(prompt="task 2", system="sys")
    assert resp2.success is True
    assert orch.tier1.generate.call_count == 1  # Still 1! Not called again!
    assert orch.ollama.generate.call_count == 2  # Routed directly to T2!
    assert router.telemetry.avoided_timeout_count >= 1
    assert router.telemetry.avoided_timeout_ms >= 15000.0


def test_failover_kwargs_formatting():
    """Verify _build_t2_failover_kwargs sanitizes and enforces JSON failover formatting."""
    from core.orchestrator import Orchestrator
    orch = Orchestrator(mode="auto", project="test_p4d")

    orig_kwargs = {
        "model": "z-ai/glm-5.3-flash",
        "prompt": "write a file",
        "system": "base system prompt",
        "tools": [{"name": "write_file"}],
        "tool_choice": "auto",
        "reasoning_effort": "low",
        "temperature": 0.2
    }

    t2_kwargs = orch._build_t2_failover_kwargs(orig_kwargs)
    assert t2_kwargs["model"] == "gpt-oss:120b-cloud"
    assert t2_kwargs["format"] == "json"
    assert t2_kwargs["think"] is False
    assert "tools" not in t2_kwargs
    assert "tool_choice" not in t2_kwargs
    assert "reasoning_effort" not in t2_kwargs
    assert "[FAILOVER TOOL EXECUTION RULE]" in t2_kwargs["system"]


@pytest.mark.asyncio
async def test_disagreement_router_genuine_semantic_escalation():
    """Verify DisagreementRouter only escalates to Tier 3 on genuine semantic mismatches."""
    from core.disagreement_router import DisagreementRouter, RoutingDecision
    from core.verifier import VerificationResult

    dr = DisagreementRouter()

    # Agreement case
    vr_agree = VerificationResult(
        agree=True,
        confidence=0.95,
        critical_issues=[],
        risk_score=0.10
    )
    res_agree = dr.route(vr_agree, tool_name="write_file")
    assert res_agree.decision == RoutingDecision.ACCEPT
    assert res_agree.tier3_needed is False

    # Genuine disagreement case
    vr_disagree = VerificationResult(
        agree=False,
        confidence=0.40,
        critical_issues=["Model generated incompatible AST structure"],
        risk_score=0.85
    )
    res_disagree = dr.route(vr_disagree, tool_name="write_file")
    assert res_disagree.decision == RoutingDecision.ESCALATE
    assert res_disagree.tier3_needed is True


@pytest.mark.asyncio
async def test_chaos_network_dns_failure_simulation(clean_router):
    """Simulate DNS failure on T1 and verify clean circuit opening without crash."""
    from models.nvidia_client import NvidiaConnectionError
    dns_err = NvidiaConnectionError("Could not resolve host: integrate.api.nvidia.com")

    clean_router.record_failure(tier=1, error=dns_err, timeout_type="CONNECT_TIMEOUT", latency=1.0)
    assert clean_router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    decision = clean_router.route_primary()
    assert decision.tier == 2
    assert decision.bypassed is True
    assert decision.avoided_timeout_ms > 0
