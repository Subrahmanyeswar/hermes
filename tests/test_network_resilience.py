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


# ==============================================================================
# 6. Forensic Edge-Case Hardening Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_legitimate_slow_first_response():
    """
    Edge Case #1: Boundary testing around first-delta timeout.
    A response that arrives just before the threshold is legitimate progress,
    whereas one exceeding the threshold is aborted as a stall.
    """
    bus = EventBus()
    # Case A: Threshold = 0.5s, delay = 0.2s -> legitimate slow response (PASS)
    supervisor = NetworkSupervisor(
        event_bus=bus,
        default_first_delta_timeout=0.5,
        default_idle_timeout=1.0,
        default_attempt_timeout=2.0,
        default_logical_timeout=3.0,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    adapter_ok = FakeProviderAdapter(provider_name="slow_ok")
    adapter_ok.first_delta_delay = 0.2
    adapter_ok.deltas_to_yield = [StreamDelta(content="Legitimately slow but arrived")]

    resp_ok = await supervisor.execute_request(
        adapter=adapter_ok,
        model="fake-model",
        prompt="Slow test",
        stream=True,
    )
    assert resp_ok.success is True
    assert resp_ok.text == "Legitimately slow but arrived"

    # Case B: Threshold = 0.2s, delay = 0.6s -> exceeds boundary, aborted as stall
    supervisor_stall = NetworkSupervisor(
        event_bus=bus,
        default_first_delta_timeout=0.2,
        default_idle_timeout=0.5,
        default_attempt_timeout=1.0,
        default_logical_timeout=2.0,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    adapter_stall = FakeProviderAdapter(provider_name="slow_stall")
    adapter_stall.first_delta_delay = 0.6
    adapter_stall.deltas_to_yield = [StreamDelta(content="Never delivered")]

    resp_stall = await supervisor_stall.execute_request(
        adapter=adapter_stall,
        model="fake-model",
        prompt="Stall test",
        stream=True,
    )
    assert resp_stall.success is False
    assert "stall" in resp_stall.error.lower() or "timeout" in resp_stall.error.lower()


@pytest.mark.asyncio
async def test_reasoning_model_deltas_reset_watchdog():
    """
    Reasoning models emitting reasoning_content deltas count as active progress
    and continuously reset the watchdog idle timer.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        default_first_delta_timeout=1.0,
        default_idle_timeout=0.4,
        default_attempt_timeout=2.0,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    adapter = FakeProviderAdapter(provider_name="reasoning_model")
    # Emit 4 reasoning tokens every 0.15s (gap < 0.4s idle timeout) then final content
    adapter.inter_delta_delay = 0.15
    adapter.deltas_to_yield = [
        StreamDelta(reasoning_content="Let's "),
        StreamDelta(reasoning_content="think "),
        StreamDelta(reasoning_content="step "),
        StreamDelta(reasoning_content="by step. "),
        StreamDelta(content="The answer is 42."),
    ]

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="deepseek-r1-mock",
        prompt="Reasoning test",
        stream=True,
    )

    assert resp.success is True
    assert resp.text == "The answer is 42."


@pytest.mark.asyncio
async def test_tool_call_semantic_action_deduplication():
    """
    Tool replay safety works for both same tool_call_id AND different tool_call_id
    with identical semantic action, while distinct actions are NOT suppressed.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(event_bus=bus)

    # 1. Register existing tool action: write_file path="auth.py"
    supervisor.register_executed_tool_call(
        tool_call_id="call_initial_1",
        turn_id="turn_42",
        action_key='write_file:{"path": "auth.py"}',
    )

    # Check 1: Same tool call ID is recognized as executed
    assert supervisor.is_tool_call_executed("call_initial_1", turn_id="turn_42") is True

    # Check 2: Different tool call ID with identical semantic action is recognized as executed
    assert supervisor.is_tool_call_executed(
        "call_retried_diff_id",
        turn_id="turn_42",
        action_key='write_file:{"path": "auth.py"}',
    ) is True

    # Check 3: Distinct semantic action is NOT recognized as executed (no over-blocking)
    assert supervisor.is_tool_call_executed(
        "call_retried_diff_id",
        turn_id="turn_42",
        action_key='write_file:{"path": "config.py"}',
    ) is False


@pytest.mark.asyncio
async def test_partial_response_fallback_clean_assembly():
    """
    When streaming fails after partial deltas, non-stream fallback starts cleanly
    and does not duplicate the partial stream chunks into the final response.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        default_idle_timeout=0.2,
        default_attempt_timeout=1.0,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.05),
    )

    adapter = FakeProviderAdapter(provider_name="partial_fallback")
    adapter.capabilities.non_streaming_fallback = True
    adapter.deltas_to_yield = [StreamDelta(content="PARTIAL_A_"), StreamDelta(content="PARTIAL_B_")]
    adapter.stall_after_deltas = 1  # Fails mid-stream
    adapter.stall_duration = 5.0
    from models.provider import NormalizedModelResponse
    adapter.non_stream_response = NormalizedModelResponse(
        text="CLEAN_FALLBACK_FULL_TEXT",
        model="fake-model",
        provider="partial_fallback",
        success=True,
    )

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Partial fallback test",
        stream=True,
    )

    assert resp.success is True
    # Must NOT be "PARTIAL_A_CLEAN_FALLBACK_FULL_TEXT"
    assert resp.text == "CLEAN_FALLBACK_FULL_TEXT"


@pytest.mark.asyncio
async def test_provider_circuit_breaker_isolation():
    """
    If Provider A's circuit trips to OPEN, Provider B's requests remain completely unblocked.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(event_bus=bus)

    health_a = supervisor.get_provider_health("provider_a")
    # Trip provider A
    for _ in range(3):
        health_a.record_failure("Outage", FailureClassification.HTTP_5XX)
    assert health_a.circuit_state == "OPEN"
    assert health_a.can_attempt() is False

    # Provider B is healthy
    adapter_b = FakeProviderAdapter(provider_name="provider_b")
    adapter_b.deltas_to_yield = [StreamDelta(content="Provider B works")]

    resp_b = await supervisor.execute_request(
        adapter=adapter_b,
        model="model-b",
        prompt="Test provider B",
        stream=True,
    )

    assert resp_b.success is True
    assert resp_b.text == "Provider B works"


@pytest.mark.asyncio
async def test_tool_only_response_and_empty_response():
    """
    Tool-only responses (empty text, valid tool call) are valid successes.
    Empty responses (no text, no tool call, no finish reason) are classified as failures.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(event_bus=bus)

    # Case 1: Tool only (empty text, valid tool call)
    adapter_tool = FakeProviderAdapter(provider_name="tool_only_provider")
    adapter_tool.deltas_to_yield = [
        StreamDelta(
            content="",
            tool_calls=[{"index": 0, "id": "c_tool_1", "function": {"name": "read_file", "arguments": '{"path": "x"}'}}],
            finish_reason="tool_calls",
        )
    ]
    resp_tool = await supervisor.execute_request(
        adapter=adapter_tool,
        model="fake-model",
        prompt="Tool only test",
        stream=True,
    )
    assert resp_tool.success is True
    assert len(resp_tool.tool_calls) == 1
    assert resp_tool.tool_calls[0]["name"] == "read_file"

    # Case 2: Completely empty stream with no tool calls and no finish reason
    adapter_empty = FakeProviderAdapter(provider_name="empty_provider")
    adapter_empty.deltas_to_yield = [StreamDelta(content="", finish_reason=None)]
    resp_empty = await supervisor.execute_request(
        adapter=adapter_empty,
        model="fake-model",
        prompt="Empty test",
        stream=True,
    )
    assert resp_empty.success is False
    assert "without producing any output" in resp_empty.error or "stall" in resp_empty.error.lower()


@pytest.mark.asyncio
async def test_secret_redaction_in_network_events():
    """
    Network events redact sensitive authorization credentials automatically.
    """
    from core.runtime_state.events import HermesEvent, EventType

    event = HermesEvent(
        event_type=EventType.NETWORK_REQUEST_CREATED,
        source="network_supervisor",
        payload={
            "headers": {"Authorization": "Bearer SECRET_KEY_99999", "Content-Type": "application/json"},
            "api_key": "SUPER_SECRET_TOKEN",
            "model": "z-ai/glm-5.3-flash",
        },
    )

    payload_dict = event.to_dict()["payload"]
    assert "SECRET_KEY_99999" not in str(payload_dict)
    assert "SUPER_SECRET_TOKEN" not in str(payload_dict)
    assert payload_dict["api_key"] == "[REDACTED_SECRET]"


@pytest.mark.asyncio
async def test_concurrent_requests_no_task_leak():
    """
    Executing 30 concurrent requests under mixed success/failure conditions
    does not leak background tasks.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.01),
    )

    tasks_before = len([t for t in asyncio.all_tasks() if not t.done()])

    async def single_req(i: int):
        adapter = FakeProviderAdapter(provider_name=f"p_{i % 3}")
        if i % 2 == 0:
            adapter.deltas_to_yield = [StreamDelta(content=f"res_{i}")]
        else:
            adapter.exception_to_raise = httpx.ConnectError("Simulated error")
        return await supervisor.execute_request(
            adapter=adapter,
            model="fake-model",
            prompt=f"Task {i}",
            stream=True,
        )

    results = await asyncio.gather(*(single_req(i) for i in range(30)), return_exceptions=True)
    assert len(results) == 30

    await asyncio.sleep(0.05)
    tasks_after = len([t for t in asyncio.all_tasks() if not t.done()])

    # Current task plus test runner task may exist, but no systematic growth
    assert tasks_after <= tasks_before + 2


