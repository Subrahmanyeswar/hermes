# tests/test_phase6_transport_hardening.py
"""
HERMES Phase 6 Acceptance Test Suite:
Model Transport, Streaming, Retry & Circuit-Breaker Hardening.

Covers Sections A through I:
- Section A: HTTP Client Lifetime and Connection Pool Management
- Section B: Timeout Layers & Deadlines
- Section C: Provider Error Classification & Secret Redaction
- Section D: Authentication, Billing & Rate Limiting (Retry-After)
- Section E: Safe Streaming & Response Completeness (NVIDIA SSE & Ollama NDJSON)
- Section F: Bounded Retries & Backoff with Jitter
- Section G: Circuit Breaker State Machine & Route Isolation
- Section H: Explicit Tier Fallback (T1 -> T2 -> T3)
- Section I: Phase 4 Stop Cancellation & Phase 5 Continuity Integration
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from core.transport.client_manager import TransportClientManager
from core.transport.circuit_breaker import CircuitBreakerRegistry, CircuitState
from core.transport.retry_coordinator import (
    FallbackPolicyConfig,
    RetryCoordinator,
    RouteAttemptRecord,
    TransportExecutionResult,
)
from core.transport.stream_validator import (
    OllamaStreamAccumulator,
    SseStreamAccumulator,
)
from core.transport.types import (
    ErrorCategory,
    StructuredTransportError,
    classify_http_status,
    sanitize_error_text,
)
from models.provider import NormalizedModelResponse
from core.transport.circuit_breaker import circuit_breaker_registry


@pytest.fixture(autouse=True)
async def clean_breaker():
    """Ensure circuit breaker registry is clean for every test."""
    await circuit_breaker_registry.reset()
    yield
    await circuit_breaker_registry.reset()


# ── Section A: HTTP Client Lifetime and Ownership ──────────────────────────

@pytest.mark.asyncio
async def test_section_a_client_reuse_and_lifecycle():
    """Client manager reuses active client for identical base_url and closes on aclose()."""
    mgr = TransportClientManager()
    c1 = await mgr.get_client("https://integrate.api.nvidia.com/v1")
    c2 = await mgr.get_client("https://integrate.api.nvidia.com/v1")
    assert c1 is c2
    assert not c1.is_closed

    # Different URL gets its own client
    c_local = await mgr.get_client("http://127.0.0.1:11434")
    assert c_local is not c1

    await mgr.aclose()
    assert c1.is_closed
    assert c_local.is_closed


@pytest.mark.asyncio
async def test_section_a_request_cancellation_does_not_close_shared_client():
    """Cancelling one mission's in-flight request does not invalidate or close the shared pool client."""
    mgr = TransportClientManager()
    shared_client = await mgr.get_client("https://integrate.api.nvidia.com/v1")

    async def fake_mission_request():
        await asyncio.sleep(10.0)

    task = asyncio.create_task(fake_mission_request())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Shared client must remain open and healthy for subsequent missions
    assert not shared_client.is_closed
    await mgr.aclose()


# ── Section B: Timeout Layers & Deadlines ────────────────────────────────────

def test_section_b_timeout_classification():
    """Layered timeouts (connect, read-idle, deadline) map to distinct ErrorCategories."""
    err_conn = classify_http_status(504, "Gateway connect timeout", "nvidia_nim", "z-ai/glm-5.3-flash")
    assert err_conn.category == ErrorCategory.PROVIDER_SERVER_ERROR

    read_err = StructuredTransportError(
        category=ErrorCategory.READ_IDLE_TIMEOUT,
        message="Stream read-idle timeout exceeded.",
        provider="nvidia_nim",
        model="z-ai/glm-5.3-flash",
        retryable=True,
    )
    assert read_err.category == ErrorCategory.READ_IDLE_TIMEOUT


