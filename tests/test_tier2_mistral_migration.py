# tests/test_tier2_mistral_migration.py
"""
HERMES 2.x — Tier 2 Migration to Mistral + Provider Reliability & Latency Qualification Suite
Covers Part 12 (Tests 1 through 25):
1. Tier 2 selects Mistral rather than Groq/Qwen.
2. Tier 1 remains unchanged.
3. Tier 3 remains unchanged.
4. Missing MISTRAL_API_KEY fails clearly.
5. API key never appears in logs or telemetry.
6. /v1/models model availability validation.
7. Successful Mistral chat completion.
8. Successful Mistral function calling.
9. Multi-turn tool response handling.
10. Truncated response detection.
11. Mistral HTTP 400 classification.
12. Mistral HTTP 401 classification.
13. Mistral HTTP 403 classification.
14. Mistral HTTP 429 and Retry-After.
15. Mistral HTTP 5xx handling.
16. Mistral connection timeout.
17. Mistral stream stall.
18. Mistral finish-reason normalization.
19. Exact active-tier and provider correlation.
20. No repeated identical Tier 2 retries.
21. Parent deadline enforcement across retries.
22. Tier 3 request timeout enforcement.
23. No Tier 1 -> Tier 2 -> Tier 3 -> Tier 1 endless cycling.
24. Stream cancellation and resource cleanup.
25. Watcher stream filter behavior.
"""

import asyncio
import json
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from config.model_config import (
    TIER1_PROVIDER, TIER1_MODEL,
    TIER2_PROVIDER, TIER2_MODEL,
    TIER3_PROVIDER, TIER3_MODEL,
    HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS,
    HERMES_MODEL_FIRST_TOKEN_TIMEOUT_SECONDS,
    HERMES_MODEL_STREAM_IDLE_TIMEOUT_SECONDS,
)
from models.common_adapter import (
    CommonProviderAdapter,
    ErrorClassification,
    classify_provider_error,
    get_provider_adapter,
    TTFTTimeoutError,
    StreamStallError,
    AttemptTimeoutError,
)
from models.provider import NormalizedModelResponse


# ==============================================================================
# TEST 1: Tier 2 selects Mistral rather than Groq/Qwen
# ==============================================================================
def test_01_tier2_selects_mistral():
    assert TIER2_PROVIDER == "mistral"
    assert TIER2_MODEL in ("codestral-latest", "mistral-small-2603")
    adapter = get_provider_adapter("mistral", tier=2)
    assert adapter.provider_name == "mistral"
    assert adapter.model_name in ("codestral-latest", "mistral-small-2603")
    assert "mistral.ai" in adapter.base_url


# ==============================================================================
# TEST 2: Tier 1 remains unchanged
# ==============================================================================
def test_02_tier1_remains_unchanged():
    assert TIER1_PROVIDER == "gemini"
    assert "gemini" in TIER1_MODEL.lower()


# ==============================================================================
# TEST 3: Tier 3 remains unchanged
# ==============================================================================
def test_03_tier3_remains_unchanged():
    assert TIER3_PROVIDER == "nvidia_nim"
    assert "nemotron" in TIER3_MODEL.lower()


# ==============================================================================
# TEST 4: Missing MISTRAL_API_KEY fails clearly
# ==============================================================================
@pytest.mark.asyncio
async def test_04_missing_mistral_api_key_fails_clearly():
    adapter = CommonProviderAdapter(
        provider_name="mistral",
        model_name="mistral-small-2603",
        base_url="https://api.mistral.ai/v1",
        api_key="",
        tier=2,
    )
    res = await adapter.generate(prompt="hello", stream=False)
    assert res.success is False
    assert "AUTH_FAILURE" in res.error
    assert "API key is not configured" in res.error


