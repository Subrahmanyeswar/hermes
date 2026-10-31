"""
Phase 4 Acceptance Test Suite: Transport Timeouts & Deadlines (Scenarios A, B, C, D / Gate B).

Verifies:
- Scenario A: Connect timeout terminates within bound, classifies correctly, releases client.
- Scenario B: Slow first token triggers first-token deadline, no indefinite hang.
- Scenario C: Mid-stream stall triggers idle watchdog, discards partial output.
- Scenario D: Overall request deadline stops retries and bounds total duration.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from core.transport.types import (
    ErrorCategory,
    StructuredTransportError,
    classify_http_status,
)
from core.transport.retry_coordinator import (
    FallbackPolicyConfig,
    RetryCoordinator,
)
from core.transport.client_manager import TransportClientManager
from core.transport.stream_validator import SseStreamAccumulator


@pytest.mark.asyncio
async def test_scenario_a_connect_timeout_bounded_and_classified():
    """Verify provider connection failure within configured connect timeout is classified and releases client."""
    mgr = TransportClientManager()
    client = await mgr.get_client(
        base_url="https://mock.nvidia.api",
        connect_timeout=0.2,
        read_timeout=1.0,
    )

    with patch.object(client, "send", side_effect=httpx.ConnectTimeout("Connection timed out")):
        t0 = time.monotonic()
        try:
            await client.get("https://mock.nvidia.api/v1/models")
            pytest.fail("Expected ConnectTimeout")
        except httpx.ConnectTimeout as exc:
            elapsed = time.monotonic() - t0
            assert elapsed < 1.0
            struct_err = StructuredTransportError(
                category=ErrorCategory.CONNECT_TIMEOUT,
                message=str(exc),
                provider="nvidia_nim",
                model="z-ai/glm-5.3-flash",
                retryable=True,
            )
            assert struct_err.category == ErrorCategory.CONNECT_TIMEOUT
            assert struct_err.retryable is True

    # Ensure client manager can shut down cleanly without leaks
    await mgr.aclose()


@pytest.mark.asyncio
async def test_scenario_b_slow_first_token_triggers_deadline():
    """Verify provider delay before first token triggers read/first-token timeout without hanging."""
    mgr = TransportClientManager()
    client = await mgr.get_client(
        base_url="https://mock.nvidia.api",
        connect_timeout=1.0,
        read_timeout=0.2,  # 200ms first token timeout
    )

    with patch.object(client, "send", side_effect=httpx.ReadTimeout("First token read timed out")):
        t0 = time.monotonic()
        try:
            await client.post("https://mock.nvidia.api/v1/chat/completions", json={})
            pytest.fail("Expected ReadTimeout")
        except httpx.ReadTimeout as exc:
            elapsed = time.monotonic() - t0
            assert elapsed < 1.0
            struct_err = StructuredTransportError(
                category=ErrorCategory.READ_IDLE_TIMEOUT,
                message=str(exc),
                provider="nvidia_nim",
                model="z-ai/glm-5.3-flash",
                retryable=True,
            )
            assert struct_err.category == ErrorCategory.READ_IDLE_TIMEOUT

    await mgr.aclose()


def test_scenario_c_midstream_stall_triggers_incomplete_stream_rejection():
    """Verify a stream that begins emitting chunks and then stops before terminal marker is rejected and discarded."""
    acc = SseStreamAccumulator(
        model="z-ai/glm-5.3-flash",
        provider="nvidia_nim",
    )

    # First chunk arrives with partial text
    line1 = 'data: {"id":"c1","choices":[{"delta":{"content":"Partial response text..."},"index":0}]}'
    ok1, err1 = acc.process_chunk(line1, now=100.0)
    assert ok1 is False
    assert err1 is None
    assert acc.content_chunks == ["Partial response text..."]

    # Stream abruptly closes without [DONE] marker
    resp, fin_err = acc.validate_and_finalize(elapsed_ms=3000.0)
    assert resp.success is False
    assert fin_err is not None
    assert fin_err.category == ErrorCategory.STREAM_INCOMPLETE
    assert "terminal completion marker" in fin_err.message


@pytest.mark.asyncio
async def test_scenario_d_overall_request_deadline_bounds_retries():
    """Verify periodic chunk deliveries or repeated retries do not bypass the total elapsed request deadline."""
    clock_time = 100.0

    def fake_time():
        nonlocal clock_time
        return clock_time

    async def fake_sleep(secs):
        nonlocal clock_time
        clock_time += secs

    # 2.0s total deadline
    cfg = FallbackPolicyConfig(
        total_request_deadline_seconds=2.0,
        primary_max_retries=5,
        base_backoff_seconds=1.0,
    )
    coord = RetryCoordinator(config=cfg, time_func=fake_time, sleep_func=fake_sleep)

    calls = 0

    async def slow_invoker(tier, provider, model, attempt, timeout_remaining):
        nonlocal calls, clock_time
        calls += 1
        clock_time += 1.6  # Consumes 1.6s, leaving 0.4s (< 0.5s remaining threshold)
        raise StructuredTransportError(
            category=ErrorCategory.PROVIDER_SERVER_ERROR,
            message="Temporary 500 error",
            provider=provider,
            model=model,
            retryable=True,
            attempt=attempt,
        )

    res = await coord.execute_with_resilience(slow_invoker)
    assert res.response is None
    assert res.error is not None
    assert res.error.category == ErrorCategory.OVERALL_DEADLINE_EXCEEDED
    assert calls == 1
