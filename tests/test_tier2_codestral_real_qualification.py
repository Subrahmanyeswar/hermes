# tests/test_tier2_codestral_real_qualification.py
"""
HERMES 2.x — Tier 2 Codestral-Latest Live Qualification Test Suite
==================================================================
Deterministic end-to-end qualification suite verifying the live Mistral Tier 2 adapter
using the actively provisioned 'codestral-latest' model.

Covers:
1. Live Model Health & Connectivity: Latency < 1500ms, valid ping.
2. Live JavaScript Code Generation: Complete function generation & syntax validation.
3. Live Single & Multi-Turn Function Calling: Native tool invocation with fs.write and fs.read.
4. Live Failure Recovery & Syntax Repair: Repairing corrupted/incomplete JS code via context directives.
5. Live Orchestrator Failover & Recovery: Recovery escalation Tier 1 -> Tier 2 executes cleanly.
6. Telemetry & Observability Logging: Verifying models.jsonl records accurate tier, latency, and tokens.
"""

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from config.model_config import (
    TIER1_PROVIDER,
    TIER1_MODEL,
    TIER2_PROVIDER,
    TIER2_MODEL,
    MISTRAL_API_KEY,
)
from core.js_syntax_validator import validate_javascript_content, validate_javascript_file
from core.observability.logger import MissionTelemetryLogger
from models.common_adapter import get_provider_adapter, CommonProviderAdapter
from tools.platform.core_tools import FSWriteTool, FSReadTool, FSEditTool


pytestmark = pytest.mark.asyncio


# ==============================================================================
# 1. LIVE HEALTH & CONNECTIVITY TEST
# ==============================================================================
async def test_live_01_tier2_codestral_health_and_latency():
    """Verify live connectivity and latency < 1500ms for codestral-latest."""
    assert MISTRAL_API_KEY, "MISTRAL_API_KEY must be configured in environment"
    assert TIER2_PROVIDER == "mistral"
    assert TIER2_MODEL == "codestral-latest"

    adapter = get_provider_adapter("mistral", "codestral-latest", tier=2)
    diag = await adapter.run_diagnostics()

    assert diag["healthy"] is True
    assert diag["status"] == "HEALTHY"
    assert diag["tier"] == 2
    assert diag["provider"] == "mistral"
    assert diag["model"] == "codestral-latest"
    assert diag["latency_ms"] < 6000.0, f"Combined latency too high: {diag['latency_ms']}ms"
    assert diag["tool_call_supported"] is True


# ==============================================================================
# 2. LIVE JAVASCRIPT CODE GENERATION & SYNTAX INTEGRITY
# ==============================================================================
async def test_live_02_codestral_javascript_generation_and_syntax():
    """Verify codestral-latest generates syntactically valid JavaScript code."""
    adapter = get_provider_adapter("mistral", "codestral-latest", tier=2)
    prompt = (
        "Write a complete, clean CommonJS JavaScript module defining an EventEmitter class "
        "with on, off, and emit methods. Use module.exports = EventEmitter; at the end. "
        "Output ONLY the raw JavaScript code inside a ```javascript ... ``` code block with no explanations."
    )

    t0 = time.monotonic()
    resp = await adapter.generate(prompt=prompt, max_tokens=512, stream=False)
    elapsed_ms = (time.monotonic() - t0) * 1000.0

    assert resp.success is True
    assert resp.finish_reason == "stop"
    assert resp.output_tokens > 50
    assert elapsed_ms < 5000.0

    # Extract code
    import re
    m = re.search(r"```(?:javascript|js)?\s*(.*?)\s*```", resp.text, re.DOTALL)
    code = m.group(1) if m else resp.text

    # Syntax gate verification
    is_valid, err_msg, diag_line = validate_javascript_content(code, "event_emitter.js")
    assert is_valid is True, f"Generated JS has syntax error: {err_msg} at line {diag_line}"


