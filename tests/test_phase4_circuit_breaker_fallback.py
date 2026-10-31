"""
Phase 4 Acceptance Test Suite: Circuit Breaker & Explicit Tier Fallback (Scenarios K, L / Gates D, E).

Verifies:
- Scenario K: Circuit breaker opens after 5 qualifying failures, rejects doomed calls, and half-open recovers.
- User stop cancellation does NOT count as a provider circuit failure.
- Scenario L: Explicit Tier 1 -> Tier 2 failover occurs with logical context preserved.
"""

import asyncio
import pytest

from core.transport.circuit_breaker import (
    CircuitBreakerRegistry,
    CircuitState,
    circuit_breaker_registry,
)
from core.transport.retry_coordinator import (
    FallbackPolicyConfig,
    RetryCoordinator,
)
from core.transport.types import (
    ErrorCategory,
    StructuredTransportError,
)
from models.provider import NormalizedModelResponse


@pytest.fixture(autouse=True)
async def reset_cb():
    await circuit_breaker_registry.reset()


@pytest.mark.asyncio
async def test_scenario_k_circuit_breaker_threshold_and_recovery():
    """Verify 5 consecutive qualifying failures trips circuit open; half-open probe recovers on success."""
    cb = CircuitBreakerRegistry()
    provider = "nvidia_nim"
    model = "z-ai/glm-5.3-flash"

    # Initial state is CLOSED with failure_threshold=5
    rec = cb.get_record(provider, model, failure_threshold=5)
    assert rec.state == CircuitState.CLOSED
    assert rec.failure_threshold == 5

    # Inject 4 failures -> breaker remains CLOSED
    for i in range(1, 5):
        err = StructuredTransportError(
            category=ErrorCategory.PROVIDER_SERVER_ERROR,
            message=f"Transient failure #{i}",
            provider=provider,
            model=model,
            retryable=True,
        )
        await cb.record_failure(provider, model, err)
        rec = cb.get_record(provider, model)
        assert rec.state == CircuitState.CLOSED
        assert rec.consecutive_failures == i

    # 5th consecutive failure trips to OPEN
    err_5 = StructuredTransportError(
        category=ErrorCategory.PROVIDER_UNAVAILABLE,
        message="5th consecutive failure",
        provider=provider,
        model=model,
        retryable=True,
    )
    await cb.record_failure(provider, model, err_5)
    rec = cb.get_record(provider, model)
    assert rec.state == CircuitState.OPEN

    # Check can_proceed while OPEN -> rejected without making network call
    can_proc, trip_err = await cb.check_can_proceed(provider, model)
    assert can_proc is False
    assert trip_err is not None
    assert trip_err.category == ErrorCategory.CIRCUIT_BREAKER_OPEN

    # Simulate cooldown expiry for half-open probe
    rec.circuit_opened_time = 0.0  # opened long ago, cooldown expired
    can_probe, probe_err = await cb.check_can_proceed(provider, model)
    assert can_probe is True
    assert probe_err is None
    rec = cb.get_record(provider, model)
    assert rec.state == CircuitState.HALF_OPEN

    # Successful probe closes breaker
    await cb.record_success(provider, model)
    rec = cb.get_record(provider, model)
    assert rec.state == CircuitState.CLOSED
    assert rec.consecutive_failures == 0


@pytest.mark.asyncio
async def test_scenario_k_user_stop_does_not_trip_circuit():
    """Verify mission cancellation (CANCELLED_BY_STOP) does not increment circuit failure counter."""
    cb = CircuitBreakerRegistry()
    provider = "nvidia_nim"
    model = "z-ai/glm-5.3-flash"

    stop_err = StructuredTransportError(
        category=ErrorCategory.CANCELLED_BY_STOP,
        message="Mission stopped by user",
        provider=provider,
        model=model,
        retryable=False,
    )

    for _ in range(10):
        await cb.record_failure(provider, model, stop_err)

    rec = cb.get_record(provider, model)
    assert rec.state == CircuitState.CLOSED
    assert rec.consecutive_failures == 0


@pytest.mark.asyncio
async def test_scenario_l_explicit_fallback_tier1_to_tier2():
    """Verify primary route failure triggers explicit fallback to Tier 2 with preserved context."""
    cfg = FallbackPolicyConfig(
        enabled=True,
        primary_max_retries=1,
        fallback_max_retries=1,
    )
    routes = [
        (1, "nvidia_nim", "z-ai/glm-5.3-flash"),
        (2, "ollama", "gpt-oss:120b-cloud"),
    ]
    coord = RetryCoordinator(
        config=cfg,
        routes=routes,
        circuit_breaker=CircuitBreakerRegistry(),
    )

    invoked_tiers = []

    async def fallback_invoker(tier, provider, model, attempt, timeout_remaining):
        invoked_tiers.append(tier)
        if tier == 1:
            raise StructuredTransportError(
                category=ErrorCategory.PROVIDER_UNAVAILABLE,
                message="Tier 1 Gateway Timeout (HTTP 504)",
                provider=provider,
                model=model,
                status_code=504,
                retryable=True,
            )
        return NormalizedModelResponse(
            text="Tier 2 response successfully fulfilled",
            provider=provider,
            model=model,
            success=True,
        )

    res = await coord.execute_with_resilience(fallback_invoker)
    assert res.response is not None
    assert res.response.success is True
    assert res.final_tier == 2
    assert res.final_provider == "ollama"
    assert res.final_model == "gpt-oss:120b-cloud"
    assert res.fallback_used is True
    assert invoked_tiers == [1, 2]
    assert "Gateway Timeout" in (res.fallback_reason or "")
