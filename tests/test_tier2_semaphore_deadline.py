"""
Deterministic unit and integration test suite for HERMES Tier 2 Semaphore & Deadline Architecture:
- Test 1: Immediate semaphore acquisition
- Test 2: Waiting successfully while another request releases the semaphore
- Test 3: Timing out while waiting on the semaphore
- Test 4: Timing out during inference
- Test 5: Cancellation without semaphore leakage
- Test 6: Recovery after timed-out request
- Test 7: No duplicate model calls or workspace writes
"""

import asyncio
import time
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from models.ollama_client import (
    OllamaClient,
    OllamaTimeoutError,
    get_tier2_semaphore,
    reset_tier2_semaphore,
)
from models.provider import NormalizedModelResponse
from core.agent_loop.loop import AgentLoop
from core.agent_loop.types import AgentLoopConfig, AgentTurn
from core.agent_loop.observations import Observation
from core.runtime_state.events import EventType


@pytest.fixture(autouse=True)
def fresh_semaphore():
    """Ensure every test starts with a fresh single-request semaphore."""
    sem = reset_tier2_semaphore(concurrency=1)
    yield sem
    reset_tier2_semaphore(concurrency=1)


# ============================================================================
# Test 1: Immediate semaphore acquisition
# ============================================================================
@pytest.mark.asyncio
async def test_immediate_semaphore_acquisition():
    """Verify when no request holds the semaphore, acquisition is immediate and released on finish."""
    sem = asyncio.Semaphore(1)
    client = OllamaClient(semaphore=sem)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": '{"tool": "write_file", "parameters": {"path": "a.txt", "content": "1"}}',
        "total_duration": 10_000_000,
    }

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_http

        resp = await client.generate(model="gpt-oss:120b-cloud", prompt="hello", timeout_seconds=5.0)

        assert resp.success is True
        # Semaphore must be back to 1
        assert sem._value == 1


# ============================================================================
# Test 2: Waiting successfully while another request releases the semaphore
# ============================================================================
@pytest.mark.asyncio
async def test_waiting_successfully_while_another_request_releases():
    """Verify request 2 waits for request 1 to release the semaphore, then completes successfully."""
    sem = asyncio.Semaphore(1)
    client = OllamaClient(semaphore=sem)

    order = []

    async def mock_post(url, json=None, timeout=None, **kwargs):
        call_id = json.get("prompt")
        order.append(f"{call_id}_start")
        if call_id == "req1":
            await asyncio.sleep(0.15)
        else:
            await asyncio.sleep(0.05)
        order.append(f"{call_id}_end")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": f"{call_id}_done", "total_duration": 5_000_000}
        return mock_resp

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = mock_post
        mock_get_client.return_value = mock_http

        task1 = asyncio.create_task(client.generate(model="gpt-oss:120b-cloud", prompt="req1", timeout_seconds=5.0))
        await asyncio.sleep(0.02)  # Ensure task1 acquires first
        task2 = asyncio.create_task(client.generate(model="gpt-oss:120b-cloud", prompt="req2", timeout_seconds=5.0))

        r1, r2 = await asyncio.gather(task1, task2)

        assert r1.text == "req1_done"
        assert r2.text == "req2_done"
        # Strict serialization check: req1 must finish before req2 starts
        assert order == ["req1_start", "req1_end", "req2_start", "req2_end"]
        assert sem._value == 1


