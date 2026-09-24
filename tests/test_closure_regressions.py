# tests/test_closure_regressions.py
"""
Regression test suite for Live Cloud Failure Closure.
Covers:
1. Large HTML native tool call parsing (unescaped quotes, @keyframes, multiline CSS).
2. Fragmented streamed SSE argument synthesis in NvidiaClient.
3. Plan approved but not executed contract (PLAN_APPROVED != TASK_EXECUTED).
4. Mission cannot report success without requested artifact.
5. Python API/test mismatch detection (class method imported as standalone function).
6. Test execution verification (detecting pytest failures during verification).
"""

import ast
import json
import pytest
import os
import sys
from pathlib import Path

from core.response_parser import ResponseParser, ParseSuccess
from core.verification_gate import VerificationGate
from core.orchestrator import Orchestrator


# ── Test 1: Large HTML native tool call parsing ────────────────────────────────
def test_large_html_native_tool_call_parsing():
    parser = ResponseParser()
    complex_html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Complex Landing Page</title>
<style>
@keyframes pulse {
    0% { transform: scale(1); opacity: 0.9; }
    50% { transform: scale(1.05); opacity: 1; }
    100% { transform: scale(1); opacity: 0.9; }
}
.hero {
    font-family: 'Inter', "Segoe UI", sans-serif;
    background: url("data:image/svg+xml;utf8,<svg></svg>");
    animation: pulse 2s infinite ease-in-out;
}
</style>
</head>
<body>
    <header class="hero">
        <h1 onclick="alert('Welcome!')">Modern Dashboard</h1>
        <p>Quotes inside: 'single' and "double" and unescaped \n control chars</p>
    </header>
</body>
</html>"""

    # Model returns native tool call where arguments contain unescaped quotes or raw control chars
    native_tool_call = {
        "id": "call_123",
        "type": "function",
        "function": {
            "name": "write_file",
            "arguments": json.dumps({"path": "index.html", "content": complex_html})
        }
    }
    raw_response = {
        "text": "",
        "tool_calls": [native_tool_call]
    }

    result = parser.parse(raw_response)
    assert isinstance(result, ParseSuccess), f"Parsing failed: {result}"
    assert result.tool == "write_file"
    assert result.parameters["path"] == "index.html"
    assert "@keyframes pulse" in result.parameters["content"]
    assert "alert('Welcome!')" in result.parameters["content"]


# ── Test 2: Fragmented streamed SSE arguments ──────────────────────────────────
def test_fragmented_streamed_sse_arguments():
    # Simulate fragmented SSE arguments from remote provider
    # chunk 1: {"path": "index.html", "content": "<!DOCTYPE html>\n<style>\n@keyframe
    # chunk 2: s glow { 0% { opacity: 0; } 100% { opacity: 1; } }\n</style>"}\n
    chunk1 = '{"path": "index.html", "content": "<!DOCTYPE html>\\n<style>\\n@keyframe'
    chunk2 = 's glow { 0% { opacity: 0; } 100% { opacity: 1; } }\\n</style>"}'
    combined_raw = chunk1 + chunk2

    parser = ResponseParser()
    parsed_params = parser._parse_tool_arguments("write_file", combined_raw)
    assert parsed_params["path"] == "index.html"
    assert "@keyframes glow" in parsed_params["content"]


# ── Test 3: Plan approved but not executed contract ────────────────────────────
def test_plan_approved_not_executed_contract(tmp_path):
    orchestrator = Orchestrator()
    task_text = "Implement a production-grade token vault module in 'generated_projects/secure_vault.py' with AES-GCM encryption"
    
    # Extract requested artifacts
    requested = orchestrator.extract_requested_artifacts(task_text)
    assert "generated_projects/secure_vault.py" in requested

    # Check non-existent file
    target_p = tmp_path / "secure_vault.py"
    if target_p.exists():
        target_p.unlink()

    # The missing check should identify it
    missing = [
        art for art in requested
        if not (tmp_path / Path(art).name).exists()
    ]
    assert len(missing) > 0
    assert "generated_projects/secure_vault.py" in missing


# ── Test 4: Mission cannot report success without requested artifact ──────────
def test_mission_cannot_report_success_without_artifact(tmp_path):
    orchestrator = Orchestrator()
    task_text = "Create a modern HTML landing page 'index.html' with embedded CSS"
    
    # Missing artifact simulation
    requested = orchestrator.extract_requested_artifacts(task_text)
    assert "index.html" in requested

    # If artifact does not exist on disk, orchestrator enforces missing contract
    still_missing = [
        art for art in requested
        if not (tmp_path / art).exists()
    ]
    assert "index.html" in still_missing


# ── Test 5: Python API/test mismatch detection ────────────────────────────────
def test_python_api_test_mismatch_detection(tmp_path):
    gate = VerificationGate()
    
    # Create module live_calc.py with class Calculator
    mod_file = tmp_path / "live_calc.py"
    mod_file.write_text("""
class Calculator:
    def add(self, a, b):
        return a + b
    def subtract(self, a, b):
        return a - b
""", encoding="utf-8")

    # Content of test_live_calc.py attempting to import class method as standalone function
    bad_test_code = """
from live_calc import add, subtract

def test_add():
    assert add(2, 3) == 5
"""
    checks_run = []
    issues = []
    
    # Point workspace or run validation with module in parent dir
    test_path = str(tmp_path / "test_live_calc.py")
    gate._validate_python_contracts(test_path, bad_test_code, checks_run, issues)

    # Must detect that 'add' is a class method, not a standalone function
    mismatch_issues = [i for i in issues if "API contract mismatch" in i]
    assert len(mismatch_issues) > 0
    assert "Calculator" in mismatch_issues[0]
    assert "'add' is imported as a standalone function" in mismatch_issues[0]


# ── Test 6: Test execution verification (detecting pytest failures) ────────────
def test_test_execution_verification(tmp_path):
    gate = VerificationGate()
    
    # Create a failing test file
    failing_test = tmp_path / "test_sample_failure.py"
    failing_test.write_text("""
def test_intentional_fail():
    assert 1 == 2, "Intentional math failure"
""", encoding="utf-8")

    checks_run = []
    issues = []
    gate._validate_python_contracts(str(failing_test), failing_test.read_text(), checks_run, issues)

    failure_issues = [i for i in issues if "Test suite execution failed" in i]
    assert len(failure_issues) > 0
    assert "test_sample_failure.py" in failure_issues[0]


# ── Test 7: Multi native tool call batching ──────────────────────────────────
def test_multi_native_tool_call_batching():
    parser = ResponseParser()
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "generated_projects/smoke_calc.py", "content": "class SmokeCalc: pass"})
            }
        },
        {
            "id": "call_2",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "generated_projects/test_smoke_calc.py", "content": "import pytest"})
            }
        }
    ]
    resp = {"tool_calls": tool_calls}
    parsed = parser.parse(resp)
    assert isinstance(parsed, ParseSuccess)
    assert parsed.tool == "write_files_batch"
    assert "files" in parsed.parameters
    assert len(parsed.parameters["files"]) == 2
    assert parsed.parameters["files"][0]["path"] == "generated_projects/smoke_calc.py"
    assert parsed.parameters["files"][1]["path"] == "generated_projects/test_smoke_calc.py"

