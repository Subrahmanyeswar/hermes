# tests/test_model_migration.py
# Tests for HERMES Phase 1 Model Migration (3-tier architecture, providers, validation recovery)

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from pydantic import BaseModel, ValidationError

from models.provider import ModelProvider, NormalizedModelResponse
from models.ollama_client import OllamaClient
from models.openrouter_client import OpenRouterClient, Tier3Response
from config.model_config import (
    TIER1_MODEL,
    TIER2_MODEL,
    TIER3_MODEL,
    MODEL_KEEP_ALIVE,
    MODEL_TIMEOUT_SECONDS,
)
from core.error_handler import ErrorHandler, FailureMode, RecoveryAction
from core.orchestrator import Orchestrator
from tools.base import BaseTool, ToolResult


# ──────────────────────────────────────────────────────────────────────
# 1. Normalized Model Provider Tests
# ──────────────────────────────────────────────────────────────────────

def test_normalized_model_response():
    resp = NormalizedModelResponse(
        text="Hello world",
        model="deepseek-r1:8b",
        provider="ollama",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        latency_ms=120.5,
        cost_usd=0.0,
        success=True
    )
    assert resp.text == "Hello world"
    assert str(resp) == "Hello world"
    assert resp.model == "deepseek-r1:8b"
    assert resp.provider == "ollama"
    assert resp.total_tokens == 15
    assert resp.success is True


def test_model_config_defaults():
    assert TIER1_MODEL == "z-ai/glm-5.3-flash"
    assert TIER2_MODEL == "gpt-oss:120b-cloud"
    assert TIER3_MODEL == "nemotron-3-ultra:cloud"
    assert MODEL_KEEP_ALIVE == "300s"
    assert MODEL_TIMEOUT_SECONDS > 0


# ──────────────────────────────────────────────────────────────────────
# 2. Ollama Provider Unit Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ollama_client_response_normalization():
    client = OllamaClient()
    mock_payload = {
        "response": "{\"tool\": \"list_files\", \"parameters\": {\"path\": \".\"}}",
        "prompt_eval_count": 45,
        "eval_count": 20,
        "load_duration": 5000000,
        "prompt_eval_duration": 20000000,
        "eval_duration": 40000000,
    }
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload
    
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
        res = await client.generate(
            model=TIER1_MODEL,
            prompt="list files in current directory",
            system="system instructions",
            keep_alive=MODEL_KEEP_ALIVE
        )
        assert isinstance(res, NormalizedModelResponse)
        assert "list_files" in res.text
        assert res.model == TIER1_MODEL
        assert res.provider == "ollama"
        assert res.input_tokens == 45
        assert res.output_tokens == 20
        assert res.total_tokens == 65
        assert res.success is True


# ──────────────────────────────────────────────────────────────────────
# 3. OpenRouter Provider Unit Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openrouter_client_generate_and_arbitrate():
    client = OpenRouterClient(api_key="test-mock-key")
    assert client.is_available() is True
    
    mock_response_json = {
        "choices": [{"message": {"content": "Arbitration decision: Proceed with tool."}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}
    }
    
    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.json.return_value = mock_response_json
    
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_http_resp)):
        # Test generate()
        gen_res = await client.generate(
            model=TIER3_MODEL,
            prompt="Hello from OpenRouter",
            system="You are an assistant."
        )
        assert isinstance(gen_res, NormalizedModelResponse)
        assert "Proceed with tool" in gen_res.text
        assert gen_res.model == TIER3_MODEL
        assert gen_res.provider == "openrouter"
        assert gen_res.input_tokens == 100
        assert gen_res.output_tokens == 30
        assert gen_res.cost_usd > 0.0
        assert gen_res.success is True
        
        # Test arbitrate()
        arb_res = await client.arbitrate(
            task="Create a secure server",
            tier1_output="{\"tool\": \"write_file\"}",
            tier2_issues=["Port number unvalidated"],
            tool_result="File written",
            escalation_reason="Disagreement on security"
        )
        assert isinstance(arb_res, Tier3Response)
        assert "Proceed with tool" in arb_res.content
        assert arb_res.model == TIER3_MODEL
        assert arb_res.cost_usd > 0.0
        assert arb_res.success is True


# ──────────────────────────────────────────────────────────────────────
# 4. Tool Validation Recovery Loop Unit Tests
# ──────────────────────────────────────────────────────────────────────

def test_error_handler_tool_validation_failure():
    eh = ErrorHandler()
    res = eh.tool_validation_failure(
        tool_name="read_file",
        validation_error="missing required argument 'path'",
        schema_info="path: str",
        attempt=0
    )
    assert res.failure_mode == FailureMode.TOOL_VALIDATION_FAILURE
    assert res.recovery_action == RecoveryAction.RETRY_WITH_ERROR_CONTEXT
    assert res.can_retry is True
    assert "missing required argument 'path'" in res.context_for_retry
    
    # Second attempt
    res2 = eh.tool_validation_failure("read_file", "missing required argument 'path'", attempt=2)
    assert res2.failure_mode == FailureMode.TOOL_VALIDATION_FAILURE
    assert res2.recovery_action == RecoveryAction.FAIL_TASK
    assert res2.is_final is True