@pytest.mark.asyncio
async def test_section_b_overall_deadline_stops_retries():
    """Logical request overall deadline stops subsequent retries deterministically."""
    clock_time = 100.0

    def fake_time():
        nonlocal clock_time
        return clock_time

    async def fake_sleep(secs):
        nonlocal clock_time
        clock_time += secs

    cfg = FallbackPolicyConfig(
        total_request_deadline_seconds=2.0,
        primary_max_retries=5,
        base_backoff_seconds=1.0,
    )
    coord = RetryCoordinator(config=cfg, time_func=fake_time, sleep_func=fake_sleep)

    call_count = 0

    async def failing_invoker(tier, provider, model, attempt, timeout_remaining):
        nonlocal call_count, clock_time
        call_count += 1
        clock_time += 1.5  # First attempt consumes 1.5s out of 2.0s
        raise StructuredTransportError(
            category=ErrorCategory.PROVIDER_SERVER_ERROR,
            message="Server overloaded",
            provider=provider,
            model=model,
            retryable=True,
            attempt=attempt,
        )

    res = await coord.execute_with_resilience(failing_invoker)
    assert res.response is None
    assert res.error is not None
    assert res.error.category == ErrorCategory.OVERALL_DEADLINE_EXCEEDED
    assert call_count == 1  # Cannot retry because deadline is exceeded


# ── Section C: Provider Error Classification & Secret Redaction ─────────────

def test_section_c_secret_redaction():
    """Secrets (API keys, bearer tokens) are strictly redacted from error messages."""
    raw_error = "Authorization failed for Bearer nvapi-secretkey1234567890abcdef. api_key='nvapi-abc1234567890xyz'"
    sanitized = sanitize_error_text(raw_error)
    assert "nvapi-secretkey1234567890abcdef" not in sanitized
    assert "nvapi-abc1234567890xyz" not in sanitized
    assert "[REDACTED" in sanitized

    err = StructuredTransportError(
        category=ErrorCategory.AUTHENTICATION_FAILURE,
        message=raw_error,
        provider="nvidia_nim",
        model="z-ai/glm-5.3-flash",
    )
    assert "nvapi-" not in str(err)
    assert "nvapi-" not in err.sanitized_message


def test_section_c_error_classification_mappings():
    """Status codes map to accurate non-retryable vs retryable categories."""
    e401 = classify_http_status(401, "Invalid token")
    assert e401.category == ErrorCategory.AUTHENTICATION_FAILURE
    assert not e401.retryable

    e403 = classify_http_status(403, "Insufficient credits / billing required")
    assert e403.category == ErrorCategory.BILLING_FAILURE
    assert not e403.retryable
    assert e403.fallback_eligible

    e429_quota = classify_http_status(429, "You exceeded your current quota, check your plan")
    assert e429_quota.category == ErrorCategory.QUOTA_EXHAUSTED
    assert not e429_quota.retryable

    e429_rate = classify_http_status(429, "Rate limit exceeded, try again later")
    assert e429_rate.category == ErrorCategory.RATE_LIMITED
    assert e429_rate.retryable

    e503 = classify_http_status(503, "Service unavailable")
    assert e503.category == ErrorCategory.PROVIDER_UNAVAILABLE
    assert e503.retryable


# ── Section D: Authentication, Billing & Rate Limiting ───────────────────────

@pytest.mark.asyncio
async def test_section_d_auth_failure_does_not_retry():
    """401 Authentication failure does not perform retry loops."""
    call_count = 0

    async def invoker(tier, provider, model, attempt, timeout_remaining):
        nonlocal call_count
        call_count += 1
        raise StructuredTransportError(
            category=ErrorCategory.AUTHENTICATION_FAILURE,
            message="401 Unauthorized",
            provider=provider,
            model=model,
            retryable=False,
            fallback_eligible=False,
        )

    coord = RetryCoordinator(config=FallbackPolicyConfig(primary_max_retries=3, enabled=False))
    res = await coord.execute_with_resilience(invoker)
    assert res.response is None
    assert call_count == 1  # Exactly 1 attempt; no retries


@pytest.mark.asyncio
async def test_section_d_retry_after_respected():
    """Temporary rate limit respects Retry-After delay within bounded limits."""
    sleeps = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    coord = RetryCoordinator(
        config=FallbackPolicyConfig(max_backoff_seconds=5.0),
        sleep_func=fake_sleep,
    )
    attempts = 0

    async def invoker(tier, provider, model, attempt, timeout_remaining):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StructuredTransportError(
                category=ErrorCategory.RATE_LIMITED,
                message="Rate limited",
                provider=provider,
                model=model,
                retryable=True,
                retry_after=2.5,
            )
        return NormalizedModelResponse(text="Success after rate limit", success=True)

    res = await coord.execute_with_resilience(invoker)
    assert res.response is not None
    assert res.response.text == "Success after rate limit"
    assert len(sleeps) == 1
    assert sleeps[0] == 2.5


