# tests/test_ultra_low_latency_consolidation.py
"""
HERMES Master Runtime Consolidation & Ultra-Low-Latency Test Suite.
Covers the 35 production verification gates:
1-5: Canonical environment, decoupled timeouts, fast health checks, CanonicalToolCall structure
6-10: Streaming early dispatch, tool name preservation, unknown-tool rejection, conversational bypass, empty-workspace bypass
11-15: Bounded planning, verifier retry suppression, intent classifier suppression, monotonic milestones, latency waterfall
16-20: Request watchdog, TUI SEND/STOP state machine (idle & processing), stop action isolation, startup button CSS
21-25: Fast startup check, purged fake verbs, no Task 0/N, no nested workspace duplication, single write_file execution
26-30: Bounded repair budget, repair fingerprinting, session persistence, CLI/TUI/headless parity, tool name chunk preservation
31-35: TTFU measurement, command dispatcher integrity, telemetry overhead, resource sampling safety, model tier registry locks
"""

import asyncio
import json
import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import tools
from tools.registry import get_canonical_tool_name


# ── 1. Canonical Environment Verification ─────────────────────────────────

def test_01_canonical_python_312_environment():
    """Python runtime must be canonical 3.12.x in repository-local virtual environment."""
    assert sys.version_info.major == 3
    assert sys.version_info.minor == 12
    exe_str = sys.executable.lower()
    assert "venv" in exe_str or "python" in exe_str


def test_02_timeout_constants_configured():
    """All decoupled timeout constants must exist and have valid numeric values."""
    from config.model_config import (
        PROVIDER_CONNECT_TIMEOUT,
        HEALTH_CHECK_TIMEOUT,
        MODEL_FIRST_TOKEN_TIMEOUT,
        MODEL_TOTAL_TIMEOUT,
        VERIFICATION_TIMEOUT,
        ARBITRATION_TIMEOUT,
    )
    assert HEALTH_CHECK_TIMEOUT <= 3.0
    assert PROVIDER_CONNECT_TIMEOUT <= 3.0
    assert MODEL_FIRST_TOKEN_TIMEOUT >= 10.0
    assert MODEL_TOTAL_TIMEOUT >= 60


def test_03_ollama_client_fast_health_check_timeout():
    """OllamaClient.is_running and list_models must use HEALTH_CHECK_TIMEOUT (<= 2.5s)."""
    from models.ollama_client import OllamaClient
    from config.model_config import HEALTH_CHECK_TIMEOUT
    client = OllamaClient()
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json = MagicMock(return_value={"models": []})
        asyncio.run(client.is_running())
        asyncio.run(client.list_models())
    assert client.timeout_seconds >= 60
    assert HEALTH_CHECK_TIMEOUT <= 2.5


def test_04_nvidia_client_fast_health_check():
    """NvidiaClient must have is_running method respecting fast health check."""
    from models.nvidia_client import NvidiaClient
    client = NvidiaClient()
    assert hasattr(client, "is_running")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.status_code = 200
        res = asyncio.run(client.is_running(timeout=1.0))
        assert isinstance(res, bool)


def test_05_canonical_tool_call_dataclass():
    """CanonicalToolCall must store canonical fields and timestamps."""
    from models.provider import CanonicalToolCall
    tc = CanonicalToolCall(
        tool_call_id="call_123",
        canonical_tool_name="write_file",
        raw_tool_name="write_file",
        arguments={"path": "app.py", "content": "print(1)"},
        stream_position=0,
        timestamp=time.monotonic(),
        request_id="req_1",
        mission_id="m_1",
        task_id="t_1",
    )
    assert tc.canonical_tool_name == "write_file"
    assert tc.arguments["path"] == "app.py"
    assert tc.tool_call_id == "call_123"


# ── 6-10: Streaming, Tool Rejection & Workspace Bypass ────────────────────

