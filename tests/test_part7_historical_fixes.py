import os
from pathlib import Path
import pytest

from core.response_parser import ResponseParser, ParseSuccess
from models.provider import NormalizedModelResponse
from models.ollama_client import normalize_ollama_payload
from core.tool_validator import tool_validator
from tools.file_tools import WriteFileTool, ReadFileTool, _clean_code_content
from core.workspace import workspace_manager, WorkspaceBoundaryError
from core.telemetry import telemetry, ToolTelemetry
from core.verification_gate import VerificationGate
from core.error_handler import ErrorHandler, FailureMode, RecoveryAction

def test_A_tool_call_parsing():
    parser = ResponseParser()
    res = parser.parse('{"tool": "read_file", "parameters": {"path": "test.py"}}')
    assert isinstance(res, ParseSuccess)
    assert res.tool == "read_file"
    assert res.parameters["path"] == "test.py"

def test_B_structured_response_normalization():
    norm = NormalizedModelResponse(
        text="raw string with \\n and \\\" verbatim",
        model="deepseek-r1:8b",
        provider="ollama"
    )
    assert norm.text == "raw string with \\n and \\\" verbatim"
    assert norm.model == "deepseek-r1:8b"

def test_C_think_reasoning_response_handling():
    payload = {
        "thinking": "Step 1: check files",
        "response": '{"tool": "list_directory", "parameters": {"path": "."}}'
    }
    normalized = normalize_ollama_payload(payload)
    assert "<think>" in normalized
    assert "Step 1: check files" in normalized
    assert "</think>" in normalized
    assert '{"tool": "list_directory"' in normalized

def test_D_content_preserving_file_writes(tmp_path):
    target = tmp_path / "test_bytes.py"
    raw_content = "line1\nline2\nprint('{\\\"key\\\": 123}')\n"
    cleaned = _clean_code_content(raw_content)
    assert cleaned == raw_content
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(cleaned)
    with open(target, "r", encoding="utf-8") as f:
        read_back = f.read()
    assert read_back == raw_content

def test_E_python_indentation_preservation():
    code = "def foo():\n    if True:\n        return 42\n"
    normalized, mods = tool_validator.normalize("write_file", {"path": "foo.py", "content": code})
    assert normalized["content"] == code

def test_F_tool_telemetry_recording():
    req = telemetry.start_request("test prompt")
    req_id = req.request_id
    tt = ToolTelemetry(
        tool_name="test_tool",
        start_time_monotonic=100.0,
        duration_ms=25.0,
        success=True,
        exit_code=0
    )
    telemetry.record_tool(tt, request_id=req_id)
    retrieved = telemetry.get_request(req_id)
    assert retrieved is not None
    assert len(retrieved.tools) >= 1
    assert retrieved.tools[-1].tool_name == "test_tool"
    telemetry.finish_request(req_id, success=True)

def test_G_zero_tool_mission_behavior():
    parser = ResponseParser()
    res = parser.parse("Hello! I am HERMES, an AI software engineer. How can I help you today?")
    assert hasattr(res, "is_plain_text")
    assert res.is_plain_text is True

def test_H_workspace_path_isolation(tmp_path):
    workspace_manager.lock(str(tmp_path))
    try:
        with pytest.raises(WorkspaceBoundaryError):
            workspace_manager.validate_path("../../../etc/passwd")
    finally:
        workspace_manager.unlock()

def test_I_objective_verification(tmp_path):
    workspace_manager.lock(str(tmp_path))
    try:
        test_file = tmp_path / "valid.py"
        test_file.write_text("x = 1\n", encoding="utf-8")
        gate = VerificationGate()
        passed, checks, issues = gate.run_deterministic_checks(
            tool_name="write_file",
            tool_parameters={"path": str(test_file), "content": "x = 1\n"},
            tool_result_output="Written",
            tool_exit_code=0,
            tool_success=True
        )
        assert passed is True
        assert len(issues) == 0
    finally:
        workspace_manager.unlock()

def test_J_repair_execution():
    handler = ErrorHandler()
    err_res = handler.json_parse_failure("invalid raw response", attempt=0)
    assert err_res.can_retry is True
    assert err_res.recovery_action == RecoveryAction.RETRY_WITH_V2_PROMPT
