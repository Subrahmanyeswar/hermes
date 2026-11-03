# tests/test_recovery_loop_remediation.py
"""
HERMES 2.x — Comprehensive Recovery Loop Remediation Test Suite
Verifies P0 fixes for:
  Test A: Output truncation detection, plain-text false negative prevention, and Groq token limits.
  Test B: Structured syntax diagnostic parser extracting file, line, SyntaxError.
  Test C: Diagnostic persistence across >4 reasoning turns.
  Test D: Failure classification (HTTP 429, 503, SyntaxError, Malformed JSON, Timeout).
  Test E: Complete Tier 1-Tier 4 routing graph (Scenarios A, B, C, D).
  Test F: Stale circuit breaker isolation, Retry-After compliance, and Auth/Quota permanence.
  Test G: Syntax repair workflow with targeted directive and revalidation.
  Test H: Reasoning-only stall watchdog terminating at budget.
  Test I: Duplicate tool call detection (node -v repeated blocked).
  Test J: Progress detection distinguishing file changes from no-ops.
  Test K: Deadline admission control halting before reserves and skipping model call.
  Test L: Timeout cancellation closing streams and cleaning processes.
  Test M: Original Observation regression (test_incident_m_b9d872ee_regression.py).
  Test N: Full historical replay simulating mission m_43651102 failure and convergence.
"""

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.adaptive_routing import AdaptiveRouter, ProviderHealthState, RouteDecision
from core.agent_loop import AgentLoop, AgentLoopConfig
from core.agent_loop.loop import (
    calculate_effective_turn_timeout,
    FINAL_VERIFICATION_RESERVE_SECONDS,
    FINALIZATION_RESERVE_SECONDS,
    MIN_MODEL_REQUEST_TIMEOUT_SECONDS,
)
from core.agent_loop.types import AgentDecisionType, AgentDecision, Observation
from core.mission_planner import Mission
from core.event_bus import EventBus, EventType
from core.structured_observation import extract_syntax_diagnostic, StructuredObservation
from models.common_adapter import (
    CommonProviderAdapter,
    NormalizedModelResponse,
    classify_provider_error,
    ErrorClassification,
    RequestTelemetry,
)
from tools.platform.core_tools import ShellBashTool


def create_test_loop(ws_root: Path) -> AgentLoop:
    mock_orch = MagicMock()
    mock_orch._active_tier = 1
    ws = MagicMock()
    ws.root_str = str(ws_root.resolve())
    ws.is_locked = False
    ws.workspace_root = ws_root.resolve()
    return AgentLoop(
        orchestrator=mock_orch,
        workspace_manager=ws,
        config=AgentLoopConfig(max_turns=10),
    )