@pytest.mark.asyncio
async def test_orchestrator_recovers_from_empty_tool_parameters():
    """Test that when model produces empty parameters {}, Hermes does NOT crash or execute {}, but recovers via retry."""
    orch = Orchestrator()
    
    # 1st call: returns empty parameters {} for read_file (missing 'path')
    bad_t1_response = '{"tool": "read_file", "parameters": {}}'
    # 2nd call: returns corrected parameters
    good_t1_response = '{"tool": "read_file", "parameters": {"path": "README.md"}}'
    
    mock_responses = [
        NormalizedModelResponse(text=bad_t1_response, model=TIER1_MODEL),
        NormalizedModelResponse(text=good_t1_response, model=TIER1_MODEL),
    ]
    
    call_count = 0
    async def mock_generate(*args, **kwargs):
        nonlocal call_count
        resp = mock_responses[min(call_count, len(mock_responses) - 1)]
        call_count += 1
        return resp
        
    orch.tier1.generate = mock_generate
    orch.ollama.generate = mock_generate
    
    from core.verifier import VerificationResult
    mock_verification = VerificationResult(
        agree=True,
        confidence=0.9,
        critical_issues=[],
        risk_score=0.1,
        quality_verdict="COMPLETE",
        latency_seconds=0.05
    )
    with patch("tools.file_tools.ReadFileTool.execute", new=AsyncMock(return_value=ToolResult(success=True, output="# Hermes", exit_code=0))):
        with patch.object(orch.verifier, "verify", new=AsyncMock(return_value=mock_verification)):
            res = await orch.run("Read the readme file")
            assert call_count >= 2
            assert res.tool_name == "read_file"
            assert res.success is True


# ──────────────────────────────────────────────────────────────────────
# 5. NVIDIA Provider Unit Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nvidia_client_response_normalization():
    from models.nvidia_client import NvidiaClient
    client = NvidiaClient(api_key="test-mock-key")
    assert await client.is_available() is True

    mock_response_json = {
        "choices": [
            {
                "message": {
                    "content": "{\"tool\": \"read_file\", \"parameters\": {\"path\": \"README.md\"}}",
                    "reasoning_content": "The user wants to read README.md"
                }
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75}
    }

    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.json.return_value = mock_response_json

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_http_resp)):
        res = await client.generate(
            model=TIER1_MODEL,
            prompt="read the readme",
            system="system instructions"
        )
        assert isinstance(res, NormalizedModelResponse)
        assert "read_file" in res.text
        assert "<think>" in res.text
        assert "The user wants to read README.md" in res.text
        assert res.model == TIER1_MODEL
        assert res.provider == "nvidia_nim"
        assert res.input_tokens == 50
        assert res.output_tokens == 25
        assert res.total_tokens == 75
        assert res.success is True


@pytest.mark.asyncio
async def test_ollama_client_arbitrate_contract():
    client = OllamaClient()
    mock_norm = NormalizedModelResponse(
        text="Arbitration decision: Proceed with tool.",
        model=TIER3_MODEL,
        provider="ollama",
        input_tokens=80,
        output_tokens=20,
        success=True
    )
    with patch.object(client, "generate", new=AsyncMock(return_value=mock_norm)):
        arb = await client.arbitrate(
            task="Arbitration task",
            tier1_output="{\"tool\": \"read_file\"}",
            tier2_issues=["Issue 1"],
            tool_result="File read",
            escalation_reason="Disagreement"
        )
        assert isinstance(arb, Tier3Response)
        assert arb.success is True
        assert "Proceed with tool" in arb.content
        assert arb.model == TIER3_MODEL
        assert arb.cost_usd == 0.0
    
    cost_sum = client.get_cost_summary()
    assert "total_spent" in cost_sum
    assert cost_sum["total_spent"] == 0.0


def test_status_bar_model_indicators():
    from ui.panels.status_bar import StatusBar, _format_model_badge
    assert _format_model_badge("z-ai/glm-5.3-flash") == "GLM-5.3-Flash"
    assert _format_model_badge("gpt-oss:120b-cloud") == "GPT-OSS"
    assert _format_model_badge("nemotron-3-ultra:cloud") == "Nemotron"

    bar = StatusBar()
    assert bar.tier1_model == "GLM-5.3-Flash"
    assert bar.tier2_model == "GPT-OSS"
    assert bar.tier3_model == "Nemotron"

    rendered = bar._render_status_text()
    assert "T1:GLM-5.3-Flash+T2:GPT-OSS" in rendered.plain


@pytest.mark.asyncio
async def test_startup_screen_status_check():
    from ui.panels.startup import StartupScreen
    screen = StartupScreen()
    assert hasattr(screen, "_t1_ok")
    assert hasattr(screen, "_t2_ok")
    assert hasattr(screen, "_t3_ok")


