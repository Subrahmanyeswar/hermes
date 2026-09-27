# tests/test_network_resilience.py
"""
Unit and integration tests for HERMES 2.x Network Resilience Layer.
Tests StreamWatchdog, RetryPolicy, ProviderHealthState, Adapters,
NetworkSupervisor, Tool Replay Safety, and Deadline Budgeting.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx

from core.event_bus import EventBus
from core.network import (
    DeadlineBudget,
    FailureClassification,
    FakeProviderAdapter,
    NetworkSupervisor,
    ProviderCapabilities,
    ProviderHealthState,
    RequestPhase,
    RetryPolicy,
    StreamDelta,
    StreamWatchdog,
    bounded_health_probe,
    classify_httpx_exception,
)
from core.network.health import CircuitState
from core.runtime_state.events import EventType


# ==============================================================================
# 1. StreamWatchdog Tests
# ==============================================================================

def test_watchdog_first_delta_timeout():
    """Watchdog flags FIRST_DELTA_TIMEOUT when first delta does not arrive."""
    watchdog = StreamWatchdog(first_delta_timeout=1.0, idle_timeout=2.0)
    watchdog.start(start_time=100.0)

    # At 100.5s: Not timed out yet
    assert watchdog.check_stall(now=100.5) is None

    # At 101.5s: First delta timeout exceeded
    stall = watchdog.check_stall(now=101.5)
    assert stall is not None
    assert "FIRST_DELTA_TIMEOUT" in stall


def test_watchdog_inter_delta_stall():
    """Watchdog flags INTER_DELTA_STALL when streaming pauses beyond idle_timeout."""
    watchdog = StreamWatchdog(first_delta_timeout=5.0, idle_timeout=2.0)
    watchdog.start(start_time=100.0)

    # First delta arrives at 101.0
    watchdog.record_first_delta(now=101.0)
    assert watchdog.check_stall(now=101.5) is None

    # Subsequent delta at 102.0
    watchdog.record_delta(delta_len=5, now=102.0)
    assert watchdog.check_stall(now=103.0) is None

    # Gap from 102.0 to 104.5s (> 2.0s idle)
    stall = watchdog.check_stall(now=104.5)
    assert stall is not None
    assert "INTER_DELTA_STALL" in stall


def test_watchdog_healthy_streaming():
    """Watchdog remains healthy as long as deltas arrive within interval."""
    watchdog = StreamWatchdog(first_delta_timeout=2.0, idle_timeout=2.0)
    watchdog.start(start_time=0.0)
    watchdog.record_first_delta(now=0.5)

    for t in [1.0, 1.5, 2.0, 2.5, 3.0]:
        watchdog.record_delta(delta_len=4, now=t)
        assert watchdog.check_stall(now=t + 0.2) is None


# ==============================================================================
# 2. RetryPolicy Tests
# ==============================================================================

def test_retry_policy_retryable_classification():
    """RetryPolicy allows retry for transient network errors."""
    policy = RetryPolicy(max_attempts=3, base_delay=0.5)

    # Retryable errors
    assert policy.should_retry(1, FailureClassification.CONNECT_TIMEOUT, remaining_budget=10.0) is True
    assert policy.should_retry(1, FailureClassification.READ_TIMEOUT, remaining_budget=10.0) is True
    assert policy.should_retry(1, FailureClassification.STREAM_STALL, remaining_budget=10.0) is True
    assert policy.should_retry(1, FailureClassification.HTTP_5XX, remaining_budget=10.0) is True
    assert policy.should_retry(1, FailureClassification.HTTP_429, remaining_budget=10.0) is True

    # Non-retryable errors
    assert policy.should_retry(1, FailureClassification.AUTH_FAILURE, remaining_budget=10.0) is False
    assert policy.should_retry(1, FailureClassification.MODEL_NOT_FOUND, remaining_budget=10.0) is False
    assert policy.should_retry(1, FailureClassification.INVALID_REQUEST, remaining_budget=10.0) is False
    assert policy.should_retry(1, FailureClassification.CANCELLED, remaining_budget=10.0) is False


def test_retry_policy_max_attempts():
    """RetryPolicy halts once attempt index reaches max_attempts."""
    policy = RetryPolicy(max_attempts=3)
    assert policy.should_retry(1, FailureClassification.CONNECT_TIMEOUT, remaining_budget=10.0) is True
    assert policy.should_retry(2, FailureClassification.CONNECT_TIMEOUT, remaining_budget=10.0) is True
    assert policy.should_retry(3, FailureClassification.CONNECT_TIMEOUT, remaining_budget=10.0) is False


def test_retry_policy_budget_exhaustion():
    """RetryPolicy does not retry if remaining budget cannot cover delay + min attempt budget."""
    policy = RetryPolicy(max_attempts=3, base_delay=2.0, min_attempt_budget=2.0)
    # Delay is ~2.0s, min attempt budget is 2.0s => requires at least 4.0s
    assert policy.should_retry(1, FailureClassification.CONNECT_TIMEOUT, remaining_budget=1.0) is False
    assert policy.should_retry(1, FailureClassification.CONNECT_TIMEOUT, remaining_budget=5.0) is True


def test_retry_policy_exponential_backoff_and_jitter():
    """Exponential delay grows exponentially and applies bounded jitter."""
    policy = RetryPolicy(base_delay=1.0, max_delay=10.0, backoff_factor=2.0, jitter_factor=0.0)
    assert policy.compute_delay(1) == 1.0
    assert policy.compute_delay(2) == 2.0
    assert policy.compute_delay(3) == 4.0
    assert policy.compute_delay(4) == 8.0
    assert policy.compute_delay(5) == 10.0  # capped at max_delay


# ==============================================================================
# 3. ProviderHealthState & Circuit Breaker Tests
# ==============================================================================

def test_circuit_breaker_trips_on_threshold():
    """ProviderHealthState trips to OPEN when failures reach threshold."""
    health = ProviderHealthState(provider_name="test_provider", failure_threshold=3, cooldown_seconds=5.0)
    assert health.circuit_state == CircuitState.CLOSED
    assert health.can_attempt() is True

    health.record_failure("error 1", FailureClassification.CONNECT_TIMEOUT)
    assert health.circuit_state == CircuitState.CLOSED
    health.record_failure("error 2", FailureClassification.CONNECT_TIMEOUT)
    assert health.circuit_state == CircuitState.CLOSED

    health.record_failure("error 3", FailureClassification.CONNECT_TIMEOUT)
    assert health.circuit_state == CircuitState.OPEN
    assert health.can_attempt() is False


def test_circuit_breaker_half_open_recovery():
    """Circuit transitions to HALF_OPEN after cooldown and recovers to CLOSED after successful probes."""
    health = ProviderHealthState(
        provider_name="test_provider",
        failure_threshold=2,
        recovery_threshold=2,
        cooldown_seconds=1.0,
    )
    # Trip circuit
    health.record_failure("err", FailureClassification.HTTP_5XX)
    health.record_failure("err", FailureClassification.HTTP_5XX)
    assert health.circuit_state == CircuitState.OPEN

    # Before cooldown
    now = time.monotonic()
    assert health.can_attempt(now=now) is False

    # After cooldown: moves to HALF_OPEN
    assert health.can_attempt(now=now + 1.1) is True
    assert health.circuit_state == CircuitState.HALF_OPEN

    # 1 success is not enough for recovery_threshold=2
    health.record_success()
    assert health.circuit_state == CircuitState.HALF_OPEN

    # 2nd success recovers circuit to CLOSED
    health.record_success()
    assert health.circuit_state == CircuitState.CLOSED
    assert health.is_healthy is True


# ==============================================================================
# 4. Bounded Health Probe Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_bounded_health_probe_success():
    async def ok_probe():
        return True

    res = await bounded_health_probe(ok_probe, timeout_seconds=1.0)
    assert res is True


@pytest.mark.asyncio
async def test_bounded_health_probe_times_out():
    """Probe that hangs times out strictly and returns False without hanging."""
    async def hanging_probe():
        await asyncio.sleep(10.0)
        return True

    start = time.monotonic()
    res = await bounded_health_probe(hanging_probe, timeout_seconds=0.2)
    elapsed = time.monotonic() - start
    assert res is False
    assert elapsed < 0.6


# ==============================================================================
# 5. NetworkSupervisor Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_supervisor_happy_path_streaming():
    """NetworkSupervisor streams deltas, tracks progress, and returns full response."""
    bus = EventBus()
    supervisor = NetworkSupervisor(event_bus=bus)

    adapter = FakeProviderAdapter(provider_name="fake_stream")
    adapter.deltas_to_yield = [
        StreamDelta(content="HERMES "),
        StreamDelta(content="Reliability "),
        StreamDelta(content="Engine"),
    ]

    deltas_received = []

    def on_delta(delta):
        deltas_received.append(delta.content)

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Test prompt",
        stream=True,
        on_delta_callback=on_delta,
    )

    assert resp.success is True
    assert resp.text == "HERMES Reliability Engine"
    assert deltas_received == ["HERMES ", "Reliability ", "Engine"]


@pytest.mark.asyncio
async def test_supervisor_fresh_connection_retry():
    """On connection reset, supervisor closes stale pool and connects freshly."""
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.1),
    )

    adapter = FakeProviderAdapter(provider_name="fake_retry")
    adapter.capabilities.non_streaming_fallback = False
    # First attempt raises connection reset, second succeeds
    adapter.exception_to_raise = httpx.ConnectError("Connection reset by peer")
    adapter.deltas_to_yield = [StreamDelta(content="Recovered")]

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Test retry",
        stream=True,
    )

    assert resp.success is True
    assert resp.text == "Recovered"
    assert adapter.closed is True  # aclose() called before retry
    assert adapter.call_count == 2


@pytest.mark.asyncio
async def test_supervisor_non_streaming_fallback():
    """When streaming fails, supervisor falls back to non-streaming execution."""
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.1),
    )

    adapter = FakeProviderAdapter(provider_name="fake_fallback")
    adapter.capabilities.non_streaming_fallback = True
    adapter.exception_to_raise = httpx.ReadTimeout("Stream read timeout")
    from models.provider import NormalizedModelResponse
    adapter.non_stream_response = NormalizedModelResponse(
        text="Fallback non-streaming success",
        model="fake-model",
        provider="fake_fallback",
        success=True,
    )

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Test fallback",
        stream=True,
    )

    assert resp.success is True
    assert resp.text == "Fallback non-streaming success"


@pytest.mark.asyncio
async def test_supervisor_tool_replay_safety():
    """Supervisor filters out tool calls that were already executed in the same turn."""
    bus = EventBus()
    supervisor = NetworkSupervisor(event_bus=bus)

    # Register tool call as already executed
    supervisor.register_executed_tool_call(tool_call_id="call_dup_1", turn_id="turn_1")

    adapter = FakeProviderAdapter(provider_name="fake_tools")
    adapter.deltas_to_yield = [
        StreamDelta(
            content="Invoking tools",
            tool_calls=[
                {"index": 0, "id": "call_dup_1", "function": {"name": "test_tool", "arguments": "{}"}},
                {"index": 1, "id": "call_new_2", "function": {"name": "test_tool2", "arguments": "{}"}},
            ],
        )
    ]

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Execute tools",
        turn_id="turn_1",
        stream=True,
    )

    assert resp.success is True
    # Only call_new_2 should remain; call_dup_1 should be suppressed
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["id"] == "call_new_2"