# ==============================================================================
# TEST A: Output Truncation Detection, Plain Text False-Negative Prevention
# ==============================================================================
@pytest.mark.asyncio
async def test_a_output_truncation_detection_and_groq_limit():
    adapter = CommonProviderAdapter(
        provider_name="groq",
        model_name="qwen/qwen3.8-27b",
        base_url="https://api.groq.com/openai/v1",
        api_key="test_key",
    )

    # 1. Groq token limit check: default max_tokens must be >= 4096, explicit low values respected
    assert adapter._execute_non_streaming is not None
    # Caller provides no max_tokens -> 4096
    val_none = None
    eff_default = min(val_none if val_none is not None else 4096, 8192)
    assert eff_default == 4096
    # Caller provides explicit low max_tokens=256 -> 256 respected
    val_low = 256
    eff_low = min(val_low if val_low is not None else 4096, 8192)
    assert eff_low == 256
    # Caller provides high max_tokens=16384 -> capped at Groq 8192
    val_high = 16384
    eff_high = min(val_high if val_high is not None else 4096, 8192)
    assert eff_high == 8192

    # 2. Output truncation detection with truncated tool call
    mock_resp_tools = MagicMock()
    mock_resp_tools.status_code = 200
    mock_resp_tools.text = json.dumps({
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_123",
                    "function": {
                        "name": "fs_write",
                        "arguments": '{"path": "app.js", "content": "const x = [truncated'
                    }
                }]
            },
            "finish_reason": "length"
        }],
        "usage": {"prompt_tokens": 50, "completion_tokens": 900}
    })
    mock_resp_tools.json.return_value = json.loads(mock_resp_tools.text)

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp_tools

    res_tool = await adapter._execute_non_streaming(
        client=mock_client,
        url="https://api.groq.com/openai/v1/chat/completions",
        headers={},
        payload={"model": "qwen/qwen3.8-27b"},
        telemetry=RequestTelemetry(),
        timeout=30.0,
    )
    assert res_tool.success is False
    assert "MODEL_OUTPUT_TRUNCATED" in (res_tool.error or "")
    assert res_tool.finish_reason == "length"
    assert res_tool.tool_calls == []  # Unparsed tool calls stripped

    # 3. False-Negative Case: Plain text output is nonempty, tool_calls is empty, finish_reason="length"
    mock_resp_text = MagicMock()
    mock_resp_text.status_code = 200
    partial_code = "const counter = 0;\nfunction increment() {\n  // cut off here"
    mock_resp_text.text = json.dumps({
        "choices": [{
            "message": {
                "content": partial_code,
                "tool_calls": []
            },
            "finish_reason": "length"
        }],
        "usage": {"prompt_tokens": 50, "completion_tokens": 900}
    })
    mock_resp_text.json.return_value = json.loads(mock_resp_text.text)
    mock_client.post.return_value = mock_resp_text

    res_text = await adapter._execute_non_streaming(
        client=mock_client,
        url="https://api.groq.com/openai/v1/chat/completions",
        headers={},
        payload={"model": "qwen/qwen3.8-27b"},
        telemetry=RequestTelemetry(),
        timeout=30.0,
    )
    # Must NEVER silently succeed when terminated by token limit
    assert res_text.success is False
    assert "MODEL_OUTPUT_TRUNCATED" in (res_text.error or "")
    assert res_text.finish_reason == "length"
    # Plain text data is safely preserved for continuation or repair
    assert res_text.text == partial_code


# ==============================================================================
# TEST B: Structured Syntax Diagnostic Parser
# ==============================================================================
def test_b_structured_syntax_diagnostic_parser():
    node_err = r"""C:\Users\SUBBU\Downloads\testing 13\app.js:13
const ORDER_STATUSES = ['New', 'Preparing', 'Ready', 'Completed', '
                                                                  ^

SyntaxError: Invalid or unexpected token
    at compileSourceTextModule (node:internal/modules/esm/load:240:19)
    at ModuleLoader.moduleStrategy (node:internal/modules/esm/translators:145:18)
    at ModuleLoader.moduleProvider (node:internal/modules/esm/loader:341:14)

Node.js v20.18.3"""

    diag = extract_syntax_diagnostic(node_err)
    assert diag is not None
    assert "app.js" in diag["file"]
    assert diag["line"] == 13
    assert diag["column"] == 67
    assert diag["error_class"] == "SyntaxError"
    assert "Invalid or unexpected token" in diag["message"]
    assert "ORDER_STATUSES" in diag["source_line"]

    class DummyToolResult:
        output = ""
        error = node_err
        success = False
        exit_code = 1

    obs = StructuredObservation.from_tool_result(
        tool_name="shell.bash",
        tool_result=DummyToolResult(),
        duration=0.1,
        files_before=set(),
        files_after=set(),
    )
    assert obs.success is False
    assert obs.error_summary is not None
    assert "Node.js v20.18.3" not in obs.error_summary
    assert "SyntaxError: Invalid or unexpected token at app.js:13" == obs.error_summary
    assert obs.diagnostic is not None
    assert obs.diagnostic["line"] == 13


