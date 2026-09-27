# tests/test_prompt12_never_hang.py
"""
The 10 Mandatory "Never Hang" Tests for HERMES 2.x
Prompt 12 Network / Provider Resilience & Zero-Silent-Hang Hardening.

Verifies:
1. Simulated infinite hang (HTTP 200 without bytes)
2. Mid-stream freeze (inter-delta stall)
3. Infinite connect loop (bounded retries)
4. Fallback hang (bounded non-streaming timeout)
5. T2 Critic stall
6. T3 Judge stall
7. Health probe freeze
8. Cancel during retry backoff
9. Compaction during retry lifecycle
10. TUI exception isolation during network event emission
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
)
from core.runtime_state.events import EventSeverity, EventType, HermesEvent


# ==============================================================================
# Test 1: Simulated Infinite Hang (HTTP 200 without bytes / TTFT stall)
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_simulated_infinite_hang():
    """
    Scenario: Provider accepts TCP connection and HTTP 200, but produces no bytes.
    Watchdog must detect first-delta timeout and abort request cleanly without hanging.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        default_first_delta_timeout=0.3,
        default_idle_timeout=0.5,
        default_attempt_timeout=1.0,
        default_logical_timeout=2.0,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    adapter = FakeProviderAdapter(provider_name="hang_provider")
    adapter.first_delta_delay = 5.0  # Emulate model hanging before emitting first delta
    adapter.deltas_to_yield = [StreamDelta(content="Never delivered")]

    start = time.monotonic()
    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Infinite hang test",
        stream=True,
    )
    elapsed = time.monotonic() - start

    assert resp.success is False
    assert "stall" in resp.error.lower() or "timeout" in resp.error.lower() or "first_delta" in resp.error.lower()
    assert elapsed < 1.5, f"Request hung for {elapsed:.2f}s instead of aborting promptly"


# ==============================================================================
# Test 2: Mid-Stream Freeze (Inter-delta stall)
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_mid_stream_freeze():
    """
    Scenario: Model sends 2 tokens, then freezes mid-stream indefinitely.
    Watchdog must detect inter-delta stall and abort request cleanly.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        default_first_delta_timeout=1.0,
        default_idle_timeout=0.3,
        default_attempt_timeout=1.0,
        default_logical_timeout=2.0,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    adapter = FakeProviderAdapter(provider_name="freeze_provider")
    adapter.deltas_to_yield = [
        StreamDelta(content="Partial "),
        StreamDelta(content="chunk "),
    ]
    adapter.stall_after_deltas = 1  # Freeze after first delta
    adapter.stall_duration = 5.0

    start = time.monotonic()
    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Freeze test",
        stream=True,
    )
    elapsed = time.monotonic() - start

    assert resp.success is False
    assert "stall" in resp.error.lower() or "timeout" in resp.error.lower()
    assert elapsed < 1.5, f"Request took {elapsed:.2f}s instead of aborting on stall"


# ==============================================================================
# Test 3: Infinite Connect Loop (Bounded Retries)
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_infinite_connect_loop():
    """
    Scenario: Network is persistently unreachable or refusing connection.
    Supervisor must cap attempts at max_attempts (3) and fail definitively without infinite loop.
    """
    bus = EventBus()
    policy = RetryPolicy(max_attempts=3, base_delay=0.05, max_delay=0.1)
    supervisor = NetworkSupervisor(event_bus=bus, retry_policy=policy)

    adapter = FakeProviderAdapter(provider_name="unreachable_provider")
    adapter.persistent_exception = True
    # Always raise connection refused
    adapter.exception_to_raise = httpx.ConnectError("Connection refused")

    start = time.monotonic()
    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Connect loop test",
        stream=True,
    )
    elapsed = time.monotonic() - start

    assert resp.success is False
    assert adapter.call_count == 3
    assert elapsed < 2.0, f"Connect loop took {elapsed:.2f}s, expected fast failure"


# ==============================================================================
# Test 4: Fallback Hang (Bounded non-streaming fallback timeout)
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_fallback_hang():
    """
    Scenario: Streaming fails, fallback to non-streaming is attempted, but non-stream also hangs.
    Supervisor must enforce hard timeout on fallback and return failure without hanging.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        default_attempt_timeout=0.3,
        default_logical_timeout=1.0,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.05),
    )

    adapter = FakeProviderAdapter(provider_name="hang_fallback_provider")
    adapter.capabilities.non_streaming_fallback = True
    adapter.exception_to_raise = httpx.ReadTimeout("Stream broke")
    adapter.connect_delay = 5.0  # Non-streaming attempt hangs for 5 seconds

    start = time.monotonic()
    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Fallback hang test",
        stream=True,
    )
    elapsed = time.monotonic() - start

    assert resp.success is False
    assert elapsed < 1.5, f"Fallback hung for {elapsed:.2f}s"