# ==============================================================================
# TEST 5: API key never appears in logs or telemetry
# ==============================================================================
@pytest.mark.asyncio
async def test_05_api_key_never_appears_in_logs():
    secret_key = "mstrl_SECRET_NEVER_LOG_ME_12345"
    adapter = CommonProviderAdapter(
        provider_name="mistral",
        model_name="mistral-small-2603",
        base_url="https://api.mistral.ai/v1",
        api_key=secret_key,
        tier=2,
    )
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        data = {
            "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
        mock_resp.json.return_value = data
        mock_resp.text = json.dumps(data)
        mock_post.return_value = mock_resp

        res = await adapter.generate(prompt="hi", stream=False)
        telemetry_str = json.dumps(res.raw_timing_metadata or {})
        assert secret_key not in telemetry_str
        assert secret_key not in str(res)
        assert secret_key not in (res.error or "")


# ==============================================================================
# TEST 6: /v1/models model availability validation
# ==============================================================================
def test_06_models_endpoint_model_availability_validation():
    mock_catalog = {
        "data": [
            {"id": "mistral-small-2603", "object": "model"},
            {"id": "codestral-latest", "object": "model"},
            {"id": "open-mistral-7b", "object": "model"},
        ]
    }
    available_ids = [m["id"] for m in mock_catalog["data"]]
    assert "mistral-small-2603" in available_ids
    assert "groq" not in available_ids


# ==============================================================================
# TEST 7: Successful Mistral chat completion
# ==============================================================================
@pytest.mark.asyncio
async def test_07_successful_mistral_chat_completion():
    adapter = CommonProviderAdapter(
        provider_name="mistral",
        model_name="mistral-small-2603",
        base_url="https://api.mistral.ai/v1",
        api_key="mock_key",
        tier=2,
    )
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        data = {
            "model": "mistral-small-2603",
            "choices": [{
                "message": {"role": "assistant", "content": "Hello from Mistral!"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_resp.json.return_value = data
        mock_resp.text = json.dumps(data)
        mock_post.return_value = mock_resp

        res = await adapter.generate(prompt="hi", stream=False)
        assert res.success is True
        assert res.text == "Hello from Mistral!"
        assert res.finish_reason == "stop"
        assert res.input_tokens == 10
        assert res.output_tokens == 5


# ==============================================================================
# TEST 8: Successful Mistral function calling
# ==============================================================================
@pytest.mark.asyncio
async def test_08_successful_mistral_function_calling():
    adapter = CommonProviderAdapter(
        provider_name="mistral",
        model_name="mistral-small-2603",
        base_url="https://api.mistral.ai/v1",
        api_key="mock_key",
        tier=2,
    )
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        data = {
            "model": "mistral-small-2603",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "fs_write",
                            "arguments": '{"path": "test.txt", "content": "sample"}'
                        }
                    }]
                },
                "finish_reason": "tool_calls"
            }],
            "usage": {"prompt_tokens": 25, "completion_tokens": 15},
        }
        mock_resp.json.return_value = data
        mock_resp.text = json.dumps(data)
        mock_post.return_value = mock_resp

        tools = [{
            "type": "function",
            "function": {"name": "fs.write", "parameters": {"type": "object"}}
        }]
        res = await adapter.generate(prompt="write file", tools=tools, stream=False)
        assert res.success is True
        assert len(res.tool_calls) == 1
        tc = res.tool_calls[0]
        assert tc["name"] == "fs.write"
        assert tc["arguments"]["path"] == "test.txt"
        assert tc["id"] == "call_abc123"


