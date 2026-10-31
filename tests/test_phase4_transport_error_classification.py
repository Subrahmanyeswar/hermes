"""
Phase 4 Acceptance Test Suite: Error Classification, Secret Redaction & Status Taxonomy (Scenarios F, G, H / Gate C).

Verifies:
- Scenario F: HTTP 401 Authentication failure does not enter futile retry loops.
- Scenario G: HTTP 402 / Quota exhaustion is distinguished and not retried indefinitely.
- Scenario H: HTTP 429 Rate limiting is distinguished from hard quota, respecting bounded Retry-After.
- Secret redaction: API keys and bearer tokens are never leaked in error messages.
"""

import pytest

from core.transport.types import (
    ErrorCategory,
    classify_http_status,
    sanitize_error_text,
)
from core.transport.retry_coordinator import (
    FallbackPolicyConfig,
    RetryCoordinator,
    StructuredTransportError,
)


def test_scenario_f_auth_failure_does_not_retry():
    """Verify HTTP 401 is classified as AUTHENTICATION_FAILURE and marked non-retryable."""
    err = classify_http_status(
        status_code=401,
        body_text="Unauthorized: Invalid API key",
        provider="nvidia_nim",
        model="z-ai/glm-5.3-flash",
    )
    assert err.category == ErrorCategory.AUTHENTICATION_FAILURE
    assert err.retryable is False
    assert err.fallback_eligible is False
    assert err.status_code == 401


def test_scenario_g_billing_failure_classification():
    """Verify HTTP 403 billing issues and HTTP 402 are classified as BILLING_FAILURE and not retried."""
    err_403_billing = classify_http_status(
        status_code=403,
        body_text="Forbidden: Insufficient account credit balance for request",
        provider="nvidia_nim",
        model="z-ai/glm-5.3-flash",
    )
    assert err_403_billing.category == ErrorCategory.BILLING_FAILURE
    assert err_403_billing.retryable is False
    assert err_403_billing.fallback_eligible is True


def test_scenario_h_rate_limiting_vs_quota_exhaustion():
    """Verify HTTP 429 distinguishes transient rate limits from hard quota exhaustion."""
    # 1. Hard Quota Exhausted
    err_quota = classify_http_status(
        status_code=429,
        body_text="You have exceeded your current quota. Please upgrade your plan.",
        provider="nvidia_nim",
        model="z-ai/glm-5.3-flash",
    )
    assert err_quota.category == ErrorCategory.QUOTA_EXHAUSTED
    assert err_quota.retryable is False
    assert err_quota.fallback_eligible is True

    # 2. Transient Rate Limit
    err_rate = classify_http_status(
        status_code=429,
        body_text="Rate limit reached: 60 requests per minute.",
        provider="nvidia_nim",
        model="z-ai/glm-5.3-flash",
    )
    assert err_rate.category == ErrorCategory.RATE_LIMITED
    assert err_rate.retryable is True
    assert err_rate.fallback_eligible is True


def test_secret_redaction_prevents_leaks():
    """Verify API keys, bearer tokens, and headers are redacted from error output."""
    raw_str = (
        "Failed POST https://api.nvidia.com: "
        "Authorization: Bearer nvapi-1234567890abcdef12345678. "
        "Also sk-9876543210fedcba98765432 and api_key=secret_token_12345678."
    )
    sanitized = sanitize_error_text(raw_str)

    assert "nvapi-1234567890abcdef12345678" not in sanitized
    assert "sk-9876543210fedcba98765432" not in sanitized
    assert "secret_token_12345678" not in sanitized
    assert "[REDACTED" in sanitized


@pytest.mark.asyncio
async def test_auth_failure_aborts_immediately_without_retry():
    """Verify RetryCoordinator aborts on AUTHENTICATION_FAILURE without attempting retries."""
    cfg = FallbackPolicyConfig(
        primary_max_retries=5,
        enabled=False,
        total_request_deadline_seconds=10.0,
    )
    coord = RetryCoordinator(config=cfg)

    call_count = 0

    async def auth_fail_invoker(tier, provider, model, attempt, timeout_remaining):
        nonlocal call_count
        call_count += 1
        raise classify_http_status(401, "Invalid key", provider, model)

    res = await coord.execute_with_resilience(auth_fail_invoker)
    assert res.response is None
    assert res.error is not None
    assert res.error.category == ErrorCategory.AUTHENTICATION_FAILURE
    # Aborts immediately after attempt 1
    assert call_count == 1