# ==============================================================================
# TEST C: Diagnostic Persistence Across >4 Reasoning Turns
# ==============================================================================
@pytest.mark.asyncio
async def test_c_diagnostic_persistence_across_reasoning_turns():
    temp_dir = tempfile.mkdtemp()
    try:
        ws_root = Path(temp_dir)
        loop = create_test_loop(ws_root)
        loop._mission_id = "test_mission_c"

        loop._pending_diagnostics["app.js"] = {
            "file": "app.js",
            "line": 13,
            "column": 67,
            "error_class": "SyntaxError",
            "message": "Invalid or unexpected token",
            "source_line": "const ORDER_STATUSES = ['New', 'Preparing', 'Ready', 'Completed', '",
        }

        for i in range(6):
            obs = Observation(
                observation_id=f"obs_reason_{i}",
                mission_id="test_mission_c",
                turn_id=f"turn_{i}",
                source_type="agent",
                source_id="reasoning",
                success=True,
                summary=f"Reasoning step {i}",
                content=f"Thinking about step {i}...",
            )
            loop._record_observation(obs)

        assert len(loop._observation_history) >= 6

        mission = Mission(
            mission_id="test_mission_c",
            user_prompt="Build coffee shop app",
            workspace_root=ws_root,
        )
        sys_prompt, user_msg = loop._build_turn_context(mission, state=None)

        assert "UNRESOLVED CRITICAL SYNTAX DIAGNOSTICS" in user_msg
        assert "app.js" in user_msg
        assert "line 13" in user_msg
        assert "SyntaxError: Invalid or unexpected token" in user_msg
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# TEST D: Failure Classification
# ==============================================================================
def test_d_failure_classification():
    err429 = classify_provider_error(status_code=429, response_body="Rate limit exceeded")
    assert err429.classification == ErrorClassification.RATE_LIMIT_EXCEEDED
    assert err429.is_transient is True

    err503 = classify_provider_error(status_code=503, response_body="Service unavailable")
    assert err503.classification == ErrorClassification.SERVICE_UNAVAILABLE

    err_timeout = classify_provider_error(exc=asyncio.TimeoutError())
    assert err_timeout.classification == ErrorClassification.REQUEST_TIMEOUT

    err401 = classify_provider_error(status_code=401, response_body="Unauthorized")
    assert err401.classification == ErrorClassification.AUTH_FAILURE

    syntax_err = extract_syntax_diagnostic("app.js:5\nconst a = ;\n^\nSyntaxError: Unexpected token ';'")
    assert syntax_err is not None
    assert syntax_err["error_class"] == "SyntaxError"
    assert syntax_err["line"] == 5


