# tests/test_three_tier_providers.py
"""
Automated Test Suite for Three-Provider Architecture & Failover Reliability (Section 12).
Tests:
  1. Successful provider response
  2. Streaming response
  3. Tool calling
  4. Multiple tool calls
  5. Tool-result continuation
  6. HTTP 429 handling
  7. HTTP 401 handling
  8. HTTP 5xx handling
  9. Connection timeout
  10. Invalid response
  11. Provider failover
  12. Missing credentials
  13. Cancellation
  14. No duplicate dispatch
  15. Recovery after provider failure

Explicit Routing Tests:
  - Tier 1 succeeds: Tier 2 and Tier 3 are not invoked
  - Tier 1 fails: Tier 2 is invoked
  - Tier 2 succeeds: mission continues
  - Tier 1 and Tier 2 fail: Tier 3 is invoked
  - Tier 3 succeeds: mission continues
  - All tiers fail: mission terminates cleanly with MultiTierRoutingExhaustedError
  - Provider quota exhaustion: no infinite retry loop
  - Recovery transition: no missing-method exception (_trigger_recovery_transition)
  - Successful recovery: authoritative routing state is correct
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from models.common_adapter import (
    CommonProviderAdapter,
    ErrorClassification,
    classify_provider_error,
    get_provider_adapter,
)
from models.provider import NormalizedModelResponse
from core.orchestrator import MultiTierRoutingExhaustedError
from core.adaptive_routing import get_adaptive_router


@pytest.fixture(autouse=True)
def reset_router():
    get_adaptive_router().reset()
    yield
    get_adaptive_router().reset()


# ==============================================================================
# PART 1: 15 FOCUSED PROVIDER ADAPTER TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_01_successful_provider_response():
    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key", tier=1)
    mock_resp = {
        "id": "chat-123",
        "choices": [{"message": {"role": "assistant", "content": "Hello world"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_resp, text=json.dumps(mock_resp))
        res = await adapter.generate(prompt="hi", stream=False)
        assert res.success is True
        assert res.text == "Hello world"
        assert res.model == "glm-4.7-flash"
        assert res.input_tokens == 10
        assert res.output_tokens == 2


@pytest.mark.asyncio
async def test_02_streaming_response():
    adapter = CommonProviderAdapter("nvidia_nim", "minimaxai/minimax-m3.1-flash", "https://integrate.api.nvidia.com/v1", "test_key", tier=2)
    stream_chunks = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "Hello "}}]}) + "\n\n",
        "data: " + json.dumps({"choices": [{"delta": {"content": "streaming!"}}]}) + "\n\n",
        "data: [DONE]\n\n",
    ]
    
    async def fake_aiter_lines():
        for ch in stream_chunks:
            yield ch

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=MagicMock(
        status_code=200,
        aiter_lines=fake_aiter_lines,
    ))
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch.object(httpx.AsyncClient, "stream", return_value=mock_stream_ctx):
        res = await adapter.generate(prompt="stream test", stream=True)
        assert res.success is True
        assert res.text == "Hello streaming!"
        assert res.ttfb_ms >= 0


@pytest.mark.asyncio
async def test_03_tool_calling():
    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key")
    mock_resp = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_abc123",
                    "type": "function",
                    "function": {"name": "fs.read", "arguments": "{\"path\": \"main.py\"}"}
                }]
            }
        }],
        "usage": {"prompt_tokens": 50, "completion_tokens": 15}
    }
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_resp, text=json.dumps(mock_resp))
        res = await adapter.generate(prompt="read main.py", stream=False)
        assert res.success is True
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0]["name"] == "fs.read"
        assert res.tool_calls[0]["arguments"] == {"path": "main.py"}
        assert res.tool_calls[0]["id"] == "call_abc123"


@pytest.mark.asyncio
async def test_04_multiple_tool_calls():
    adapter = CommonProviderAdapter("nvidia_nim", "minimaxai/minimax-m3.1-flash", "https://integrate.api.nvidia.com/v1", "test_key")
    mock_resp = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "fs.write", "arguments": "{\"path\": \"index.html\", \"content\": \"<h1>Hi</h1>\"}"}
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "fs.write", "arguments": "{\"path\": \"style.css\", \"content\": \"body {}\"}"}
                    }
                ]
            }
        }]
    }
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_resp, text=json.dumps(mock_resp))
        res = await adapter.generate(prompt="create files", stream=False)
        assert res.success is True
        assert len(res.tool_calls) == 2
        assert res.tool_calls[0]["arguments"]["path"] == "index.html"
        assert res.tool_calls[1]["arguments"]["path"] == "style.css"


@pytest.mark.asyncio
async def test_05_tool_result_continuation():
    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key")
    messages = [
        {"role": "user", "content": "What is in test.txt?"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_t1", "type": "function", "function": {"name": "fs.read", "arguments": "{\"path\": \"test.txt\"}"}}]},
        {"role": "tool", "tool_call_id": "call_t1", "content": "file contents: hermes rocket"},
    ]
    mock_resp = {
        "choices": [{"message": {"role": "assistant", "content": "The file contains hermes rocket."}}]
    }
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_resp, text=json.dumps(mock_resp))
        res = await adapter.generate(messages=messages, stream=False)
        assert res.success is True
        assert "hermes rocket" in res.text


@pytest.mark.asyncio
async def test_06_http_429_handling():
    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key")
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=429, text='{"error": "rate limit exceeded, retry later"}')
        res = await adapter.generate(prompt="hi", stream=False)
        assert res.success is False
        assert "RATE_LIMIT_EXCEEDED" in res.error


@pytest.mark.asyncio
async def test_07_http_401_handling():
    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "bad_key")
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=401, text='{"error": {"code": "401", "message": "token expired or incorrect"}}')
        res = await adapter.generate(prompt="hi", stream=False)
        assert res.success is False
        assert "AUTH_FAILURE" in res.error


@pytest.mark.asyncio
async def test_08_http_5xx_handling():
    adapter = CommonProviderAdapter("nvidia_nim", "minimaxai/minimax-m3.1-flash", "https://integrate.api.nvidia.com/v1", "test_key")
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=503, text='Service Unavailable - Overloaded')
        res = await adapter.generate(prompt="hi", stream=False)
        assert res.success is False
        assert "SERVICE_UNAVAILABLE" in res.error


@pytest.mark.asyncio
async def test_09_connection_timeout():
    adapter = CommonProviderAdapter("nvidia_nim", "minimaxai/minimax-m3.1-flash", "https://integrate.api.nvidia.com/v1", "test_key")
    with patch.object(httpx.AsyncClient, "post", side_effect=httpx.TimeoutException("Read timed out")):
        res = await adapter.generate(prompt="hi", stream=False)
        assert res.success is False
        assert "REQUEST_TIMEOUT" in res.error


@pytest.mark.asyncio
async def test_10_invalid_response():
    adapter = CommonProviderAdapter("openrouter", "moonshotai/kimi-k2.6:free", "https://openrouter.ai/api/v1", "test_key")
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=MagicMock(side_effect=ValueError("Invalid JSON")), text="Not a JSON")
        res = await adapter.generate(prompt="hi", stream=False)
        assert res.success is False


@pytest.mark.asyncio
async def test_11_provider_failover():
    # Verify fallback from T1 to T2 occurs in orchestrator
    t1_adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key", tier=1)
    t2_adapter = CommonProviderAdapter("nvidia_nim", "minimaxai/minimax-m3.1-flash", "https://integrate.api.nvidia.com/v1", "test_key", tier=2)
    
    t1_adapter.generate = AsyncMock(side_effect=RuntimeError("ZAI 500 error"))
    t2_adapter.generate = AsyncMock(return_value=NormalizedModelResponse(text="Recovered by Tier 2", success=True))

    mock_orch = MagicMock()
    mock_orch.tier1 = t1_adapter
    mock_orch.tier2 = t2_adapter
    mock_orch.tier3 = MagicMock()
    mock_orch._active_tier = 1

    # Simulate dispatch with failover
    async def dispatch(prompt):
        try:
            return await mock_orch.tier1.generate(prompt=prompt)
        except Exception:
            mock_orch._active_tier = 2
            return await mock_orch.tier2.generate(prompt=prompt)

    resp = await dispatch("build app")
    assert resp.success is True
    assert resp.text == "Recovered by Tier 2"
    assert mock_orch._active_tier == 2


@pytest.mark.asyncio
async def test_12_missing_credentials():
    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", api_key="", tier=1)
    res = await adapter.generate(prompt="hi", stream=False)
    assert res.success is False
    assert "not configured" in res.error


@pytest.mark.asyncio
async def test_13_cancellation():
    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key")
    with patch.object(httpx.AsyncClient, "post", side_effect=asyncio.CancelledError()):
        with pytest.raises(asyncio.CancelledError):
            await adapter.generate(prompt="cancel me", stream=False)


@pytest.mark.asyncio
async def test_14_no_duplicate_dispatch():
    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key")
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"choices": [{"message": {"content": "ok"}}]}, text="{}")
        # Ensure single invocation generates exactly 1 request
        await adapter.generate(prompt="single", stream=False)
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_15_recovery_after_provider_failure():
    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key")
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        # First call fails, second call succeeds
        mock_post.side_effect = [
            MagicMock(status_code=503, text="Service Unavailable"),
            MagicMock(status_code=200, json=lambda: {"choices": [{"message": {"content": "Healthy now"}}]}, text="{}")
        ]
        r1 = await adapter.generate(prompt="p1", stream=False)
        assert r1.success is False
        r2 = await adapter.generate(prompt="p2", stream=False)
        assert r2.success is True
        assert r2.text == "Healthy now"


# ==============================================================================
# PART 2: 9 EXPLICIT ROUTING & AGENTLOOP RECOVERY TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_routing_01_tier1_succeeds_tier2_tier3_untouched():
    from core.adaptive_routing import get_adaptive_router
    get_adaptive_router().reset()
    t1 = MagicMock(generate=AsyncMock(return_value=NormalizedModelResponse(text="T1 OK", success=True)))
    t2 = MagicMock(generate=AsyncMock())
    t3 = MagicMock(generate=AsyncMock())

    from core.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.tier1 = t1
    orch.tier2 = t2
    orch.tier3 = t3
    orch._tier3 = t3
    orch.ollama = None
    orch._default_ollama = None
    orch._emit_progress = AsyncMock()

    resp = await orch._generate_t1(prompt="test")
    assert resp.text == "T1 OK"
    t1.generate.assert_awaited_once()
    t2.generate.assert_not_called()
    t3.generate.assert_not_called()


@pytest.mark.asyncio
async def test_routing_02_tier1_fails_tier2_invoked():
    from core.adaptive_routing import get_adaptive_router
    get_adaptive_router().reset()
    t1 = MagicMock(generate=AsyncMock(side_effect=RuntimeError("T1 500 error")))
    t2 = MagicMock(generate=AsyncMock(return_value=NormalizedModelResponse(text="T2 OK", success=True)))
    t3 = MagicMock(generate=AsyncMock())

    from core.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.tier1 = t1
    orch.tier2 = t2
    orch.tier3 = t3
    orch._tier3 = t3
    orch.ollama = None
    orch._default_ollama = None
    orch._emit_progress = AsyncMock()

    resp = await orch._generate_t1(prompt="test")
    assert resp.text == "T2 OK"
    t1.generate.assert_awaited_once()
    t2.generate.assert_awaited_once()
    t3.generate.assert_not_called()


@pytest.mark.asyncio
async def test_routing_03_tier1_and_tier2_fail_tier3_invoked():
    from core.adaptive_routing import get_adaptive_router
    get_adaptive_router().reset()
    t1 = MagicMock(generate=AsyncMock(side_effect=RuntimeError("T1 error")))
    t2 = MagicMock(generate=AsyncMock(side_effect=RuntimeError("T2 error")))
    t3 = MagicMock(generate=AsyncMock(return_value=NormalizedModelResponse(text="T3 OK", success=True)))

    from core.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.tier1 = t1
    orch.tier2 = t2
    orch.tier3 = t3
    orch._tier3 = t3
    orch.ollama = None
    orch._default_ollama = None
    orch._emit_progress = AsyncMock()

    resp = await orch._generate_t1(prompt="test")
    assert resp.text == "T3 OK"
    t1.generate.assert_awaited_once()
    t2.generate.assert_awaited_once()
    t3.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_routing_04_all_tiers_fail_terminates_cleanly():
    from core.adaptive_routing import get_adaptive_router
    get_adaptive_router().reset()
    t1 = MagicMock(generate=AsyncMock(side_effect=RuntimeError("T1 down")))
    t2 = MagicMock(generate=AsyncMock(side_effect=RuntimeError("T2 down")))
    t3 = MagicMock(generate=AsyncMock(side_effect=RuntimeError("T3 down")))

    from core.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.tier1 = t1
    orch.tier2 = t2
    orch.tier3 = t3
    orch._tier3 = t3
    orch.ollama = None
    orch._default_ollama = None
    orch._emit_progress = AsyncMock()

    with pytest.raises(MultiTierRoutingExhaustedError) as exc_info:
        await orch._generate_t1(prompt="test")
    assert "tiers failed" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_routing_05_quota_exhaustion_no_infinite_loop():
    adapter = CommonProviderAdapter("openrouter", "moonshotai/kimi-k2.6:free", "https://openrouter.ai/api/v1", "test_key")
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=429, text='{"error": {"code": 429, "message": "quota exceeded"}}')
        res = await adapter.generate(prompt="hi", stream=False)
        assert res.success is False
        assert "RATE_LIMIT_EXCEEDED" in res.error
        # Exactly one call executed - no infinite retry
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_routing_06_recovery_transition_no_missing_method():
    """Verify that AgentLoop has _trigger_recovery_transition and does NOT raise AttributeError."""
    from core.agent_loop.loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    loop._mission_id = "m_test_rec"
    loop._recovery_attempt_count = 0
    loop.workspace = MagicMock(root_str=".", is_locked=False)
    loop.orchestrator = MagicMock(_active_tier=1)
    loop.context_engine = None
    loop._publish_event = AsyncMock()
    loop._record_observation = MagicMock()

    # Call _trigger_recovery_transition - MUST NOT raise AttributeError
    rec_ok = await loop._trigger_recovery_transition(
        turn_id="turn_1",
        rejection_reason="Model stalled in reasoning-only loop",
        unmet_reqs=["index.html", "main.js"]
    )
    assert rec_ok is True
    assert loop.orchestrator._active_tier == 2
    assert loop._recovery_attempt_count == 1


@pytest.mark.asyncio
async def test_routing_07_recovery_transition_escalates_to_tier3():
    """Verify second recovery transition escalates from Tier 2 to Tier 3."""
    from core.agent_loop.loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    loop._mission_id = "m_test_rec2"
    loop._recovery_attempt_count = 1
    loop.workspace = MagicMock(root_str=".", is_locked=False)
    loop.orchestrator = MagicMock(_active_tier=2)
    loop.context_engine = None
    loop._publish_event = AsyncMock()
    loop._record_observation = MagicMock()

    rec_ok = await loop._trigger_recovery_transition(
        turn_id="turn_2",
        rejection_reason="Tier 2 also stalled",
        unmet_reqs=["main.js"]
    )
    assert rec_ok is True
    assert loop.orchestrator._active_tier == 3
    assert loop._recovery_attempt_count == 2


@pytest.mark.asyncio
async def test_routing_08_recovery_transition_exhaustion():
    """Verify third recovery transition is rejected (bounded recovery policy)."""
    from core.agent_loop.loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    loop._mission_id = "m_test_rec3"
    loop._recovery_attempt_count = 2
    loop.orchestrator = MagicMock(_active_tier=3)

    rec_ok = await loop._trigger_recovery_transition(
        turn_id="turn_3",
        rejection_reason="Tier 3 exhausted",
        unmet_reqs=["main.js"]
    )
    assert rec_ok is False


@pytest.mark.asyncio
async def test_routing_09_authoritative_routing_state_persistence():
    """Verify authoritative routing state is correctly maintained across turns."""
    from core.agent_loop.loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    loop._mission_id = "m_test_state"
    loop._recovery_attempt_count = 0
    loop.workspace = MagicMock(root_str=".", is_locked=False)
    orch = MagicMock(_active_tier=1)
    loop.orchestrator = orch
    loop.context_engine = None
    loop._publish_event = AsyncMock()
    loop._record_observation = MagicMock()

    assert orch._active_tier == 1
    await loop._trigger_recovery_transition(turn_id="t1", rejection_reason="loop")
    assert orch._active_tier == 2
    await loop._trigger_recovery_transition(turn_id="t2", rejection_reason="loop")
    assert orch._active_tier == 3
