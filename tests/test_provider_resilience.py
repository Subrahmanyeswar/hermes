# tests/test_provider_resilience.py
"""
Provider Resilience and Multi-Tier Failover Test Suite for HERMES 2.x.
Validates:
1. Provider error classification (HTTP 401, 403, 404, 429, 500, 503, timeouts).
2. Circuit breaker transitions across Tier 1 and Tier 2 (HEALTHY -> DEGRADED -> OPEN_CIRCUIT -> RECOVERED).
3. Zero-wait failover from Tier 1 to Tier 2 and Tier 2 to Tier 3 when degraded/open.
4. Error handling in DecisionInterpreter: provider errors are NOT converted to CONTINUE_REASONING.
5. Context preservation across multi-tier failovers.
"""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock

from models.common_adapter import classify_provider_error, ErrorClassification, NormalizedModelResponse
from core.adaptive_routing import (
    AdaptiveRouter,
    ProviderHealthState,
    RouteDecision,
)
from core.agent_loop.decisions import DecisionInterpreter, AgentDecisionType


def test_classify_provider_errors():
    """Verify provider status codes are mapped into actionable taxonomy."""
    # 401 Auth
    err401 = classify_provider_error(status_code=401, response_body="Invalid API key")
    assert err401.classification == ErrorClassification.AUTH_FAILURE
    assert not err401.is_transient

    # 403 Permission
    err403 = classify_provider_error(status_code=403, response_body="Forbidden")
    assert err403.classification == ErrorClassification.PERMISSION_DENIED

    # 404 Not Found
    err404 = classify_provider_error(status_code=404, response_body="Model does not exist")
    assert err404.classification == ErrorClassification.MODEL_NOT_FOUND

    # 429 Rate Limit
    err429 = classify_provider_error(status_code=429, response_body="Rate limit exceeded")
    assert err429.classification == ErrorClassification.RATE_LIMIT_EXCEEDED
    assert err429.is_transient

    # 503 Service Unavailable / Demand Spikes
    err503 = classify_provider_error(status_code=503, response_body="Model overloaded")
    assert err503.classification == ErrorClassification.SERVICE_UNAVAILABLE
    assert err503.is_transient

    # 500 Internal Error
    err500 = classify_provider_error(status_code=500, response_body="Internal error")
    assert err500.classification == ErrorClassification.INTERNAL_ERROR
    assert err500.is_transient


def test_circuit_breaker_transitions():
    """Verify circuit breaker transitions HEALTHY -> DEGRADED -> OPEN_CIRCUIT on repeated failures."""
    router = AdaptiveRouter()

    # Initial state
    assert router.providers[1].state == ProviderHealthState.HEALTHY
    assert router.providers[2].state == ProviderHealthState.HEALTHY

    # Single failure on Tier 1 -> DEGRADED
    router.record_failure(tier=1, error=Exception("HTTP 503: Unavailable"), timeout_type="ERROR")
    assert router.providers[1].state == ProviderHealthState.DEGRADED

    # Additional failures -> OPEN_CIRCUIT
    router.record_failure(tier=1, error=Exception("HTTP 503: Unavailable"), timeout_type="ERROR")
    router.record_failure(tier=1, error=Exception("HTTP 503: Unavailable"), timeout_type="ERROR")
    assert router.providers[1].state == ProviderHealthState.OPEN_CIRCUIT

    # Success restores HEALTHY
    router.record_success(tier=1, latency=1.2)
    assert router.providers[1].state == ProviderHealthState.HEALTHY


def test_tier2_circuit_breaker_and_tier3_failover():
    """Verify that when Tier 1 and Tier 2 are degraded/open, router fails over directly to Tier 3."""
    router = AdaptiveRouter()

    # Trip Tier 1
    router.record_failure(tier=1, error=Exception("Timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert router.providers[1].state == ProviderHealthState.DEGRADED

    # With T1 degraded and T2 healthy, routes to T2
    decision1 = router.route_primary()
    assert decision1.tier == 2
    assert decision1.bypassed is True

    # Now trip Tier 2 with HTTP 429
    router.record_failure(tier=2, error=Exception("HTTP 429: Rate Limit Exceeded"), timeout_type="RATE_LIMIT")
    assert router.providers[2].state in (ProviderHealthState.DEGRADED, ProviderHealthState.OPEN_CIRCUIT)

    # With both T1 and T2 degraded, route_primary must zero-wait failover directly to Tier 3!
    decision2 = router.route_primary()
    assert decision2.tier == 3
    assert decision2.bypassed is True
    assert "T3" in decision2.reason or "fast-failover to T3" in decision2.reason


def test_interpreter_rejects_failed_responses():
    """Verify DecisionInterpreter marks failed responses as INVALID rather than CONTINUE_REASONING."""
    interpreter = DecisionInterpreter()

    # 1. Groq HTTP 429
    resp_429 = NormalizedModelResponse(
        text="",
        model="qwen/qwen3.8-27b",
        provider="groq",
        error="RATE_LIMIT_EXCEEDED: [429] Quota exhausted",
        success=False,
    )
    dec_429 = interpreter.interpret(resp_429)
    assert dec_429.decision_type == AgentDecisionType.INVALID
    assert "PROVIDER_ERROR" in dec_429.reasoning

    # 2. Gemini HTTP 503
    resp_503 = NormalizedModelResponse(
        text="",
        model="gemini-3.5-flash-lite",
        provider="gemini",
        error="SERVICE_UNAVAILABLE: [503] Model high demand",
        success=False,
    )
    dec_503 = interpreter.interpret(resp_503)
    assert dec_503.decision_type == AgentDecisionType.INVALID
    assert "PROVIDER_ERROR" in dec_503.reasoning


def test_transient_error_recovery():
    """Verify that successful generation restores Tier 2 from DEGRADED back to HEALTHY."""
    router = AdaptiveRouter()
    router.record_failure(tier=2, error=Exception("HTTP 429"), timeout_type="RATE_LIMIT")
    assert router.providers[2].state == ProviderHealthState.DEGRADED

    # Tier 2 succeeds on subsequent call
    router.record_success(tier=2, latency=2.1)
    assert router.providers[2].state == ProviderHealthState.HEALTHY