# ==============================================================================
# Test 5: T2 Critic Stall
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_t2_critic_stall():
    """
    Scenario: Tier 2 Critic evaluation model hangs during review turn.
    Supervisor bounds T2 generation and returns failure within budget.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        default_attempt_timeout=0.3,
        default_logical_timeout=0.8,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    t2_adapter = FakeProviderAdapter(provider_name="ollama_t2")
    t2_adapter.connect_delay = 5.0

    start = time.monotonic()
    resp = await supervisor.execute_request(
        adapter=t2_adapter,
        model="gpt-oss:120b-cloud",
        prompt="Review T1 evidence and identify discrepancies",
        stream=False,
    )
    elapsed = time.monotonic() - start

    assert resp.success is False
    assert elapsed < 1.5, f"T2 Critic request hung for {elapsed:.2f}s"


# ==============================================================================
# Test 6: T3 Judge Stall
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_t3_judge_stall():
    """
    Scenario: Tier 3 Judge model hangs during escalation adjudication.
    Supervisor bounds T3 call and enforces timeout without freezing system.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        default_attempt_timeout=0.3,
        default_logical_timeout=0.8,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    t3_adapter = FakeProviderAdapter(provider_name="ollama_t3")
    t3_adapter.first_delta_delay = 5.0

    start = time.monotonic()
    resp = await supervisor.execute_request(
        adapter=t3_adapter,
        model="nemotron-3-ultra:cloud",
        prompt="Adjudicate disagreement between T1 and T2",
        stream=True,
    )
    elapsed = time.monotonic() - start

    assert resp.success is False
    assert elapsed < 1.5, f"T3 Judge request hung for {elapsed:.2f}s"


# ==============================================================================
# Test 7: Health Probe Freeze
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_health_probe_freeze():
    """
    Scenario: Provider liveness/readiness probe hangs indefinitely on frozen socket.
    bounded_health_probe must strictly enforce 2.0s limit and return False.
    """
    async def frozen_probe():
        await asyncio.sleep(60.0)
        return True

    start = time.monotonic()
    is_live = await bounded_health_probe(frozen_probe, timeout_seconds=0.2)
    elapsed = time.monotonic() - start

    assert is_live is False
    assert elapsed < 0.6, f"Health probe hung for {elapsed:.2f}s"


# ==============================================================================
# Test 8: Cancel During Retry Backoff
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_cancel_during_backoff():
    """
    Scenario: User cancels mission while request is sleeping during retry backoff.
    Supervisor must abort sleep immediately upon cancellation event.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=5.0),  # 5s sleep
    )

    adapter = FakeProviderAdapter(provider_name="cancel_provider")
    adapter.exception_to_raise = httpx.ConnectError("Transient network drop")

    cancel_event = asyncio.Event()

    async def cancel_soon():
        await asyncio.sleep(0.1)
        cancel_event.set()

    asyncio.create_task(cancel_soon())

    start = time.monotonic()
    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Cancel during backoff test",
        cancel_event=cancel_event,
        stream=True,
    )
    elapsed = time.monotonic() - start

    assert resp.success is False
    assert "cancel" in resp.error.lower()
    assert elapsed < 1.0, f"Cancel did not interrupt sleep promptly ({elapsed:.2f}s)"


# ==============================================================================
# Test 9: Context Compaction During Retry Lifecycle
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_compaction_during_retry():
    """
    Scenario: Context engine triggers microcompaction while request is in retry lifecycle.
    Network request and state reduction do not deadlock.
    """
    bus = EventBus()
    supervisor = NetworkSupervisor(
        event_bus=bus,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.1),
    )

    adapter = FakeProviderAdapter(provider_name="compaction_provider")
    adapter.capabilities.non_streaming_fallback = False
    adapter.exception_to_raise = httpx.ConnectError("Temporary reset")
    adapter.deltas_to_yield = [StreamDelta(content="Compacted and recovered")]

    async def emit_compaction_during_backoff():
        await asyncio.sleep(0.05)
        bus.publish(
            HermesEvent(
                event_type=EventType.MICROCOMPACTION_STARTED,
                source="context_engine",
                payload={"target_tokens": 4000},
            )
        )
        await asyncio.sleep(0.05)
        bus.publish(
            HermesEvent(
                event_type=EventType.MICROCOMPACTION_COMPLETED,
                source="context_engine",
                payload={"tokens_freed": 1200},
            )
        )

    asyncio.create_task(emit_compaction_during_backoff())

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="Prompt that survives compaction",
        stream=True,
    )

    assert resp.success is True
    assert resp.text == "Compacted and recovered"


# ==============================================================================
# Test 10: TUI Exception Isolation During Network Event Emission
# ==============================================================================
@pytest.mark.asyncio
async def test_never_hang_tui_exception_isolation():
    """
    Scenario: TUI UI event subscriber raises an unhandled exception when receiving network events.
    NetworkSupervisor must swallow subscriber error, prevent crash, and complete request.
    """
    bus = EventBus()

    # Broken TUI subscriber that throws on every event
    def broken_tui_subscriber(event):
        raise RuntimeError("TUI rendering buffer crashed on network event!")

    bus.subscribe(broken_tui_subscriber)

    supervisor = NetworkSupervisor(event_bus=bus)
    adapter = FakeProviderAdapter(provider_name="tui_isolation_provider")
    adapter.deltas_to_yield = [StreamDelta(content="TUI survived")]

    resp = await supervisor.execute_request(
        adapter=adapter,
        model="fake-model",
        prompt="TUI isolation test",
        stream=True,
    )

    assert resp.success is True
    assert resp.text == "TUI survived"
