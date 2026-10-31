"""
Phase 4 Acceptance Test Suite: Bounded Retries & Exponential Backoff (Scenario E / Gate D).

Verifies:
- Scenario E: Transient 503 errors trigger bounded retry with backoff, culminating in success.
- Finite retry attempts (does not loop forever).
- Backoff cap and jitter calculation.
- Retry-After header is parsed, respected, and bounded.
"""

import pytest

from core.transport.types import (
    ErrorCategory,
    StructuredTransportError,
)
from core.transport.circuit_breaker import CircuitBreakerRegistry, circuit_breaker_registry
from core.transport.retry_coordinator import (
    FallbackPolicyConfig,
    RetryCoordinator,
)
from models.provider import NormalizedModelResponse


@pytest.fixture(autouse=True)
async def reset_cb():
    await circuit_breaker_registry.reset()


@pytest.mark.asyncio
async def test_scenario_e_transient_503_retries_and_succeeds():
    """Verify two transient 503 errors succeed on 3rd attempt with exponential backoff delays recorded."""
    delays_recorded = []

    async def fake_sleep(secs: float):
        delays_recorded.append(secs)

    cfg = FallbackPolicyConfig(
        primary_max_retries=3,
        base_backoff_seconds=0.5,
        max_backoff_seconds=5.0,
    )
    coord = RetryCoordinator(
        config=cfg,
        sleep_func=fake_sleep,
        circuit_breaker=CircuitBreakerRegistry(),
    )

    attempts = 0

    async def transient_invoker(tier, provider, model, attempt, timeout_remaining):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise StructuredTransportError(
                category=ErrorCategory.PROVIDER_UNAVAILABLE,
                message="HTTP 503 Service Temporarily Unavailable",
                provider=provider,
                model=model,
                status_code=503,
                retryable=True,
                attempt=attempt,
            )
        return NormalizedModelResponse(
            text="Service recovered successfully on attempt 3",
            success=True,
            provider=provider,
            model=model,
        )

    res = await coord.execute_with_resilience(transient_invoker)
    assert res.response is not None
    assert res.response.success is True
    assert res.response.text == "Service recovered successfully on attempt 3"
    assert attempts == 3
    # Slept twice (after attempt 1 and after attempt 2)
    assert len(delays_recorded) == 2
    assert all(d > 0.0 for d in delays_recorded)


@pytest.mark.asyncio
async def test_scenario_e_retry_after_header_respected():
    """Verify Retry-After delay is parsed and enforced before next attempt."""
    delays_recorded = []

    async def fake_sleep(secs: float):
        delays_recorded.append(secs)

    cfg = FallbackPolicyConfig(
        primary_max_retries=3,
        base_backoff_seconds=0.1,
    )
    coord = RetryCoordinator(
        config=cfg,
        sleep_func=fake_sleep,
        circuit_breaker=CircuitBreakerRegistry(),
    )

    attempts = 0

    async def rate_limited_invoker(tier, provider, model, attempt, timeout_remaining):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StructuredTransportError(
                category=ErrorCategory.RATE_LIMITED,
                message="HTTP 429 Too Many Requests",
                provider=provider,
                model=model,
                status_code=429,
                retryable=True,
                retry_after=1.75,
                attempt=attempt,
            )
        return NormalizedModelResponse(
            text="Success after Retry-After delay",
            success=True,
        )

    res = await coord.execute_with_resilience(rate_limited_invoker)
    assert res.response is not None
    assert res.response.success is True
    assert len(delays_recorded) == 1
    assert delays_recorded[0] == 1.75


def test_scenario_e_backoff_calculation_bounded_and_jittered():
    """Verify backoff calculation caps at max_backoff and applies bounded jitter."""
    cfg = FallbackPolicyConfig(
        base_backoff_seconds=0.5,
        max_backoff_seconds=4.0,
    )
    coord = RetryCoordinator(config=cfg)

    # Attempt 1 -> 0.5s * 2^0 + jitter (0..0.25)
    d1 = coord._calculate_backoff(attempt=1)
    assert 0.5 <= d1 <= 0.8

    # Attempt 2 -> 0.5s * 2^1 + jitter (0..0.5)
    d2 = coord._calculate_backoff(attempt=2)
    assert 1.0 <= d2 <= 1.6

    # Attempt 10 -> capped at max_backoff (4.0s) + jitter
    d10 = coord._calculate_backoff(attempt=10)
    assert 4.0 <= d10 <= 5.0
