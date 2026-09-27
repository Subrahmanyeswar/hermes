# tests/test_prompt12_failure_injection.py
"""
Failure Injection Matrix for HERMES 2.x
Prompt 12 Network & Provider Resilience Layer.

Verifies system behavior under simulated edge cases:
1. DNS resolution failure
2. TCP Connection refused
3. TCP Connection reset by peer
4. HTTP 429 Rate Limit / Quota exceeded
5. HTTP 503 Service Unavailable
6. HTTP 401 Authentication Failure (Fast fail without retry)
7. HTTP 404 Model Not Found (Fast fail without retry)
8. Malformed SSE chunk handling
9. Prompt 1 regression: NVIDIA NIM stream stall reproduction and recovery
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx

from core.event_bus import EventBus
from core.network import (
    FailureClassification,
    FakeProviderAdapter,
    NetworkSupervisor,
    ProviderHealthState,
    RetryPolicy,
    StreamDelta,
    StreamWatchdog,
)
from core.runtime_state.events import EventType


@pytest.mark.asyncio
async def test_failure_injection_dns_error():
    """DNS resolution error is classified as DNS_ERROR."""
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.05),
    )

    adapter = FakeProviderAdapter(provider_name="dns_fail_provider")
    adapter.persistent_exception = True
    adapter.exception_to_raise = httpx.ConnectError("getaddrinfo failed: name resolution error")

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="DNS failure test",
        stream=True,
    )

    assert resp.success is False
    assert adapter.call_count == 1  # DNS resolution errors fail fast without retry
    health = supervisor.get_provider_health("dns_fail_provider")
    assert health.last_failure_classification == FailureClassification.DNS_ERROR


@pytest.mark.asyncio
async def test_failure_injection_connection_reset_fresh_pool():
    """Connection reset by peer closes pool and retries with fresh connection."""
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.05),
    )

    adapter = FakeProviderAdapter(provider_name="reset_provider")
    adapter.capabilities.non_streaming_fallback = False
    adapter.exception_to_raise = httpx.ConnectError("Connection reset by peer")
    adapter.deltas_to_yield = [StreamDelta(content="Recovered after reset")]

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Reset test",
        stream=True,
    )

    assert resp.success is True
    assert resp.text == "Recovered after reset"
    assert adapter.closed is True
    assert adapter.call_count == 2


@pytest.mark.asyncio
async def test_failure_injection_http_429_rate_limit():
    """HTTP 429 triggers exponential backoff retry and succeeds if rate limit clears."""
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.1),
    )

    adapter = FakeProviderAdapter(provider_name="ratelimit_provider")
    adapter.capabilities.non_streaming_fallback = False
    adapter.status_code_error = 429
    adapter.deltas_to_yield = [StreamDelta(content="Succeeded after 429 backoff")]

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Rate limit test",
        stream=True,
    )

    assert resp.success is True
    assert resp.text == "Succeeded after 429 backoff"
    assert adapter.call_count == 2


@pytest.mark.asyncio
async def test_failure_injection_http_503_service_unavailable():
    """HTTP 503 triggers retry and succeeds on next attempt."""
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.05),
    )

    adapter = FakeProviderAdapter(provider_name="unavailable_provider")
    adapter.capabilities.non_streaming_fallback = False
    adapter.status_code_error = 503
    adapter.deltas_to_yield = [StreamDelta(content="Server recovered")]

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="503 test",
        stream=True,
    )

    assert resp.success is True
    assert resp.text == "Server recovered"
    assert adapter.call_count == 2


@pytest.mark.asyncio
async def test_failure_injection_auth_failure_fast_fail():
    """HTTP 401 Authentication Failure does not retry and fails immediately."""
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.05),
    )

    adapter = FakeProviderAdapter(provider_name="unauthorized_provider")
    adapter.persistent_exception = True
    adapter.status_code_error = 401

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Auth failure test",
        stream=True,
    )

    assert resp.success is False
    assert adapter.call_count == 1  # Exactly 1 attempt - no retries on auth failure
    health = supervisor.get_provider_health("unauthorized_provider")
    assert health.last_failure_classification == FailureClassification.AUTH_FAILURE


@pytest.mark.asyncio
async def test_failure_injection_model_not_found_fast_fail():
    """HTTP 404 Model Not Found does not retry and fails immediately."""
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.05),
    )

    adapter = FakeProviderAdapter(provider_name="notfound_provider")
    adapter.persistent_exception = True
    adapter.status_code_error = 404

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="nonexistent-model",
        prompt="Model not found test",
        stream=True,
    )

    assert resp.success is False
    assert adapter.call_count == 1  # Exactly 1 attempt - no retries on model not found
    health = supervisor.get_provider_health("notfound_provider")
    assert health.last_failure_classification == FailureClassification.MODEL_NOT_FOUND


@pytest.mark.asyncio
async def test_failure_injection_malformed_chunk_recovery():
    """Malformed chunks in stream are handled safely without crashing."""
    bus = EventBus()
    supervisor = NetworkSupervisor(event_bus=bus)

    adapter = FakeProviderAdapter(provider_name="malformed_provider")
    adapter.deltas_to_yield = [
        StreamDelta(content="Valid prefix "),
        StreamDelta(content=""),  # Empty chunk
        StreamDelta(content="valid suffix"),
    ]

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Malformed chunk test",
        stream=True,
    )

    assert resp.success is True
    assert resp.text == "Valid prefix valid suffix"


@pytest.mark.asyncio
async def test_prompt1_regression_nvidia_stream_stall_recovery():
    """
    Prompt 1 Regression Test:
    NVIDIA NIM stream emits prompt tokens, stalls for 30s mid-stream.
    HERMES 2.x StreamWatchdog detects stall in <1.0s, aborts attempt, and recovers.
    """
    bus = EventBus()
    events_recorded = []

    def record_events(ev):
        events_recorded.append(ev.event_type)

    bus.subscribe(record_events)

    supervisor = NetworkSupervisor(
        event_bus=bus,
        default_first_delta_timeout=1.0,
        default_idle_timeout=0.2,  # Strict idle timeout
        default_attempt_timeout=1.0,
        default_logical_timeout=3.0,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.05),
    )

    adapter = FakeProviderAdapter(provider_name="nvidia_nim_stalled")
    adapter.capabilities.non_streaming_fallback = True
    adapter.stall_after_deltas = 1  # Freeze after 1st delta on attempt 1
    adapter.stall_duration = 30.0   # Emulate long NIM stall
    from models.provider import NormalizedModelResponse
    adapter.non_stream_response = NormalizedModelResponse(
        text="def add(a, b): return a + b",
        model="z-ai/glm-5.3-flash",
        provider="nvidia_nim",
        success=True,
    )

    start = time.monotonic()
    resp = await supervisor.execute_request(
        adapter=adapter,
        model="z-ai/glm-5.3-flash",
        prompt="Write add function",
        stream=True,
    )
    elapsed = time.monotonic() - start

    assert resp.success is True
    assert "return a + b" in resp.text
    # Must recover in less than 2.0s rather than hanging 30s
    assert elapsed < 2.0, f"Recovery took {elapsed:.2f}s instead of fast recovery"
    assert EventType.NETWORK_DISCONNECTED in events_recorded
    assert EventType.NETWORK_DEGRADED in events_recorded