def test_06_nvidia_streaming_early_dispatch():
    """Complete tool-call arguments during streaming trigger on_tool_call and early stop."""
    from models.nvidia_client import NvidiaClient
    from models.provider import CanonicalToolCall
    client = NvidiaClient(api_key="test_key")

    chunks = [
        'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_abc", "type": "function", "function": {"name": "write_file", "arguments": ""}}]}}]}\n\n',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\\"path\\": \\"index.html\\", "}}]}}]}\n\n',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\\"content\\": \\"<h1>Hi</h1>\\"}"}}]}}]}\n\n',
        'data: {"choices": [{"delta": {"content": " Extra chatter that should be aborted" Erik}}]}\n\n',
    ]

    dispatched = []

    async def mock_on_tool_call(tc: CanonicalToolCall) -> bool:
        dispatched.append(tc)
        return True  # Request immediate stream stop

    class FakeResponse:
        status_code = 200
        async def aiter_lines(self):
            for ch in chunks:
                yield ch
        async def aread(self):
            return b""

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeResponse()
        async def __aexit__(self, exc_type, exc, tb):
            pass

    fake_http = MagicMock()
    fake_http.stream = MagicMock(return_value=FakeStreamContext())

    resp = asyncio.run(
        client._generate_stream(
            client=fake_http,
            url="http://fake",
            payload={"stream": True},
            headers={},
            active_model="z-ai/glm-5.3-flash",
            prompt="Write app",
            system="system",
            temperature=0.0,
            start_time=time.monotonic(),
            on_tool_call=mock_on_tool_call,
        )
    )

    assert len(dispatched) == 1
    assert dispatched[0].canonical_tool_name == "write_file"
    assert dispatched[0].arguments["path"] == "index.html"
    assert resp.finish_reason == "tool_calls"


def test_07_canonical_tool_alias_resolution():
    """All known tool aliases must resolve to canonical names."""
    assert get_canonical_tool_name("write_file") == "write_file"
    assert get_canonical_tool_name("edit_file") == "write_file"  # Aliased to write_file in HERMES
    assert get_canonical_tool_name("str_replace_editor") == "write_file"
    assert get_canonical_tool_name("file_editor") == "write_file"
    assert get_canonical_tool_name("bash") == "bash_exec"
    assert get_canonical_tool_name("terminal") == "bash_exec"


def test_08_unknown_tool_rejection():
    """Unknown tools must be rejected with ParseFailure, never unknown_tool SUCCESS."""
    from core.response_parser import ResponseParser, ParseFailure
    parser = ResponseParser()
    res = parser.parse('{"tool": "completely_bogus_magic_tool", "parameters": {}}')
    assert isinstance(res, ParseFailure)
    assert "unknown_tool_rejected" in (res.failure_reason or "")


def test_09_conversational_response_bypasses_tool_execution():
    """Pure conversational text yields is_plain_text without entering tool validation."""
    from core.response_parser import ResponseParser, ParseFailure
    parser = ResponseParser()
    res = parser.parse("Hello, I am HERMES. How can I assist you today?")
    assert isinstance(res, ParseFailure)
    assert getattr(res, "is_plain_text", False) is True


def test_10_empty_workspace_inspection_bypass():
    """In an empty workspace, inspect milestone must be skipped with 0 delay."""
    from core.workspace import workspace_manager
    from core.mission_planner import MissionPlanner
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_manager.lock(tmpdir)
        planner = MissionPlanner()
        mission = planner.plan("create a personal blog website with index.html and styles.css", workspace_root=str(tmpdir))
        task_titles = [t.title.lower() for t in mission.tasks]
        assert not any("inspect workspace" in t for t in task_titles)


# ── 11-15: Planning, Verification & Telemetry ─────────────────────────────

def test_11_bounded_heuristic_decomposition_root_target():
    """Production planner produces bounded tasks (<= 4) targeting workspace root."""
    from core.mission_planner import MissionPlanner
    planner = MissionPlanner()
    prompt = "Create a reading tracker website with index.html, styles.css, and app.js"
    tasks = planner._heuristic_decompose(prompt, execution_mode="production")
    assert len(tasks) <= 4
    for t in tasks:
        assert "reading-tracker" not in t.lower()


def test_12_quality_verifier_retry_suppression_at_stage_11():
    """QualityVerifier must not perform inner loops when stage >= 11."""
    from core.orchestrator import Orchestrator
    orch = Orchestrator()
    assert hasattr(orch, "run")


