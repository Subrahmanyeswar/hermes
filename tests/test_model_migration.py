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
    assert TIER1_MODEL == "deepseek-r1:8b"
    assert TIER2_MODEL == "qwen3:8b"
    assert TIER3_MODEL == "stealth/ox-alpha"
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