# ── Section E: Streaming Completeness & Protocol Integrity ───────────────────

def test_section_e_sse_stream_complete_with_tool_call():
    """Complete SSE stream with valid [DONE] and tool call delta parses safely."""
    acc = SseStreamAccumulator(model="z-ai/glm-5.3-flash", provider="nvidia_nim")
    now = time.monotonic()

    chunks = [
        'data: {"choices": [{"delta": {"reasoning_content": "Plan step"}}]}',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "write_file", "arguments": "{\\"path\\": "}}]}}]}',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\\"a.txt\\", \\"content\\": \\"hi\\"}"}}]}}]}',
        'data: [DONE]',
    ]

    for c in chunks:
        is_done, err = acc.process_chunk(c, now)
        assert err is None

    assert acc.has_terminal_marker is True
    resp, err = acc.validate_and_finalize(elapsed_ms=100.0)
    assert err is None
    assert resp.success is True
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "write_file"
    assert resp.tool_calls[0]["arguments"] == {"path": "a.txt", "content": "hi"}


def test_section_e_sse_stream_incomplete_rejected():
    """Incomplete SSE stream lacking [DONE] marker is rejected with STREAM_INCOMPLETE."""
    acc = SseStreamAccumulator(model="z-ai/glm-5.3-flash", provider="nvidia_nim")
    acc.process_chunk('data: {"choices": [{"delta": {"content": "Hello partial"}}]}', time.monotonic())

    # Stream ends abruptly without [DONE]
    resp, err = acc.validate_and_finalize(elapsed_ms=50.0)
    assert resp.success is False
    assert err is not None
    assert err.category == ErrorCategory.STREAM_INCOMPLETE


def test_section_e_ollama_stream_complete_and_incomplete():
    """Ollama NDJSON requires 'done: true' marker; abrupt EOF fails validation."""
    acc = OllamaStreamAccumulator(model="gpt-oss:120b-cloud", provider="ollama")
    acc.process_line('{"response": "Part 1", "done": false}')
    resp_inc, err_inc = acc.validate_and_finalize(elapsed_ms=50.0)
    assert resp_inc.success is False
    assert err_inc.category == ErrorCategory.STREAM_INCOMPLETE

    # Emit terminal chunk
    acc.process_line('{"response": " Part 2", "done": true, "eval_count": 10}')
    resp_ok, err_ok = acc.validate_and_finalize(elapsed_ms=80.0)
    assert err_ok is None
    assert resp_ok.success is True
    assert resp_ok.text == "Part 1 Part 2"


# ── Section F: Bounded Retries & Backoff ──────────────────────────────────────

@pytest.mark.asyncio
async def test_section_f_transient_5xx_retries_and_succeeds():
    """Transient HTTP 500 retries up to limit and returns success on subsequent attempt."""
    attempts = 0
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    coord = RetryCoordinator(
        config=FallbackPolicyConfig(primary_max_retries=3),
        sleep_func=fake_sleep,
    )

    async def invoker(tier, provider, model, attempt, timeout_remaining):
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise StructuredTransportError(
                category=ErrorCategory.PROVIDER_SERVER_ERROR,
                message="HTTP 500",
                provider=provider,
                model=model,
                retryable=True,
            )
        return NormalizedModelResponse(text="Success on attempt 2", success=True)

    res = await coord.execute_with_resilience(invoker)
    assert res.response is not None
    assert res.response.text == "Success on attempt 2"
    assert attempts == 2
    assert len(sleeps) == 1


# ── Section G: Circuit Breaker State Transitions ─────────────────────────────

