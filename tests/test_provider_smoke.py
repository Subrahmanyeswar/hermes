"""
tests/test_provider_smoke.py
Provider smoke tests verifying the three-tier live provider architecture:
- Tier 1: Gemini (gemini-3.5-flash-lite)
- Tier 2: Groq (qwen/qwen3.8-27b)
- Tier 3: NVIDIA NIM (nvidia/nemotron-3.5-lightning-30b-a3b)
"""
import pytest
import os
import asyncio
from models.common_adapter import get_provider_adapter

_TOOLS_DEF = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Writes content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"}
                },
                "required": ["path", "content"]
            }
        }
    }
]

def test_gemini_adapter_creation():
    adapter = get_provider_adapter("gemini", "gemini-3.5-flash-lite", tier=1)
    assert adapter is not None
    assert type(adapter).__name__ == "GeminiClient"

def test_groq_adapter_creation():
    adapter = get_provider_adapter("groq", "qwen/qwen3.8-27b", tier=2)
    assert adapter is not None
    assert adapter.provider_name == "groq"

def test_nvidia_adapter_creation():
    adapter = get_provider_adapter("nvidia_nim", "nvidia/nemotron-3.5-lightning-30b-a3b", tier=3)
    assert adapter is not None
    assert adapter.provider_name == "nvidia_nim"
    assert "nvidia.com" in adapter.base_url

@pytest.mark.asyncio
async def test_gemini_live_inference():
    adapter = get_provider_adapter("gemini", "gemini-3.5-flash-lite", tier=1)
    resp = await adapter.generate(
        prompt="Call write_file to save test.txt with content 'hello'",
        tools=_TOOLS_DEF,
    )
    assert resp.success is True
    assert len(resp.tool_calls) > 0
    fn_name = resp.tool_calls[0].get("name")
    assert fn_name == "write_file"

@pytest.mark.asyncio
async def test_groq_live_inference():
    adapter = get_provider_adapter("groq", "qwen/qwen3.8-27b", tier=2)
    resp = await adapter.generate(
        prompt="Call write_file to save test.txt with content 'hello'",
        tools=_TOOLS_DEF,
    )
    assert getattr(resp, "success", True) is True
    tc = getattr(resp, "tool_calls", [])
    assert len(tc) > 0
    fn_name = tc[0].get("name") or tc[0].get("function", {}).get("name")
    assert fn_name == "write_file"

@pytest.mark.asyncio
async def test_nvidia_live_inference():
    adapter = get_provider_adapter("nvidia_nim", "nvidia/nemotron-3.5-lightning-30b-a3b", tier=3)
    resp = await adapter.generate(
        prompt="Call write_file to save test.txt with content 'hello'",
        tools=_TOOLS_DEF,
    )
    tc = getattr(resp, "tool_calls", [])
    assert len(tc) > 0
    fn_name = tc[0].get("name") or tc[0].get("function", {}).get("name")
    assert fn_name == "write_file"