# ============================================================================
# Test 3: Timing out while waiting on the semaphore
# ============================================================================
@pytest.mark.asyncio
async def test_timing_out_while_waiting_on_semaphore():
    """Verify request 2 waiting for the semaphore times out within its configured deadline."""
    sem = asyncio.Semaphore(1)
    client = OllamaClient(semaphore=sem)

    req2_executed = False

    async def mock_post(url, json=None, timeout=None, **kwargs):
        nonlocal req2_executed
        call_id = json.get("prompt")
        if call_id == "req1":
            await asyncio.sleep(0.4)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": "req1_done", "total_duration": 5_000_000}
            return mock_resp
        else:
            req2_executed = True
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": "req2_done", "total_duration": 5_000_000}
            return mock_resp

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = mock_post
        mock_get_client.return_value = mock_http

        task1 = asyncio.create_task(client.generate(model="gpt-oss:120b-cloud", prompt="req1", timeout_seconds=5.0))
        await asyncio.sleep(0.02)

        t2_start = time.monotonic()
        with pytest.raises(OllamaTimeoutError) as exc_info:
            # Configured deadline is 0.1s. Request 1 holds semaphore for 0.4s.
            await client.generate(model="gpt-oss:120b-cloud", prompt="req2", timeout_seconds=0.1)
        t2_dur = time.monotonic() - t2_start

        assert "waiting for execution slot" in str(exc_info.value)
        # Total wait time must not exceed configured deadline significantly
        assert t2_dur < 0.25
        # Request 2 must never have started inference
        assert req2_executed is False

        # Wait for task1 to finish
        r1 = await task1
        assert r1.text == "req1_done"
        # Semaphore was cleanly restored
        assert sem._value == 1


# ============================================================================
# Test 4: Timing out during inference
# ============================================================================
@pytest.mark.asyncio
async def test_timing_out_during_inference():
    """Verify request that acquires semaphore but hangs during inference respects deadline and releases semaphore."""
    sem = asyncio.Semaphore(1)
    client = OllamaClient(semaphore=sem)

    async def mock_post_hang(url, json=None, timeout=None, **kwargs):
        # Simulate hung inference respecting remaining_inference_seconds timeout
        to_val = getattr(timeout, "read", 0.1) if timeout else 0.1
        await asyncio.sleep(float(to_val))
        raise httpx.TimeoutException("Inference timed out")

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = mock_post_hang
        mock_get_client.return_value = mock_http

        t0 = time.monotonic()
        with pytest.raises(OllamaTimeoutError) as exc_info:
            await client.generate(model="gpt-oss:120b-cloud", prompt="hung_req", timeout_seconds=0.1)
        dur = time.monotonic() - t0

        assert dur < 0.30
        assert "timed out" in str(exc_info.value).lower()
        # Crucial: Semaphore must be released even though inference timed out!
        assert sem._value == 1


# ============================================================================
# Test 5: Cancellation without semaphore leakage
# ============================================================================
@pytest.mark.asyncio
async def test_cancellation_without_semaphore_leakage():
    """Verify cancelling an in-flight request cleanly releases semaphore without leakage."""
    sem = asyncio.Semaphore(1)
    client = OllamaClient(semaphore=sem)

    started_event = asyncio.Event()

    async def mock_post_slow(url, json=None, timeout=None, **kwargs):
        started_event.set()
        await asyncio.sleep(1.0)
        return MagicMock()

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = mock_post_slow
        mock_get_client.return_value = mock_http

        task = asyncio.create_task(client.generate(model="gpt-oss:120b-cloud", prompt="to_cancel", timeout_seconds=5.0))
        await started_event.wait()
        assert sem._value == 0  # Currently acquired

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Crucial invariant: Semaphore must not leak upon cancellation!
        assert sem._value == 1


# ============================================================================
# Test 6: Recovery after timed-out request
# ============================================================================
@pytest.mark.asyncio
async def test_recovery_after_timed_out_request():
    """Verify after a request times out, subsequent requests proceed immediately and cleanly."""
    sem = asyncio.Semaphore(1)
    client = OllamaClient(semaphore=sem)

    # 1. Trigger timeout
    async def mock_timeout(url, json=None, timeout=None, **kwargs):
        await asyncio.sleep(0.08)
        raise httpx.TimeoutException("timeout")

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = mock_timeout
        mock_get_client.return_value = mock_http

        with pytest.raises(OllamaTimeoutError):
            await client.generate(model="gpt-oss:120b-cloud", prompt="fail", timeout_seconds=0.08)

    assert sem._value == 1

    # 2. Subsequent healthy request must succeed immediately without deadlock
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "recovered_ok", "total_duration": 1_000_000}

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_http

        res = await client.generate(model="gpt-oss:120b-cloud", prompt="healthy", timeout_seconds=2.0)
        assert res.success is True
        assert res.text == "recovered_ok"
        assert sem._value == 1


