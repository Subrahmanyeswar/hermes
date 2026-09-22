"""
tests/test_ollama_client_reasoning.py
Comprehensive unit tests for OllamaClient reasoning model ingestion (Cases A-H, streaming, token accounting, etc.).
"""

import asyncio
import json
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from models.ollama_client import OllamaClient, normalize_ollama_payload, OllamaTimeoutError, OllamaConnectionError
from models.provider import NormalizedModelResponse
from core.response_parser import ResponseParser, ParseSuccess, ParseFailure


class TestNormalizeOllamaPayload:
    # TEST 1: Case A — Standard response-only payload
    def test_case_a_standard_response_only(self):
        data = {"response": '{"tool": "write_file", "parameters": {"path": "main.py"}}'}
        res = normalize_ollama_payload(data)
        assert res == '{"tool": "write_file", "parameters": {"path": "main.py"}}'

    # TEST 2: Case B — Reasoning-only payload (DeepSeek-R1 standard)
    def test_case_b_reasoning_only(self):
        thinking = 'Let me create the helper\n{"tool": "write_file", "parameters": {"path": "main.py"}}'
        data = {"thinking": thinking, "response": ""}
        res = normalize_ollama_payload(data)
        assert "<think>" in res
        assert "</think>" in res
        assert thinking in res

    # TEST 3: Case C — Thinking + response payload
    def test_case_c_thinking_plus_response(self):
        thinking = "Analyze problem step by step."
        response = '{"tool": "write_file", "parameters": {"path": "main.py"}}'
        data = {"thinking": thinking, "response": response}
        res = normalize_ollama_payload(data)
        assert res.startswith("<think>\nAnalyze problem step by step.\n</think>\n")
        assert res.endswith(response)

    # TEST 4: Case D — Empty thinking + populated response
    def test_case_d_empty_thinking_plus_response(self):
        data = {"thinking": "", "response": "Hello world"}
        res = normalize_ollama_payload(data)
        assert res == "Hello world"
        assert "<think>" not in res

    # TEST 5: Case E — Missing thinking field
    def test_case_e_missing_thinking_field(self):
        data = {"response": "Only response"}
        res = normalize_ollama_payload(data)
        assert res == "Only response"

    # TEST 6: Case F — Missing response field + populated thinking
    def test_case_f_missing_response_field(self):
        data = {"thinking": "Only thinking"}
        res = normalize_ollama_payload(data)
        assert "<think>\nOnly thinking\n</think>" in res

    # TEST 7: Case G — Both fields empty
    def test_case_g_both_empty(self):
        data = {"thinking": "", "response": ""}
        res = normalize_ollama_payload(data)
        assert res == ""

    # TEST 8: Case H — Malformed payload / non-dict / missing keys
    def test_case_h_malformed_payload(self):
        assert normalize_ollama_payload({}) == ""
        assert normalize_ollama_payload(None) == ""
        assert normalize_ollama_payload({"other": 123}) == ""
        assert normalize_ollama_payload({"thinking": None, "response": None}) == ""

    # TEST 12: Tool JSON survives normalization and parses cleanly
    def test_tool_json_survives_and_parses(self):
        parser = ResponseParser()
        data = {
            "thinking": "We should use write_file to save the helper.",
            "response": '{"tool": "write_file", "parameters": {"path": "helpers.py", "content": "def help(): pass"}}'
        }
        normalized = normalize_ollama_payload(data)
        parse_res = parser.parse(normalized)
        assert isinstance(parse_res, ParseSuccess)
        assert parse_res.tool == "write_file"
        assert parse_res.parameters["path"] == "helpers.py"
        assert "write_file" in parse_res.reasoning or "We should" in parse_res.reasoning

    # TEST 13: Pre-existing <think> tags are not duplicated
    def test_think_tag_no_duplication(self):
        data = {"thinking": "<think>Existing thoughts</think>", "response": "Result"}
        normalized = normalize_ollama_payload(data)
        assert normalized.count("<think>") == 1
        assert normalized.count("</think>") == 1


@pytest.mark.asyncio
class TestOllamaClientAsync:
    # TEST 9 & 10 & 11: Async generate with mocked API response
    async def test_generate_reasoning_payload(self):
        client = OllamaClient()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "thinking": 'Let us write the file\n{"tool": "write_file", "parameters": {"path": "a.py"}}',
            "response": "",
            "prompt_eval_count": 50,
            "eval_count": 120,
            "load_duration": 100_000_000,
            "prompt_eval_duration": 200_000_000,
            "eval_duration": 1_000_000_000,
        }

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_response)):
            res: NormalizedModelResponse = await client.generate(
                model="deepseek-r1:8b",
                prompt="Write a file a.py",
                keep_alive=0
            )
            assert res.success is True
            assert "<think>" in res.text
            assert "write_file" in res.text
            # TEST 14: Token accounting
            assert res.input_tokens == 50
            assert res.output_tokens == 120
            assert res.total_tokens == 170

    # TEST 16: Genuine empty response produces empty string
    async def test_generate_genuine_empty_response(self):
        client = OllamaClient()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "thinking": "",
            "response": "",
            "prompt_eval_count": 10,
            "eval_count": 0,
        }

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_response)):
            res = await client.generate(model="deepseek-r1:8b", prompt="Hello", keep_alive=0)
            assert res.text == ""
            parser = ResponseParser()
            parse_res = parser.parse(res.text)
            assert isinstance(parse_res, ParseFailure)
            assert parse_res.failure_reason == "empty_response"

    # TEST 17: Provider error raises RuntimeError
    async def test_generate_provider_error(self):
        client = OllamaClient()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"error": "model not found"}

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_response)):
            with pytest.raises(RuntimeError, match="model not found"):
                await client.generate(model="nonexistent:model", prompt="Hello", keep_alive=0)

    # TEST 18: Timeout raises OllamaTimeoutError
    async def test_generate_timeout_error(self):
        client = OllamaClient()
        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=httpx.TimeoutException("timeout"))):
            with pytest.raises(OllamaTimeoutError):
                await client.generate(model="deepseek-r1:8b", prompt="Hello", keep_alive=0)

    # TEST 19: Connection error raises OllamaConnectionError
    async def test_generate_connection_error(self):
        client = OllamaClient()
        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=httpx.ConnectError("cannot connect"))):
            with pytest.raises(OllamaConnectionError):
                await client.generate(model="deepseek-r1:8b", prompt="Hello", keep_alive=0)
