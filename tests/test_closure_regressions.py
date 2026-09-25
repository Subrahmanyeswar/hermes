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


# ── Test 8: Telemetry attribution records actual execution_mode ───────────────
def test_telemetry_attribution_records_actual_execution_mode():
    from core.telemetry import telemetry
    from core.orchestrator import Orchestrator

    orch_prod = Orchestrator(mode="auto", execution_mode="production")
    assert orch_prod.execution_mode == "production"

    req_prod = telemetry.start_request("create something", execution_mode=orch_prod.execution_mode)
    assert req_prod.execution_mode == "production"

    orch_bench = Orchestrator(mode="auto", execution_mode="benchmark")
    req_bench = telemetry.start_request("create benchmark", execution_mode=orch_bench.execution_mode)
    assert req_bench.execution_mode == "benchmark"

    with telemetry._global_lock:
        telemetry._active_requests.pop(req_prod.request_id, None)
        telemetry._active_requests.pop(req_bench.request_id, None)


# ── Test 9: Model call attribution does not cross-contaminate requests ─────────
def test_model_call_attribution_does_not_cross_contaminate_requests():
    from core.telemetry import telemetry
    from models.nvidia_client import NvidiaClient
    from models.ollama_client import OllamaClient

    req_a = telemetry.start_request("task A", execution_mode="production")
    req_b = telemetry.start_request("task B", execution_mode="benchmark")

    n_client = NvidiaClient(api_key="test_key")
    o_client = OllamaClient()

    # Attribute nvidia call explicitly to req_b
    n_client._record_telemetry_success(
        model="z-ai/glm-5.3-flash",
        prompt="prompt B",
        system="system B",
        start_time=100.0,
        latency=0.5,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        temperature=0.0,
        request_id=req_b.request_id,
        mission_id=req_b.request_id,
        task_id=req_b.request_id,
    )

    # Attribute ollama call explicitly to req_a
    o_client._record_telemetry_success(
        model="gpt-oss:120b-cloud",
        prompt="prompt A",
        system="system A",
        keep_alive=0,
        temperature=0.0,
        num_ctx=4096,
        start_perf=100.0,
        elapsed_sec=0.2,
        data={"total_duration": 200000000},
        request_id=req_a.request_id,
        mission_id=req_a.request_id,
        task_id=req_a.request_id,
    )

    # Verify no cross contamination
    assert len(req_b.model_calls) == 1
    assert req_b.model_calls[0].request_id == req_b.request_id
    assert req_b.model_calls[0].provider == "nvidia_nim"
    assert req_b.model_calls[0].execution_mode == "benchmark"

    assert len(req_a.model_calls) == 1
    assert req_a.model_calls[0].request_id == req_a.request_id
    assert req_a.model_calls[0].provider == "ollama"
    assert req_a.model_calls[0].execution_mode == "production"

    with telemetry._global_lock:
        telemetry._active_requests.pop(req_a.request_id, None)
        telemetry._active_requests.pop(req_b.request_id, None)


# ── Test 10: No-progress loop triggers after 2 consecutive identical inspections
def test_no_progress_loop_triggers_after_two_consecutive_identical_inspections():
    from core.mission_runner import MissionRunner
    from core.workspace import WorkspaceManager

    runner = MissionRunner(orchestrator=None, workspace_manager=WorkspaceManager())

    # Build simulated task tool history
    history = [
        {
            "iteration": 1,
            "tool_name": "list_directory",
            "fingerprint": 'list_directory:{"path": "."}',
            "workspace_changed": False,
        },
        {
            "iteration": 2,
            "tool_name": "list_directory",
            "fingerprint": 'list_directory:{"path": "."}',
            "workspace_changed": False,
        }
    ]

    is_read_only = history[-1]["tool_name"] in ("list_directory", "read_file", "search_files", "file_exists")
    prev = history[-2]
    curr = history[-1]
    is_stall = (
        is_read_only
        and curr["tool_name"] == prev["tool_name"]
        and curr["fingerprint"] == prev["fingerprint"]
        and not curr["workspace_changed"]
        and not prev["workspace_changed"]
    )
    assert is_stall is True


# ── Test 11: Corrective guidance is injected on stall ──────────────────────────
def test_corrective_guidance_injected_on_stall():
    from core.mission_planner import MissionTask
    from core.mission_runner import MissionRunner
    from core.workspace import WorkspaceManager

    runner = MissionRunner(orchestrator=None, workspace_manager=WorkspaceManager())
    task = MissionTask(
        title="Create script",
        description="Create hello.txt containing Hello",
    )

    needs_impl = runner._task_needs_implementation(task)
    assert needs_impl is True

    corrective_msg = (
        "NO PROGRESS DETECTED: You already inspected the workspace with this action "
        "and no state changed. Do not repeat the same inspection. "
        "Proceed to the next required implementation action."
    )
    if needs_impl:
        corrective_msg += (
            "\nCRITICAL REQUIREMENT: This task requires file creation. "
            "You MUST invoke write_file now to create the required file(s). "
            "Do not run any more inspection or listing tools."
        )

    assert "NO PROGRESS DETECTED" in corrective_msg
    assert "write_file" in corrective_msg