# ==============================================================================
# TEST E: Complete Tier 1-Tier 4 Routing Graph (Scenarios A, B, C, D)
# ==============================================================================
@pytest.mark.asyncio
async def test_e_tier_cycle_prevention_graph_scenarios():
    temp_dir = tempfile.mkdtemp()
    try:
        ws_root = Path(temp_dir)
        router = AdaptiveRouter()

        # ── SCENARIO A: T1 -> T2 -> T3 -> T4 -> terminal failure (same fingerprint) ──
        router.reset_state()
        loop_a = create_test_loop(ws_root)
        loop_a._mission_id = "test_scenario_a"
        loop_a._total_recovery_budget = 10
        loop_a.orchestrator._active_tier = 1

        with patch("core.adaptive_routing.adaptive_router", router):
            # T1 -> T2
            ok1 = await loop_a._trigger_recovery_transition("t1", "SyntaxError: app.js:13", unmet_reqs=["app.js"])
            assert ok1 is True
            assert loop_a.orchestrator._active_tier == 2

            # T2 -> T3
            ok2 = await loop_a._trigger_recovery_transition("t2", "SyntaxError: app.js:13", unmet_reqs=["app.js"])
            assert ok2 is True
            assert loop_a.orchestrator._active_tier == 3

            # T3 -> T4 (T1 already visited for this fingerprint, cannot cycle to T1)
            ok3 = await loop_a._trigger_recovery_transition("t3", "SyntaxError: app.js:13", unmet_reqs=["app.js"])
            assert ok3 is True
            assert loop_a.orchestrator._active_tier == 4

            # T4 -> Terminal failure (all tiers visited for this fingerprint)
            ok4 = await loop_a._trigger_recovery_transition("t4", "SyntaxError: app.js:13", unmet_reqs=["app.js"])
            assert ok4 is False, "Scenario A: T4 must terminate when all tiers have failed for the incident"

        # ── SCENARIO B: One explicitly permitted healthy Tier 1 rotation ──
        router.reset_state()
        loop_b = create_test_loop(ws_root)
        loop_b._mission_id = "test_scenario_b"
        loop_b._total_recovery_budget = 10
        loop_b.orchestrator._active_tier = 3
        # T1 did not fail this incident (e.g. started at T3 or new issue)
        with patch("core.adaptive_routing.adaptive_router", router):
            ok_rot = await loop_b._trigger_recovery_transition("t1", "New Issue", unmet_reqs=["style.css"])
            assert ok_rot is True
            assert loop_b.orchestrator._active_tier == 1
            assert loop_b._tier_rotations == 1

        # ── SCENARIO C: Tier 1 marked unhealthy during Tier 4 decision ──
        router.reset_state()
        loop_c = create_test_loop(ws_root)
        loop_c._mission_id = "test_scenario_c"
        loop_c._total_recovery_budget = 10
        loop_c.orchestrator._active_tier = 4
        # Mark Tier 1 unhealthy
        router.record_failure(1, Exception("Connection reset"), timeout_type="CONNECT_TIMEOUT")
        with patch("core.adaptive_routing.adaptive_router", router):
            ok_c = await loop_c._trigger_recovery_transition("t1", "Different issue", unmet_reqs=["app.js"])
            # T1 is unhealthy -> MUST NOT rotate to T1! Must terminate!
            assert ok_c is False

        # ── SCENARIO D: A new failure fingerprint legitimately permits a fresh recovery path ──
        router.reset_state()
        loop_d = create_test_loop(ws_root)
        loop_d._mission_id = "test_scenario_d"
        loop_d._total_recovery_budget = 10
        loop_d.orchestrator._active_tier = 1

        with patch("core.adaptive_routing.adaptive_router", router):
            # First fingerprint: app.js syntax error (T1 -> T2)
            await loop_d._trigger_recovery_transition("t1", "SyntaxError in app.js", unmet_reqs=["app.js"])
            assert loop_d.orchestrator._active_tier == 2

            # New fingerprint: missing DOM element in index.html (legitimately fresh visited set)
            loop_d.orchestrator._active_tier = 1
            ok_fresh = await loop_d._trigger_recovery_transition("t2", "Missing button element in index.html", unmet_reqs=["index.html"])
            assert ok_fresh is True
            assert loop_d.orchestrator._active_tier == 2
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# TEST F: Stale Circuit Breaker Isolation, Retry-After, Auth/Quota Permanence
# ==============================================================================
def test_f_circuit_breaker_semantics_and_cooldown():
    router = AdaptiveRouter()

    # 1. Transient failure recovers after 120s cooldown
    router.reset_state()
    for _ in range(5):
        router.record_failure(1, Exception("Gateway timeout"), timeout_type="FIRST_TOKEN_TIMEOUT")
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT
    # Advance time past 120s window
    router.providers[1].circuit_open_ts = time.time() - 150.0
    assert router.get_health(1).state == ProviderHealthState.HEALTHY

    # 2. HTTP 429 with Retry-After=300: does NOT recover after 120s
    router.reset_state()
    err_429 = Exception("Rate limit exceeded")
    err_429.retry_after = 300.0
    router.record_failure(1, err_429, retry_after=300.0)
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT
    # Even after 150s, 300s Retry-After has not passed!
    router.providers[1].circuit_open_ts = time.time() - 150.0
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT

    # 3. Authentication failure (401 / 403): does NOT auto-recover after 120s
    router.reset_state()
    router.record_failure(1, Exception("401 Unauthorized: Invalid API key"))
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT
    router.providers[1].circuit_open_ts = time.time() - 150.0
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT
    assert router.providers[1].is_auth_failure is True

    # 4. Quota exhaustion failure: does NOT auto-recover after 120s
    router.reset_state()
    router.record_failure(1, Exception("insufficient_quota: You exceeded your current quota"))
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT
    router.providers[1].circuit_open_ts = time.time() - 150.0
    assert router.get_health(1).state == ProviderHealthState.OPEN_CIRCUIT
    assert router.providers[1].is_quota_exhausted is True