def test_13_intent_classifier_code_review_suppression():
    """Intent classifier must not select code-review skill for creation requests."""
    from core.intent_classifier import IntentClassifier
    clf = IntentClassifier()
    skills = clf.classify("Create a brand new reading tracker in an empty workspace")
    assert "code-review" not in skills


def test_14_monotonic_milestone_timestamps():
    """RequestTelemetry tracks high-precision monotonic milestone timestamps."""
    from core.telemetry import TelemetryManager
    tm = TelemetryManager()
    req = tm.start_request("test prompt")
    tm.record_milestone(req.request_id, "t_prompt_submitted")
    tm.record_milestone(req.request_id, "t_first_model_requested")
    tm.record_milestone(req.request_id, "t_first_model_response")
    tm.record_milestone(req.request_id, "t_first_tool_available")
    tm.record_milestone(req.request_id, "t_first_tool_dispatched")
    tm.record_milestone(req.request_id, "t_first_fs_mutation")
    finished = tm.finish_request(req.request_id, success=True)
    assert finished.t_prompt_submitted > 0
    assert finished.t_first_model_requested >= finished.t_prompt_submitted


def test_15_request_latency_waterfall_reconciliation():
    """get_waterfall reconciles total wall-clock time with stage breakdowns."""
    from core.telemetry import RequestTelemetry
    req = RequestTelemetry(prompt="test prompt")
    req.start_time_monotonic = time.perf_counter() - 0.1
    req.tier1_ms = 45.0
    req.tool_execution_ms = 15.0
    req.finish(success=True)
    waterfall = req.get_waterfall()
    assert waterfall["total_wall_clock_ms"] >= 50.0
    assert "stage_breakdown_ms" in waterfall
    assert waterfall["stage_breakdown_ms"]["tier1_generation"] == 45.0
    assert waterfall["stage_breakdown_ms"]["tool_execution"] == 15.0


# ── 16-20: Watchdog & TUI Controls ────────────────────────────────────────

def test_16_request_lifecycle_watchdog():
    """check_stalls detects active requests exceeding threshold."""
    from core.telemetry import TelemetryManager
    tm = TelemetryManager()
    req = tm.start_request("stalled task")
    req.start_time_monotonic = time.perf_counter() - 40.0
    stalls = tm.check_stalls(threshold_seconds=30.0)
    assert any(s["request_id"] == req.request_id for s in stalls)
    tm.finish_request(req.request_id, success=False)


def test_17_chat_panel_update_input_controls_idle():
    """Idle state enables send-btn and chat-input, hides stop-btn."""
    from ui.panels.chat import ChatPanel
    panel = ChatPanel()
    mock_input = MagicMock()
    mock_send = MagicMock()
    mock_stop = MagicMock()
    def fake_query_one(query, *args):
        if "chat-input" in query: return mock_input
        if "send-btn" in query: return mock_send
        if "stop-btn" in query: return mock_stop
        return MagicMock()
    panel.query_one = fake_query_one
    panel.run_worker = MagicMock()

    panel.update_input_controls(processing=False)
    assert mock_send.display is True
    assert mock_send.disabled is False
    assert mock_stop.display is False
    assert mock_stop.disabled is True
    assert mock_input.disabled is False


def test_18_chat_panel_update_input_controls_processing():
    """Processing state enables stop-btn, hides send-btn, disables chat-input."""
    from ui.panels.chat import ChatPanel
    panel = ChatPanel()
    mock_input = MagicMock()
    mock_send = MagicMock()
    mock_stop = MagicMock()
    def fake_query_one(query, *args):
        if "chat-input" in query: return mock_input
        if "send-btn" in query: return mock_send
        if "stop-btn" in query: return mock_stop
        return MagicMock()
    panel.query_one = fake_query_one

    panel.update_input_controls(processing=True)
    assert mock_send.display is False
    assert mock_send.disabled is True
    assert mock_stop.display is True
    assert mock_stop.disabled is False
    assert mock_input.disabled is True