@pytest.mark.asyncio
async def test_orchestrator_tier1_binding_and_memory_client():
    from core.orchestrator import Orchestrator
    from config.model_config import TIER1_PROVIDER
    orch = Orchestrator()
    if TIER1_PROVIDER == "nvidia_nim":
        from models.nvidia_client import NvidiaClient
        assert isinstance(orch.tier1, NvidiaClient)
        assert orch.tier1.model == TIER1_MODEL
        assert orch.memory_manager._ollama_client == orch.tier1


@pytest.mark.asyncio
async def test_mission_driver_event_queue_identity_preserved():
    """Verify that MissionDriver drains event queue in place and never replaces the instance."""
    from kairos.mission_driver import MissionDriver
    mock_orch = MagicMock()
    mock_orch.execution_mode = "production"
    driver = MissionDriver(orchestrator=mock_orch)
    initial_queue = driver.get_event_queue()
    assert initial_queue is driver._event_queue

    # Put a dummy event into queue
    await initial_queue.put("dummy_event")
    assert not initial_queue.empty()

    # Mock planner and runner
    mock_mission = MagicMock()
    mock_mission.mission_id = "test_m"
    mock_mission.tasks = []
    driver._planner.plan = MagicMock(return_value=mock_mission)

    mock_runner = MagicMock()
    mock_result = MagicMock()
    mock_result.tasks = []
    mock_result.overall_status = "success"
    mock_runner.run = AsyncMock(return_value=mock_result)

    with patch("kairos.mission_driver.MissionRunner", return_value=mock_runner):
        with patch.object(driver, "initialise_workspace", new=AsyncMock(return_value={})):
            await driver.run_mission("test prompt")

    # The queue instance MUST be identical
    assert driver.get_event_queue() is initial_queue
    assert driver._event_queue is initial_queue


@pytest.mark.asyncio
async def test_nvidia_client_streaming_sse_parser():
    """Verify NvidiaClient SSE stream parsing accumulates content and reasoning."""
    from models.nvidia_client import NvidiaClient
    client = NvidiaClient(api_key="test-mock-key")

    sse_lines = [
        b"data: {\"choices\": [{\"delta\": {\"reasoning_content\": \"Thinking step 1... \"}}]}\n",
        b"data: {\"choices\": [{\"delta\": {\"reasoning_content\": \"Thinking step 2.\"}}]}\n",
        b"data: {\"choices\": [{\"delta\": {\"content\": \"{\\\"tool\\\": \\\"write_file\\\", \"}}]}\n",
        b"data: {\"choices\": [{\"delta\": {\"content\": \"\\\"parameters\\\": {\\\"path\\\": \\\"index.html\\\"}}\"}}]}\n",
        b"data: [DONE]\n"
    ]

    async def mock_aiter_lines():
        for line in sse_lines:
            yield line.decode("utf-8")

    mock_stream_resp = MagicMock()
    mock_stream_resp.status_code = 200
    mock_stream_resp.aiter_lines = mock_aiter_lines

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_stream(*args, **kwargs):
        yield mock_stream_resp

    mock_http_client = MagicMock()
    mock_http_client.stream = mock_stream

    with patch.object(client, "_get_client", new=AsyncMock(return_value=mock_http_client)):
        res = await client.generate(prompt="create file", stream=True)
        assert res.success is True
        assert "<think>" in res.text
        assert "Thinking step 1... Thinking step 2." in res.text
        assert "\"tool\": \"write_file\"" in res.text
        assert res.provider == "nvidia_nim"
        assert res.model == "z-ai/glm-5.3-flash"


@pytest.mark.asyncio
async def test_nvidia_client_tool_call_delta_accumulation():
    """Verify NvidiaClient properly accumulates streaming tool_calls deltas."""
    from models.nvidia_client import NvidiaClient
    client = NvidiaClient(api_key="test-mock-key")

    sse_lines = [
        b"data: {\"choices\": [{\"delta\": {\"tool_calls\": [{\"index\": 0, \"id\": \"call_abc\", \"type\": \"function\", \"function\": {\"name\": \"write_file\", \"arguments\": \"{\\\"path\\\": \"}}]}}]}\n",
        b"data: {\"choices\": [{\"delta\": {\"tool_calls\": [{\"index\": 0, \"function\": {\"arguments\": \"\\\"index.html\\\", \\\"content\\\": \\\"<h1>Hi</h1>\\\"}\"}}]}}]}\n",
        b"data: [DONE]\n"
    ]

    async def mock_aiter_lines():
        for line in sse_lines:
            yield line.decode("utf-8")

    mock_stream_resp = MagicMock()
    mock_stream_resp.status_code = 200
    mock_stream_resp.aiter_lines = mock_aiter_lines

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_stream(*args, **kwargs):
        yield mock_stream_resp

    mock_http_client = MagicMock()
    mock_http_client.stream = mock_stream

    with patch.object(client, "_get_client", new=AsyncMock(return_value=mock_http_client)):
        res = await client.generate(prompt="create index", stream=True)
        assert res.success is True
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0]["id"] == "call_abc"
        assert res.tool_calls[0]["function"]["name"] == "write_file"
        assert "\"path\": \"index.html\"" in res.tool_calls[0]["function"]["arguments"]
        # Also verify synthesized text contains the tool call
        assert "write_file" in res.text