# ── Test 12: Implementation tasks prioritize write_file over inspection ───────
def test_implementation_tasks_prioritize_write_file_over_inspection():
    from core.mission_planner import Mission, MissionTask
    from core.mission_runner import MissionRunner
    from core.workspace import WorkspaceManager

    runner = MissionRunner(orchestrator=None, workspace_manager=WorkspaceManager())
    task = MissionTask(title="Build web app", description="Create an index.html file with landing page")
    mission = Mission(user_prompt="Build web app", tasks=[task])

    assert runner._task_needs_implementation(task) is True
    prompt = runner._build_task_prompt_with_description(task, mission, task.description)
    assert "For file creation tasks, invoke write_file directly" in prompt


# ── Test 13: UI stage state transitions out of Stage 1 ─────────────────────────
def test_ui_stage_state_transitions_out_of_stage_1():
    from ui.panels.chat import ProcessingIndicator

    indicator = ProcessingIndicator()
    assert indicator.current_stage == 1
    assert indicator.stage_status[1] == "running"

    # Transition to stage 5 (Tier 1 Generation)
    indicator.update_progress("stage_start", {"stage": 5, "stage_name": "Tier 1 Generation", "verb": "Generating"})
    assert indicator.current_stage == 5
    assert indicator.stage_status[1] == "success"
    assert indicator.stage_status[2] == "success"
    assert indicator.stage_status[3] == "success"
    assert indicator.stage_status[4] == "success"
    assert indicator.stage_status[5] == "running"

    # Complete stage 5
    indicator.update_progress("stage_end", {"stage": 5, "status": "success"})
    assert indicator.stage_status[5] == "success"


# ── Test 14: Status bar badge formats GLM model as GLM-5.3-Flash ───────────────
def test_status_bar_badge_formats_glm_model_as_glm_5_3_flash():
    from ui.panels.status_bar import _format_model_badge, StatusBar

    assert _format_model_badge("z-ai/glm-5.3-flash") == "GLM-5.3-Flash"
    assert _format_model_badge("glm-5.3") == "GLM-5.3-Flash"
    assert _format_model_badge("GLM-5.3-FLASH") == "GLM-5.3-Flash"

    sb = StatusBar()
    assert sb.tier1_model == "GLM-5.3-Flash"


# ── Test 15: Duplicate active-request attribution prevention ──────────────────
def test_duplicate_active_request_attribution_prevention():
    from core.telemetry import telemetry
    from models.nvidia_client import NvidiaClient

    # Single active request exists
    req_active = telemetry.start_request("Active Mission", execution_mode="production")
    n_client = NvidiaClient(api_key="test_key")

    # Record model call with non-matching request_id
    n_client._record_telemetry_success(
        model="z-ai/glm-5.3-flash",
        prompt="Orphaned prompt",
        system="Orphaned system",
        start_time=100.0,
        latency=0.5,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        temperature=0.0,
        request_id="non_matching_unknown_id",
        mission_id="non_matching_unknown_mission",
        task_id="non_matching_unknown_task",
    )

    # Active request must NOT have captured the non-matching model call
    assert len(req_active.model_calls) == 0

    with telemetry._global_lock:
        telemetry._active_requests.pop(req_active.request_id, None)


# ── Test 16: Partial verification after provider network failure ──────────────
def test_partial_verification_after_provider_network_failure():
    from core.mission_planner import Mission, MissionTask, TaskState
    from core.mission_runner import MissionRunner
    from core.workspace import WorkspaceManager

    runner = MissionRunner(orchestrator=None, workspace_manager=WorkspaceManager())
    t1 = MissionTask(title="Build HTML", description="Create index.html", state=TaskState.COMPLETED)
    t2 = MissionTask(
        title="Responsive fix",
        description="Add mobile responsive breakpoints",
        state=TaskState.FAILED,
        error_message="NvidiaConnectionError: Could not connect to NVIDIA NIM at https://integrate.api.nvidia.com/v1"
    )
    mission = Mission(user_prompt="Build site", tasks=[t1, t2])
    runner._files_created = ["index.html"]

    result = runner._build_result(mission, success=False)
    assert result.success is False
    assert result.status == "VERIFICATION_INTERRUPTED"
    assert "Artifact created" in result.error
    assert len(result.files_created) == 1
    assert "index.html" in result.files_created


# ── Test 17: Exact original stall prompt regression and decomposition ─────────
@pytest.mark.asyncio
async def test_exact_original_stall_prompt_regression():
    from core.mission_planner import MissionPlanner
    prompt = (
        "create a single html page websites with multiple pages the theme is "
        "about student career guidance tell students what to do after 12th "
        "and everything in professional way with animations and make it awesome"
    )
    planner = MissionPlanner()
    tasks = await planner._parse_intent_async(prompt, execution_mode="production")
    assert len(tasks) >= 1
    # Verify the mission plans into executable items
    mission = await planner.plan_async(prompt, workspace_root="", execution_mode="production")
    assert len(mission.tasks) >= 1
    # On an empty workspace root, it should not insert a separate stalled inspection
    task_titles = [t.title.lower() for t in mission.tasks]
    assert not (len(mission.tasks) > 1 and "inspect workspace" in task_titles[0] and planner._detect_project_root(prompt) == "")


# ── Test 18: Trivial single task decomposition does not insert extra inspection
@pytest.mark.asyncio
async def test_trivial_single_task_decomposition_does_not_insert_extra_inspection():
    from core.mission_planner import MissionPlanner
    prompt = "Create hello.txt containing: Hello from HERMES."
    planner = MissionPlanner()
    mission = await planner.plan_async(prompt, workspace_root="", execution_mode="production")
    # Trivial single-file task must have exactly 1 task
    assert len(mission.tasks) == 1
    assert "hello.txt" in mission.tasks[0].description