@pytest.mark.asyncio
async def test_state_replay_network_lifecycle():
    """
    Replaying canonical sequence through StateReducer deterministically reproduces matching NetworkState.
    """
    from core.runtime_state.events import HermesEvent, EventType
    from core.runtime_state.store import StateStore
    from core.runtime_state.reducer import StateReducer
    from core.runtime_state.models import NetworkConnectivity

    store = StateStore(mission_id="m_replay")
    events = [
        HermesEvent(event_type=EventType.NETWORK_REQUEST_CREATED, mission_id="m_replay", payload={"request_id": "req_1", "provider": "nvidia_nim"}),
        HermesEvent(event_type=EventType.NETWORK_CONNECTING, mission_id="m_replay", payload={"request_id": "req_1", "attempt_id": "att_1"}),
        HermesEvent(event_type=EventType.NETWORK_CONNECTED, mission_id="m_replay", payload={"request_id": "req_1"}),
        HermesEvent(event_type=EventType.NETWORK_STREAMING, mission_id="m_replay", payload={"request_id": "req_1"}),
        HermesEvent(event_type=EventType.REQUEST_FIRST_DELTA, mission_id="m_replay", payload={"ttft_seconds": 0.42}),
        HermesEvent(event_type=EventType.REQUEST_PROGRESS, mission_id="m_replay", payload={"deltas_count": 10}),
        HermesEvent(event_type=EventType.NETWORK_DISCONNECTED, mission_id="m_replay", payload={"error": "Reset"}),
        HermesEvent(event_type=EventType.NETWORK_RECONNECTING, mission_id="m_replay", payload={"attempt_index": 2}),
        HermesEvent(event_type=EventType.NETWORK_RECOVERED, mission_id="m_replay", payload={"request_id": "req_1"}),
    ]

    for ev in events:
        store.apply_event(ev)

    snap = store.get_snapshot()
    assert snap.network.connectivity == NetworkConnectivity.RECOVERED
    assert snap.network.request_id == "req_1"
    assert snap.network.ttft_ms == 420.0
    assert snap.network.deltas_received == 10
    assert snap.network.retry_count == 1