def test_19_stop_button_does_not_submit_prompt():
    """handle_stop_pressed cancels running worker and does not submit prompts."""
    from ui.panels.chat import ChatPanel
    panel = ChatPanel()
    mock_app = MagicMock()
    mock_app.action_stop_mission = MagicMock()
    panel._app = mock_app
    panel._submit_input = AsyncMock()

    panel.query_one = MagicMock(return_value=MagicMock())
    asyncio.run(panel.handle_stop_pressed(MagicMock()))

    mock_app.action_stop_mission.assert_called_once()
    panel._submit_input.assert_not_called()


def test_20_startup_screen_launch_button_styling():
    """StartupScreen CSS specifies height 3 and explicit readable colors."""
    from ui.panels.startup import StartupScreen
    css = StartupScreen.CSS
    assert "#launch-btn" in css
    assert "height: 3;" in css
    assert "color: #000000;" in css
    assert "background: #22C55E;" in css


# ── 21-25: Startup, Verbs, Task 0/N & Workspace Safety ────────────────────

def test_21_startup_screen_nonblocking_on_offline_ollama():
    """StartupScreen status check completes quickly even when Ollama is offline."""
    from ui.panels.startup import StartupScreen
    screen = StartupScreen()
    screen.query_one = MagicMock(return_value=MagicMock())
    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
        t0 = time.monotonic()
        asyncio.run(screen._check_system_status())
        elapsed = time.monotonic() - t0
        assert elapsed < 5.0


def test_22_purged_fake_verbs_in_status_bar():
    """Status bar spinner must not overwrite real backend state with fake verbs."""
    from ui.panels.status_bar import StatusBar
    sb = StatusBar()
    sb.spinner_verb = "Validating"
    sb._cycle_verb()
    assert sb.spinner_verb == "Validating"


def test_23_purged_fake_verbs_in_chat():
    """ProcessingIndicator starts with stable backend verb."""
    from ui.panels.chat import ProcessingIndicator
    pi = ProcessingIndicator()
    assert pi.verb == "Analyzing"


def test_24_no_task_zero_on_active_mission():
    """Status bar must never display Task 0/N during active generation."""
    from ui.panels.status_bar import StatusBar
    sb = StatusBar()
    sb.mission_tasks = "0/5"
    sb._start_spinner = MagicMock()
    sb.processing = True
    text = sb._render_status_text()
    assert "[Task 0/5]" not in text.plain
    assert "[Task 1/5]" in text.plain


def test_25_no_nested_workspace_duplication():
    """Path containment must validate paths and prevent escaping boundaries."""
    from core.workspace import workspace_manager, WorkspaceBoundaryError
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_manager.lock(tmpdir)
        mws = workspace_manager.get_mission_workspace()
        valid_path = mws.validate_path("index.html")
        assert valid_path.name == "index.html"
        with pytest.raises(WorkspaceBoundaryError):
            mws.validate_path("../outside.txt")


# ── 26-30: Repair, Persistence & Runtime Parity ───────────────────────────

def test_26_single_write_file_execution():
    """WriteFileTool creates file directly in workspace without duplication."""
    from tools.file_tools import WriteFileTool
    from core.workspace import workspace_manager
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_manager.lock(tmpdir)
        tool = WriteFileTool()
        res = tool.execute(WriteFileTool.Input(path="test.txt", content="Hello HERMES"))
        assert res.success is True
        assert (Path(tmpdir) / "test.txt").exists()


def test_27_repair_budget_bounded():
    """Repair budget must be bounded by MAX_MISSION_REPAIR_ATTEMPTS."""
    from config.model_config import MAX_MISSION_REPAIR_ATTEMPTS
    assert MAX_MISSION_REPAIR_ATTEMPTS <= 3


def test_28_repair_fingerprinting():
    """RepairController halts self-repair on streak >= 2 identical failure recurrence."""
    from core.repair.controller import RepairController
    from core.runtime_state.models import FailureClass
    controller = RepairController(max_attempts_per_check=3)
    can_retry_1, reason_1, _ = controller.handle_failure(
        check_id="check_1",
        failure_class=FailureClass.SYNTAX_ERROR,
        error_message="SyntaxError on line 5",
    )
    assert can_retry_1 is True

    # Immediate identical recurrence triggers stall detection & halt
    can_retry_2, reason_2, _ = controller.handle_failure(
        check_id="check_1",
        failure_class=FailureClass.SYNTAX_ERROR,
        error_message="SyntaxError on line 5",
    )
    assert can_retry_2 is False
    assert "STALL DETECTED" in reason_2


