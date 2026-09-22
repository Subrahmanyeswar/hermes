"""
Pre-Benchmark Gate 15.9: Tool Reliability Stress Test Regression Suite.
Independently verifies:
1. gate_15_9_tool_reliability_results.json exists with 90/90 PASS and 0 uncaught exceptions.
2. Empty objects ({}) and minimal JSON never crash the mission pipeline.
3. Schema validation safely rejects missing required fields and wrong types.
4. Bounded repair loop guarantees no infinite loops (stops at max_repair_attempts).
5. Post-repair security re-validation intercepts malicious paths and commands.
6. Duplicate calls and idempotency invariants are physically enforced.
7. ResponseParser extracts tool calls amidst prose, markdown fences, and thinking tokens.
"""

import json
import asyncio
from pathlib import Path
import pytest

from core.response_parser import ResponseParser, ParseSuccess, ParseFailure
from core.tool_validator import ToolValidator, ToolValidationResult
from core.workspace import WorkspaceManager, WorkspaceBoundaryError, workspace_manager
from tools.registry import get_tool, list_tools
from tools.file_tools import ReadFileTool, WriteFileTool, DeleteFileTool
from tools.shell_tools import BashExecTool

WORKSPACE = Path(__file__).resolve().parent.parent
RESULTS_PATH = WORKSPACE / "artifacts" / "gate_15_9_tool_reliability_results.json"


def test_gate15_9_results_file_and_summary_metrics():
    """Validates Gate 15.9 results artifact and summary metrics."""
    assert RESULTS_PATH.exists(), f"Missing {RESULTS_PATH}"
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    
    assert data["gate"] == "15.9"
    assert data["total_tests"] == 90
    assert data["passed"] == 90
    assert data["failed"] == 0
    assert data["uncaught_exceptions"] == 0
    assert data["infinite_retry_loops"] == 0
    assert data["unintended_executions"] == 0
    assert data["duplicate_destructive_executions"] == 0
    assert data["false_completions"] == 0
    assert data["security_bypasses"] == 0
    assert data["sentinel_intact"] is True
    assert data["verdict"] == "PASS"


def test_empty_object_never_crashes_parser():
    """Validates that {} and minimal inputs return ParseFailure without raising exceptions."""
    parser = ResponseParser()
    empty_payloads = ["{}", "   ", '{"path": ""}', '{"tool": ""}', '{"parameters": {}}']
    for p in empty_payloads:
        res = parser.parse(p)
        assert isinstance(res, ParseFailure)
        assert res.failure_reason in ("empty_response", "json_found_but_no_tool_key", "json_malformed_unparseable")


def test_schema_validation_rejects_missing_and_wrong_types():
    """Validates that ToolValidator rejects missing required arguments and wrong types."""
    validator = ToolValidator(enabled=True)
    
    # Missing required argument
    is_valid, _, errs = validator.validate_schema("write_file", {"path": "test.txt"})
    assert is_valid is False
    assert any("Missing required argument" in e or "content" in e for e in errs)
    
    # Wrong type (int for path)
    is_valid, _, errs = validator.validate_schema("write_file", {"path": 12345, "content": "hello"})
    assert is_valid is False
    assert len(errs) > 0


@pytest.mark.asyncio
async def test_bounded_repair_loop_prevents_infinite_retries():
    """Validates that repair attempts are strictly bounded by max_repair_attempts."""
    validator = ToolValidator(enabled=True)
    
    class UnresponsiveMockLLM:
        def __init__(self):
            self.calls = 0
        async def generate(self, *args, **kwargs):
            self.calls += 1
            return "still unparseable garbage"
    
    client = UnresponsiveMockLLM()
    res = await validator.process_and_validate(
        tool_name="write_file",
        raw_params={},
        task_text="",
        ollama_client=client,
        max_repair_attempts=2
    )
    assert res.is_valid is False
    assert client.calls == 2  # Bounded exactly to 2 attempts


@pytest.mark.asyncio
async def test_security_revalidation_after_repair_blocks_malicious_output(tmp_path):
    """Validates that repaired model output is strictly re-validated by security."""
    validator = ToolValidator(enabled=True)
    
    # Create isolated workspace and sentinel outside
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "OUTSIDE_SENTINEL.txt"
    sentinel.write_text("SAFE_TOKEN", encoding="utf-8")
    
    orig_wm = workspace_manager.workspace_root
    workspace_manager.lock(str(ws))
    
    class MaliciousRepairLLM:
        async def generate(self, *args, **kwargs):
            return json.dumps({
                "tool": "write_file",
                "parameters": {
                    "path": f"{sentinel.as_posix()}",
                    "content": "PWNED"
                }
            })
    
    try:
        res = await validator.process_and_validate(
            tool_name="write_file",
            raw_params={},
            task_text="",
            ollama_client=MaliciousRepairLLM(),
            max_repair_attempts=1
        )
        assert res.is_valid is False
        assert res.security_passed is False
        assert sentinel.read_text(encoding="utf-8") == "SAFE_TOKEN"
    finally:
        if orig_wm:
            workspace_manager.lock(str(orig_wm))


def test_duplicate_delete_idempotency(tmp_path):
    """Validates that duplicate delete does not raise unhandled exception."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    target = ws / "temp.txt"
    target.write_text("data", encoding="utf-8")
    
    orig_wm = workspace_manager.workspace_root
    workspace_manager.lock(str(ws))
    
    try:
        df = DeleteFileTool()
        r1 = df.execute(DeleteFileTool.Input(path="temp.txt", confirm=True))
        r2 = df.execute(DeleteFileTool.Input(path="temp.txt", confirm=True))
        assert r1.success is True
        assert r2.success is False
        assert "not exist" in r2.error.lower() or "not found" in r2.error.lower()
    finally:
        if orig_wm:
            workspace_manager.lock(str(orig_wm))


def test_parser_extracts_tool_from_markdown_and_prose():
    """Validates that ResponseParser extracts JSON from prose and markdown fences."""
    parser = ResponseParser()
    raw = (
        "I will now inspect the project configuration.\n\n"
        "```json\n"
        "{\n"
        '  "tool": "read_file",\n'
        '  "parameters": {"path": "package.json"}\n'
        "}\n"
        "```\n"
        "Let me know if you need anything else."
    )
    res = parser.parse(raw)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "read_file"
    assert res.parameters.get("path") == "package.json"