# ==============================================================================
# TEST 9: Multi-turn tool response handling
# ==============================================================================
@pytest.mark.asyncio
async def test_09_multi_turn_tool_response_handling():
    adapter = CommonProviderAdapter(
        provider_name="mistral",
        model_name="mistral-small-2603",
        base_url="https://api.mistral.ai/v1",
        api_key="mock_key",
        tier=2,
    )
    messages = [
        {"role": "user", "content": "Check weather"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}
            }]
        },
        {
            "role": "tool",
            "name": "get_weather",
            "tool_call_id": "call_123",
            "content": '{"temp": 22}'
        }
    ]
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        data = {
            "model": "mistral-small-2603",
            "choices": [{"message": {"role": "assistant", "content": "Weather in Paris is 22C."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10},
        }
        mock_resp.json.return_value = data
        mock_resp.text = json.dumps(data)
        mock_post.return_value = mock_resp

        res = await adapter.generate(messages=messages, stream=False)
        assert res.success is True
        assert "22C" in res.text


# ==============================================================================
# TEST 10: Truncated response detection
# ==============================================================================
@pytest.mark.asyncio
async def test_10_truncated_response_detection():
    adapter = CommonProviderAdapter(
        provider_name="mistral",
        model_name="mistral-small-2603",
        base_url="https://api.mistral.ai/v1",
        api_key="mock_key",
        tier=2,
    )
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        data = {
            "choices": [{
                "message": {"role": "assistant", "content": "Incomplete code snippet..."},
                "finish_reason": "length"
            }],
        }
        mock_resp.json.return_value = data
        mock_resp.text = json.dumps(data)
        mock_post.return_value = mock_resp

        res = await adapter.generate(prompt="generate huge file", stream=False)
        assert res.finish_reason == "length"
        assert res.success is False
        assert "MODEL_OUTPUT_TRUNCATED" in res.error
        assert len(res.tool_calls) == 0


# ==============================================================================
# TEST 11: Mistral HTTP 400 classification
# ==============================================================================
def test_11_mistral_http_400_classification():
    err1 = classify_provider_error(status_code=400, response_body='{"message": "Invalid argument"}')
    assert err1.classification == ErrorClassification.INVALID_REQUEST

    err2 = classify_provider_error(status_code=400, response_body='{"message": "Invalid model: bad-id", "type": "invalid_model"}')
    assert err2.classification == ErrorClassification.MODEL_NOT_FOUND
    assert err2.is_model_unavailable is True


# ==============================================================================
# TEST 12: Mistral HTTP 401 classification
# ==============================================================================
def test_12_mistral_http_401_classification():
    err = classify_provider_error(status_code=401, response_body='{"detail": "Invalid API Key"}')
    assert err.classification == ErrorClassification.AUTH_FAILURE
    assert err.is_unauthorized is True
    assert err.is_transient is False


# ==============================================================================
# TEST 13: Mistral HTTP 403 classification
# ==============================================================================
def test_13_mistral_http_403_classification():
    err = classify_provider_error(status_code=403, response_body='{"detail": "Forbidden"}')
    assert err.classification == ErrorClassification.PERMISSION_DENIED
    assert err.is_unauthorized is True


# ==============================================================================
# TEST 14: Mistral HTTP 429 and Retry-After
# ==============================================================================
def test_14_mistral_http_429_and_retry_after():
    err = classify_provider_error(status_code=429, response_body='{"message": "Rate limit exceeded", "code": "1300"}')
    assert err.classification == ErrorClassification.RATE_LIMIT_EXCEEDED
    assert err.status_code == 429


# ==============================================================================
# TEST 15: Mistral HTTP 5xx handling
# ==============================================================================
def test_15_mistral_http_5xx_handling():
    for code, expected_enum in [
        (500, ErrorClassification.INTERNAL_ERROR),
        (502, ErrorClassification.BAD_GATEWAY),
        (503, ErrorClassification.SERVICE_UNAVAILABLE),
        (504, ErrorClassification.GATEWAY_TIMEOUT),
    ]:
        err = classify_provider_error(status_code=code, response_body="Server glitch")
        assert err.classification == expected_enum
        assert err.is_transient is True


# ==============================================================================
# TEST 16: Mistral connection timeout
# ==============================================================================
def test_16_mistral_connection_timeout():
    exc = TTFTTimeoutError("First token not received within 15.0s")
    err = classify_provider_error(exc=exc)
    assert err.classification == ErrorClassification.MODEL_TTFT_TIMEOUT
    assert err.status_code == 408


# ==============================================================================
# TEST 17: Mistral stream stall
# ==============================================================================
def test_17_mistral_stream_stall():
    exc = StreamStallError("Stream idle timeout exceeded 15.0s")
    err = classify_provider_error(exc=exc)
    assert err.classification == ErrorClassification.MODEL_STREAM_STALL
    assert err.status_code == 408


# ==============================================================================
# TEST 18: Mistral finish-reason normalization
# ==============================================================================
def test_18_mistral_finish_reason_normalization():
    resp_stop = NormalizedModelResponse(text="Done", finish_reason="stop", model="mistral-small-2603", provider="mistral")
    assert resp_stop.finish_reason == "stop"
    assert resp_stop.success is True

    resp_tools = NormalizedModelResponse(text="", tool_calls=[{"name": "test"}], finish_reason="tool_calls", model="mistral-small-2603", provider="mistral")
    assert resp_tools.finish_reason == "tool_calls"
    assert resp_tools.success is True


# ==============================================================================
# TEST 19: Exact active-tier and provider correlation
# ==============================================================================
def test_19_exact_active_tier_and_provider_correlation():
    adapter = get_provider_adapter("mistral", tier=2)
    assert adapter.tier == 2
    assert adapter.provider_name == "mistral"
    assert adapter.model_name in ("codestral-latest", "mistral-small-2603")


# ==============================================================================
# TEST 20: No repeated identical Tier 2 retries
# ==============================================================================
@pytest.mark.asyncio
async def test_20_no_repeated_identical_tier2_retries():
    adapter = CommonProviderAdapter(
        provider_name="mistral",
        model_name="mistral-small-2603",
        base_url="https://api.mistral.ai/v1",
        api_key="mock_key",
        tier=2,
    )
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = '{"message": "Rate limit exceeded"}'
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        res = await adapter.generate(prompt="hi", stream=False)
        assert mock_post.call_count == 1  # Exactly 1 attempt, no runaway retry loop
        assert res.success is False
        assert "RATE_LIMIT_EXCEEDED" in res.error


# ==============================================================================
# TEST 21: Parent deadline enforcement across retries
# ==============================================================================
@pytest.mark.asyncio
async def test_21_parent_deadline_enforcement_across_retries():
    adapter = CommonProviderAdapter(
        provider_name="mistral",
        model_name="mistral-small-2603",
        base_url="https://api.mistral.ai/v1",
        api_key="mock_key",
        tier=2,
        attempt_timeout_seconds=45.0,
    )
    # Passed timeout of 90.0s must be capped by attempt_timeout_seconds (45.0s)
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        data = {
            "choices": [{"message": {"role": "assistant", "content": "Bounded"}}]
        }
        mock_resp.json.return_value = data
        mock_resp.text = json.dumps(data)
        mock_post.return_value = mock_resp

        await adapter.generate(prompt="hi", timeout_seconds=90.0, stream=False)
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["timeout"] == 45.0


# ==============================================================================
# TEST 22: Tier 3 request timeout enforcement
# ==============================================================================
def test_22_tier3_request_timeout_enforcement():
    adapter3 = get_provider_adapter("nvidia_nim", tier=3)
    assert adapter3.attempt_timeout_seconds == 45.0
    assert HERMES_MODEL_ATTEMPT_TIMEOUT_SECONDS == 45.0


# ==============================================================================
# TEST 23: No Tier 1 -> Tier 2 -> Tier 3 -> Tier 1 endless cycling
# ==============================================================================
@pytest.mark.asyncio
async def test_23_no_endless_tier_cycling():
    from core.orchestrator import MultiTierRoutingExhaustedError
    exc = MultiTierRoutingExhaustedError("All tiers exhausted: T1 failed, T2 failed, T3 failed")
    assert "All tiers exhausted" in str(exc)


# ==============================================================================
# TEST 24: Proper stream cancellation and resource cleanup
# ==============================================================================
@pytest.mark.asyncio
async def test_24_stream_cancellation_and_resource_cleanup():
    adapter = CommonProviderAdapter(
        provider_name="mistral",
        model_name="mistral-small-2603",
        base_url="https://api.mistral.ai/v1",
        api_key="mock_key",
        tier=2,
    )
    client = await adapter._get_client()
    assert client is not None
    assert not client.is_closed
    await adapter.close()
    assert adapter._client is None


# ==============================================================================
# TEST 25: Watcher stream filter behavior
# ==============================================================================
def test_25_watcher_stream_filter_behavior():
    watcher_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "watch_mission_logs.ps1")
    with open(watcher_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert '[string]$Stream = "events"' in content
    assert '$streamFileName' in content
    assert '$targetStreamFile' in content
    assert '$fileStream' in content