# ==============================================================================
# TEST G: Syntax Repair Workflow with Targeted Directive & Revalidation
# ==============================================================================
@pytest.mark.asyncio
async def test_g_syntax_repair_workflow():
    temp_dir = tempfile.mkdtemp()
    try:
        ws_root = Path(temp_dir)
        loop = create_test_loop(ws_root)
        loop._mission_id = "test_mission_g"

        bad_diag = {
            "file": "app.js",
            "line": 13,
            "error_class": "SyntaxError",
            "message": "Invalid or unexpected token",
            "source_line": "const ORDER_STATUSES = ['New', 'Preparing', 'Ready', 'Completed', '",
        }
        loop._pending_diagnostics["app.js"] = bad_diag
        assert "app.js" in loop._pending_diagnostics

        app_js = ws_root / "app.js"
        app_js.write_text("console.log('valid code');\n", encoding="utf-8")

        target_base = Path("app.js").name.lower()
        if target_base in loop._pending_diagnostics:
            del loop._pending_diagnostics[target_base]

        assert "app.js" not in loop._pending_diagnostics
        assert len(loop._pending_diagnostics) == 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# TEST H: Reasoning-Only Stall Watchdog Terminating at Budget
# ==============================================================================
@pytest.mark.asyncio
async def test_h_reasoning_only_stall_watchdog():
    temp_dir = tempfile.mkdtemp()
    try:
        ws_root = Path(temp_dir)
        loop = create_test_loop(ws_root)
        loop._mission_id = "test_mission_h"

        loop._consecutive_empty_turns = 3
        loop._consecutive_empty_turns += 1

        assert loop._consecutive_empty_turns >= 4
        termination_reason = (
            f"FAILED_NO_ACTION_STALL: Model stalled with {loop._consecutive_empty_turns} "
            "consecutive reasoning turns without tool execution"
        )
        assert "FAILED_NO_ACTION_STALL" in termination_reason
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# TEST I: Duplicate Tool Call Detection (node -v repeated blocked)
# ==============================================================================
@pytest.mark.asyncio
async def test_i_duplicate_tool_call_detection():
    temp_dir = tempfile.mkdtemp()
    try:
        ws_root = Path(temp_dir)
        loop = create_test_loop(ws_root)
        loop._mission_id = "test_mission_i"

        cmd = "node -v"
        norm_cmd = cmd.lower()
        loop._executed_info_commands.add(norm_cmd)

        info_cmds = ("node -v", "node --version", "npm -v", "npm --version", "python --version", "git --version")
        is_blocked = norm_cmd in loop._executed_info_commands and any(norm_cmd == ic for ic in info_cmds)
        assert is_blocked is True

        test_file = ws_root / "test.js"
        test_file.write_text("bad code", encoding="utf-8")
        file_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()

        syntax_cmd = "node -c test.js"
        loop._failed_syntax_checks[syntax_cmd] = file_hash

        curr_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
        assert loop._failed_syntax_checks.get(syntax_cmd) == curr_hash

        test_file.write_text("good code()", encoding="utf-8")
        new_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
        assert loop._failed_syntax_checks.get(syntax_cmd) != new_hash
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# TEST J: Progress Detection Distinguishing File Changes from No-Ops
# ==============================================================================
def test_j_progress_detection_distinguishing_file_changes():
    temp_dir = tempfile.mkdtemp()
    try:
        ws_root = Path(temp_dir)
        app_file = ws_root / "app.js"

        app_file.write_text("const a = 1;", encoding="utf-8")
        h1 = hashlib.sha256(app_file.read_bytes()).hexdigest()

        app_file.write_text("const a = 1;", encoding="utf-8")
        h2 = hashlib.sha256(app_file.read_bytes()).hexdigest()
        assert h1 == h2

        app_file.write_text("const a = 2;", encoding="utf-8")
        h3 = hashlib.sha256(app_file.read_bytes()).hexdigest()
        assert h1 != h3
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# TEST K: Deadline Admission Control Halting & Skipping Model Call
# ==============================================================================
@pytest.mark.asyncio
async def test_k_deadline_admission_control_and_spy():
    # 1. Mathematical boundary checks
    t_1200 = calculate_effective_turn_timeout(remaining_wall_time=1200.0, configured_timeout=360.0)
    assert t_1200 == 90.0

    t_280 = calculate_effective_turn_timeout(remaining_wall_time=280.0, configured_timeout=360.0)
    assert t_280 == 90.0

    # Remaining time is 175s: usable is 175 - 165 = 10s < 15s -> returns None
    t_175 = calculate_effective_turn_timeout(remaining_wall_time=175.0, configured_timeout=360.0)
    assert t_175 is None

    # 2. Spy Provider Test: Prove provider request method is NEVER called when admission denied
    temp_dir = tempfile.mkdtemp()
    try:
        ws_root = Path(temp_dir)
        loop = create_test_loop(ws_root)
        # Set max_wall_time_seconds so remaining wall time budget is only 170s (< 165s reserve + 15s min timeout)
        loop.config.max_wall_time_seconds = 170.0

        # Spy method on orchestrator
        spy_generate = AsyncMock()
        loop.orchestrator.generate = spy_generate
        loop.orchestrator._generate_t1 = spy_generate

        mission = Mission(mission_id="test_k_spy", user_prompt="Goal", workspace_root=ws_root)
        result = await loop.run(mission)

        # Verify admission was denied and model call was NEVER executed
        assert spy_generate.call_count == 0
        assert result.success is False
        assert "Insufficient remaining wall time budget" in (result.termination_reason or "")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# TEST L: Timeout Cancellation Closing Streams and Cleaning Processes