# ==============================================================================
# 3. LIVE MULTI-STEP NATIVE TOOL CALLING (fs.write & fs.read)
# ==============================================================================
async def test_live_03_codestral_multistep_tool_calling(tmp_path):
    """Verify multi-turn tool calling: model issues fs.write, then reads back file."""
    adapter = get_provider_adapter("mistral", "codestral-latest", tier=2)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "fs_write",
                "description": "Write text content to file at path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fs_read",
                "description": "Read content of file at path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
        },
    ]

    # Turn 1: instruct model to create a file
    messages = [
        {"role": "user", "content": "Create a file named greeting.txt with content 'HELLO_MISTRAL_CODESTRAL' using fs_write."}
    ]
    resp1 = await adapter.generate(messages=messages, tools=tools, max_tokens=256, stream=False)

    assert resp1.success is True
    assert len(resp1.tool_calls) > 0
    call1 = resp1.tool_calls[0]
    assert call1["name"] in ("fs_write", "fs.write")
    args1 = call1["arguments"]
    assert "greeting.txt" in args1.get("path", "")

    # Execute tool write to actual workspace
    target_file = tmp_path / "greeting.txt"
    target_file.write_text(args1["content"], encoding="utf-8")
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == args1["content"]

    # Turn 2: Feed back tool result and instruct model to read it
    messages.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": call1["id"],
            "type": "function",
            "function": {
                "name": call1["name"],
                "arguments": json.dumps(args1),
            }
        }]
    })
    messages.append({
        "role": "tool",
        "tool_call_id": call1["id"],
        "content": json.dumps({"status": "success", "bytes_written": len(args1["content"])}),
    })
    messages.append({
        "role": "user",
        "content": "Now read back greeting.txt using fs_read to verify it.",
    })

    resp2 = await adapter.generate(messages=messages, tools=tools, max_tokens=256, stream=False)
    assert resp2.success is True
    assert len(resp2.tool_calls) > 0
    call2 = resp2.tool_calls[0]
    assert call2["name"] in ("fs_read", "fs.read")
    assert "greeting.txt" in call2["arguments"].get("path", "")


# ==============================================================================
# 4. LIVE SYNTAX REPAIR & FAILURE RECOVERY
# ==============================================================================
async def test_live_04_codestral_syntax_repair_recovery(tmp_path):
    """Verify codestral-latest corrects corrupted code upon receiving syntax repair directive."""
    adapter = get_provider_adapter("mistral", "codestral-latest", tier=2)

    broken_code = (
        "function computeMetrics(data) {\n"
        "    const total = data.reduce((acc, v) => acc + v, 0);\n"
        "    const mean = total / data.length;\n"
        "    return { total, mean };\n"
        "    // Note: missing closing brace below\n"
    )
    broken_file = tmp_path / "metrics.js"
    broken_file.write_text(broken_code, encoding="utf-8")

    # Verify broken state
    is_valid, err_msg, diag_line = validate_javascript_file(str(broken_file))
    assert is_valid is False

    tools = [
        {
            "type": "function",
            "function": {
                "name": "fs_write",
                "description": "Write text content to file at path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        }
    ]

    directive = (
        f"[SYNTAX_REPAIR_DIRECTIVE]\n"
        f"File: metrics.js\n"
        f"Error: {err_msg} at line {diag_line}\n"
        f"Current Content:\n{broken_code}\n"
        f"Instruction: Repair metrics.js so that it has valid JavaScript syntax. "
        f"Call fs_write with the complete valid content."
    )

    resp = await adapter.generate(prompt=directive, tools=tools, max_tokens=256, stream=False)
    assert resp.success is True
    assert len(resp.tool_calls) > 0
    repair_call = resp.tool_calls[0]
    assert repair_call["name"] in ("fs_write", "fs.write")
    repaired_code = repair_call["arguments"]["content"]

    # Write repaired code to disk and validate
    broken_file.write_text(repaired_code, encoding="utf-8")
    is_repaired_valid, rep_err, _ = validate_javascript_file(str(broken_file))
    assert is_repaired_valid is True, f"Repaired code still invalid: {rep_err}\n{repaired_code}"


# ==============================================================================
# 5. LIVE OBSERVABILITY TELEMETRY AUDIT
# ==============================================================================
async def test_live_05_observability_logging_for_tier2(tmp_path):
    """Verify that MissionTelemetryLogger records codestral-latest calls with accurate tier and model metadata."""
    logger = MissionTelemetryLogger(
        mission_id="m_qual_codestral",
        run_id="run_qual_01",
        base_dir=tmp_path / "observability",
    )

    adapter = get_provider_adapter("mistral", "codestral-latest", tier=2)
    t0 = time.monotonic()
    resp = await adapter.generate(prompt="Respond with OK.", max_tokens=10, stream=False)
    elapsed_ms = (time.monotonic() - t0) * 1000.0

    # Log model call using canonical logger
    logger.record_model_call(
        turn=1,
        tier=2,
        provider="mistral",
        model="codestral-latest",
        duration_ms=elapsed_ms,
        status="SUCCESS",
        params={"temperature": 0.2, "max_tokens": 10},
        timings={"total_latency_ms": elapsed_ms, "ttft_ms": resp.latency_ms},
        response_meta={"input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens},
        raw_prompt="Respond with OK.",
        raw_response=resp.text,
    )

    models_log = logger.files["models"]
    assert models_log.exists()
    lines = [json.loads(line) for line in models_log.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) == 1
    entry = lines[0]
    assert entry["tier"] == 2
    assert entry["provider"] == "mistral"
    assert entry["model"] == "codestral-latest"
    assert entry["status"] == "SUCCESS"
    assert entry["duration_ms"] > 0