# ============================================================================
# Test 7: No duplicate model calls or workspace writes on timeout
# ============================================================================
@pytest.mark.asyncio
async def test_no_duplicate_model_calls_on_timeout():
    """Verify AgentLoop converts Tier 2 timeout into structured observation without duplicate model dispatches."""
    loop = AgentLoop.__new__(AgentLoop)
    loop._mission_id = "test_mission_timeout"
    loop.config = MagicMock()
    loop.config.temperature = 0.0
    loop._publish_event = AsyncMock()
    loop._record_observation = MagicMock()

    mock_ollama = MagicMock()
    mock_ollama.generate = AsyncMock(side_effect=OllamaTimeoutError("Ollama request timed out after 1.0s waiting for execution slot"))

    mock_orch = MagicMock()
    mock_orch._active_tier = 2
    mock_orch.ollama = mock_ollama
    loop.orchestrator = mock_orch

    with patch("config.model_config.TIER2_MODEL", "gpt-oss:120b-cloud"):
        obs = await loop._generate_model_turn(
            system_prompt="sys",
            user_message="user",
            turn_id="turn_t2_timeout",
            timeout_seconds=1.0,
        )

        # Must return structured Observation, not crash
        assert isinstance(obs, Observation)
        assert obs.success is False
        assert obs.source_type == "model"
        assert obs.metadata.get("code") == "TIER2_REQUEST_TIMEOUT"
        assert "timed out" in obs.summary.lower()
        # Exactly ONE call was made — no duplicate background or secondary retry call!
        assert mock_ollama.generate.call_count == 1


# ============================================================================
# Test 8: Total deadline enforced during slow streaming / chunked response
# ============================================================================
@pytest.mark.asyncio
async def test_total_deadline_enforced_during_slow_streaming_response():
    """
    Verify that when a server sends chunks frequently enough to avoid individual
    read timeouts but slowly enough that total duration exceeds the deadline,
    the outer deadline terminates the request, releases the semaphore, allows
    subsequent requests to succeed immediately, and prevents duplicate calls.
    """
    sem = asyncio.Semaphore(1)
    client = OllamaClient(semaphore=sem)

    call_count = 0

    async def mock_slow_streaming_post(url, json=None, timeout=None, **kwargs):
        nonlocal call_count
        call_count += 1
        call_id = json.get("prompt")
        if call_id == "slow_stream":
            # Simulate a slow server that sends small chunks every 0.03s.
            # Individual read timeout is 0.15s, so each chunk easily evades read timeout.
            # But total streaming duration is 2.0s, which far exceeds the 0.15s request deadline.
            start_t = time.monotonic()
            while time.monotonic() - start_t < 2.0:
                await asyncio.sleep(0.03)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": "completed_after_2s", "total_duration": 20_000_000}
            return mock_resp
        else:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": "subsequent_success", "total_duration": 1_000_000}
            return mock_resp

    with patch.object(client, "_get_client", AsyncMock()) as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = mock_slow_streaming_post
        mock_get_client.return_value = mock_http

        # 1. Total deadline must terminate the slow streaming operation
        t0 = time.monotonic()
        with pytest.raises(OllamaTimeoutError) as exc_info:
            await client.generate(
                model="gpt-oss:120b-cloud",
                prompt="slow_stream",
                timeout_seconds=0.15,
            )
        elapsed = time.monotonic() - t0

        # Terminated by outer deadline (around ~0.15s), bounded well below 1.5s
        assert elapsed < 0.45, f"Expected elapsed < 0.45s, got {elapsed:.3f}s"
        assert "exceeded" in str(exc_info.value).lower() or "timed out" in str(exc_info.value).lower()

        # 2. Semaphore permit must be released cleanly
        assert sem._value == 1, "Semaphore permit was not released after slow streaming timeout"

        # 3. Exactly one model call was attempted (no duplicate/retries triggered)
        assert call_count == 1, f"Expected 1 call, got {call_count}"

        # 4. A subsequent request can acquire the semaphore and succeed immediately
        res = await client.generate(
            model="gpt-oss:120b-cloud",
            prompt="healthy_followup",
            timeout_seconds=2.0,
        )
        assert res.success is True
        assert res.text == "subsequent_success"
        assert sem._value == 1
        assert call_count == 2