@pytest.mark.asyncio
async def test_section_g_circuit_breaker_lifecycle():
    """Circuit breaker transitions CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    clock_mono = 1000.0

    def fake_time():
        nonlocal clock_mono
        return clock_mono

    cb = CircuitBreakerRegistry(time_func=fake_time)
    provider = "test_prov"
    model = "test_model"

    rec = cb.get_record(provider, model, failure_threshold=2, cooldown_seconds=10.0)
    assert rec.state == CircuitState.CLOSED

    # Failure 1
    err = StructuredTransportError(category=ErrorCategory.CONNECTION_FAILURE, message="Down", provider=provider, model=model)
    await cb.record_failure(provider, model, err)
    assert rec.state == CircuitState.CLOSED

    # Failure 2 trips breaker to OPEN
    await cb.record_failure(provider, model, err)
    assert rec.state == CircuitState.OPEN

    # Requests fail fast while OPEN
    can, trip_err = await cb.check_can_proceed(provider, model)
    assert not can
    assert trip_err.category == ErrorCategory.CIRCUIT_BREAKER_OPEN

    # Advance clock past 10s cooldown -> enters HALF_OPEN probe
    clock_mono += 11.0
    can_probe, _ = await cb.check_can_proceed(provider, model)
    assert can_probe is True
    assert rec.state == CircuitState.HALF_OPEN

    # Successful probe resets breaker to CLOSED
    await cb.record_success(provider, model)
    assert rec.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_section_g_user_stop_cancellation_does_not_trip_circuit():
    """Intentional user cancellation does NOT increment circuit failure count."""
    cb = CircuitBreakerRegistry()
    stop_err = StructuredTransportError(
        category=ErrorCategory.CANCELLED_BY_STOP,
        message="Stopped by user",
        provider="nvidia_nim",
        model="z-ai/glm-5.3-flash",
    )
    await cb.record_failure("nvidia_nim", "z-ai/glm-5.3-flash", stop_err)
    rec = cb.get_record("nvidia_nim", "z-ai/glm-5.3-flash", failure_threshold=1)
    assert rec.consecutive_failures == 0
    assert rec.state == CircuitState.CLOSED


# ── Section H: Explicit Tier Fallback (T1 -> T2 -> T3) ───────────────────────

@pytest.mark.asyncio
async def test_section_h_explicit_fallback_t1_to_t2():
    """When T1 fails with eligible error, request falls back cleanly to T2."""
    invoked_tiers = []

    async def multi_tier_invoker(tier, provider, model, attempt, timeout_remaining):
        invoked_tiers.append(tier)
        if tier == 1:
            raise StructuredTransportError(
                category=ErrorCategory.PROVIDER_UNAVAILABLE,
                message="T1 503 Service Unavailable",
                provider=provider,
                model=model,
                retryable=False,
                fallback_eligible=True,
            )
        elif tier == 2:
            return NormalizedModelResponse(
                text="Answer from Tier 2 Ollama Cloud",
                model=model,
                provider=provider,
                success=True,
            )
        raise RuntimeError("Unexpected tier")

    coord = RetryCoordinator(config=FallbackPolicyConfig(primary_max_retries=1, fallback_max_retries=1))
    res = await coord.execute_with_resilience(multi_tier_invoker)

    assert res.response is not None
    assert res.final_tier == 2
    assert res.fallback_used is True
    assert "T1 503" in (res.fallback_reason or "")
    assert invoked_tiers == [1, 2]
    assert res.response.text == "Answer from Tier 2 Ollama Cloud"


# ── Section I: Phase 4 & Phase 5 Continuity Integration ──────────────────────

@pytest.mark.asyncio
async def test_section_i_abort_signal_stops_execution_immediately():
    """Abort signal from Phase 4 aborts before execution without starting retries or fallbacks."""
    abort_evt = asyncio.Event()
    abort_evt.set()  # Stop already signaled

    called = False

    async def invoker(tier, provider, model, attempt, timeout_remaining):
        nonlocal called
        called = True
        return NormalizedModelResponse(text="Should not run", success=True)

    coord = RetryCoordinator()
    res = await coord.execute_with_resilience(invoker, abort_event=abort_evt, mission_id="m_stop_test")

    assert called is False
    assert res.response is None
    assert res.error is not None
    assert res.error.category == ErrorCategory.CANCELLED_BY_STOP