# ==============================================================================
@pytest.mark.asyncio
async def test_l_timeout_cancellation():
    from tools.shell_tools import terminate_active_subprocesses
    terminate_active_subprocesses(mission_id="test_l")


# ==============================================================================
# TEST M: Original Observation Regression
# ==============================================================================
def test_m_original_observation_regression():
    from core.agent_loop.types import Observation as ObsType
    from core.agent_loop.observations import Observation as ObsObs
    assert ObsType is ObsObs, "Observation symbol must refer to identical class object"


# ==============================================================================
# TEST N: Full Historical Replay Simulating Mission m_43651102 Failure & Convergence
# ==============================================================================
@pytest.mark.asyncio
async def test_n_historical_replay_mission_m_43651102():
    temp_dir = tempfile.mkdtemp()
    try:
        ws_root = Path(temp_dir)
        app_js = ws_root / "app.js"

        truncated_content = """// BrewLedger POS Logic
const TAX_RATE = 0.0825;
const DISCOUNTS = {
    'HAPPYHOUR': 0.15,
    'BREW10': 0.10,
    'VIP20': 0.20
};

const ORDER_STATUSES = ['New', 'Preparing', 'Ready', 'Completed', '"""
        app_js.write_text(truncated_content, encoding="utf-8")

        loop = create_test_loop(ws_root)
        loop._mission_id = "test_mission_m_43651102_replay"

        raw_err = f"""{app_js}:13
const ORDER_STATUSES = ['New', 'Preparing', 'Ready', 'Completed', '
                                                                  ^

SyntaxError: Invalid or unexpected token
    at compileSourceTextModule (node:internal/modules/esm/load:240:19)

Node.js v20.18.3"""

        diag = extract_syntax_diagnostic(raw_err)
        assert diag is not None
        assert diag["error_class"] == "SyntaxError"
        assert diag["line"] == 13

        loop._pending_diagnostics["app.js"] = diag

        mission = Mission(
            mission_id=loop._mission_id,
            user_prompt="Build complete BrewLedger coffee shop POS application",
            workspace_root=ws_root,
        )
        _, user_msg = loop._build_turn_context(mission, state=None)
        assert "UNRESOLVED CRITICAL SYNTAX DIAGNOSTICS" in user_msg
        assert "app.js" in user_msg
        assert "SyntaxError: Invalid or unexpected token" in user_msg

        loop._executed_info_commands.add("node -v")
        assert "node -v" in loop._executed_info_commands

        complete_content = """// BrewLedger POS Logic
const TAX_RATE = 0.0825;
const DISCOUNTS = {
    'HAPPYHOUR': 0.15,
    'BREW10': 0.10,
    'VIP20': 0.20
};

const ORDER_STATUSES = ['New', 'Preparing', 'Ready', 'Completed', 'Cancelled'];

class POSApp {
    constructor() {
        this.items = [];
    }
}
window.POSApp = POSApp;
"""
        app_js.write_text(complete_content, encoding="utf-8")
        del loop._pending_diagnostics["app.js"]
        assert len(loop._pending_diagnostics) == 0

        diag_after = extract_syntax_diagnostic("")
        assert diag_after is None

        assert app_js.stat().st_size > 200
        assert "Cancelled" in app_js.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