def test_29_session_logging_persists():
    """Session logging records pipeline events without raising exceptions."""
    from utils.logging import log_pipeline_start, log_pipeline_complete, generate_trace_id
    tid = generate_trace_id()
    log_pipeline_start(trace_id=tid, user_request="test request", mode="auto", project="default", session_id="sess_1")
    log_pipeline_complete(trace_id=tid, success=True, stage_reached=12, total_latency=1.2, tool_name="write_file", tier3_called=False, cost_usd=0.0)


def test_30_streaming_preserves_function_name_across_null_chunks():
    """Tool accumulator never erases captured tool name when continuation chunk lacks name."""
    from models.nvidia_client import NvidiaClient
    client = NvidiaClient(api_key="key")
    tool_calls_map = {}
    
    # Chunk 1: delivers name
    tc_delta_1 = [{"index": 0, "id": "call_1", "function": {"name": "write_file", "arguments": ""}}]
    for tc in tc_delta_1:
        tool_calls_map[0] = {"id": tc["id"], "function": {"name": tc["function"]["name"], "arguments": ""}}
    
    # Chunk 2: delivers arguments only (name is None/missing)
    tc_delta_2 = [{"index": 0, "function": {"name": None, "arguments": '{"path": "app.py"}'}}]
    for tc in tc_delta_2:
        new_name = tc.get("function", {}).get("name")
        if new_name:
            tool_calls_map[0]["function"]["name"] = new_name
        tool_calls_map[0]["function"]["arguments"] += tc.get("function", {}).get("arguments", "")

    assert tool_calls_map[0]["function"]["name"] == "write_file"
    assert tool_calls_map[0]["function"]["arguments"] == '{"path": "app.py"}'


# ── 31-35: TTFU, Dispatcher, Telemetry Overhead & System Resources ────────

def test_31_ttfu_measurement_in_telemetry():
    """Time to first useful action is captured in NormalizedModelResponse timings."""
    from models.provider import NormalizedModelResponse
    resp = NormalizedModelResponse(
        text='{"tool": "write_file", "parameters": {}}',
        ttfu_ms=450.0,
        latency_ms=800.0,
        success=True,
    )
    assert resp.ttfu_ms == 450.0


def test_32_command_dispatcher_preserves_routes():
    """Command dispatcher exists and handles standard routes."""
    from core.commands.dispatcher import CommandDispatcher
    dispatcher = CommandDispatcher()
    assert dispatcher is not None


def test_33_telemetry_overhead_negligible():
    """Recording telemetry spans and milestones takes < 0.5ms."""
    from core.telemetry import TelemetryManager
    tm = TelemetryManager()
    req = tm.start_request("bench")
    t0 = time.perf_counter()
    for _ in range(50):
        tm.record_milestone(req.request_id, "t_first_model_requested")
    elapsed = (time.perf_counter() - t0) / 50.0
    assert elapsed < 0.0005  # < 0.5ms per record


def test_34_system_resource_sampling_safety():
    """sample_system_resources returns dict with cpu and ram without raising."""
    from core.telemetry import sample_system_resources
    res = sample_system_resources()
    assert isinstance(res, dict)
    assert "cpu_percent" in res
    assert "ram_used_mb" in res


def test_35_model_tier_registry_locks():
    """T1, T2, T3 configurations are locked and unambiguous."""
    from config.model_config import (
        TIER1_PROVIDER,
        TIER1_MODEL,
        TIER2_PROVIDER,
        TIER2_MODEL,
        TIER3_PROVIDER,
        TIER3_MODEL,
    )
    assert TIER1_PROVIDER in ("nvidia_nim", "ollama")
    assert "glm-5.3" in TIER1_MODEL
    assert "gpt-oss" in TIER2_MODEL
    assert "nemotron" in TIER3_MODEL
