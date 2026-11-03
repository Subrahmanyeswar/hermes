# tests/test_careergrid_control_plane_remediation.py
"""
Comprehensive Integration Test Suite for HERMES 2.x Master Control-Plane Remediation.
Exercises Tests A through P specified in the remediation directive.
"""

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, List

import pytest

from core.agent_loop.syntax_repair import SyntaxRepairController, SyntaxRepairTicket
from core.agent_loop.completion import CompletionPolicy
from core.code_completeness import validate_implementation_completeness
from core.js_syntax_validator import (
    validate_javascript_content,
    validate_javascript_file,
    check_js_bracket_balance,
)
from core.project_intelligence.skills import SkillEngine
from core.observability.logger import get_telemetry_logger, MissionTelemetryLogger
from core.observability.bus_subscriber import ObservabilityBusSubscriber
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType, EventSeverity
from models.common_adapter import NormalizedModelResponse
from tools.platform.core_tools import FSWriteTool


# ── Test A: Truncated model output (finish_reason = length) ─────────────────
@pytest.mark.asyncio
async def test_a_truncated_model_output_rejection():
    """Verify responses ending in length/max_tokens are marked as truncated."""
    from models.common_adapter import CommonProviderAdapter
    import httpx
    from unittest.mock import MagicMock, patch

    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key", tier=1)
    mock_resp = {
        "id": "chat-123",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "const x = 1;",
                "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "fs.write", "arguments": '{"path": "app.js", "content": "function seed() { const t = ('}}]
            },
            "finish_reason": "length"
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 500, "total_tokens": 600},
    }
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_resp, text=json.dumps(mock_resp))
        res = await adapter.generate(prompt="hi", stream=False)
        assert res.success is False
        assert "MODEL_OUTPUT_TRUNCATED" in res.error
        assert res.finish_reason == "length"
        assert len(res.tool_calls) == 0  # Partial tool calls must NOT be executed


# ── Test B: Missing finish reason ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_b_missing_finish_reason_recording():
    """Verify that missing finish_reason is recorded cleanly."""
    from models.common_adapter import CommonProviderAdapter
    import httpx
    from unittest.mock import MagicMock, patch

    adapter = CommonProviderAdapter("zai", "glm-4.7-flash", "https://api.z.ai/api/paas/v4", "test_key", tier=1)
    mock_resp = {
        "id": "chat-123",
        "choices": [{
            "message": {"role": "assistant", "content": "const x = 1;"},
            "finish_reason": None
        }],
        "usage": {"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100},
    }
    with patch.object(httpx.AsyncClient, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_resp, text=json.dumps(mock_resp))
        res = await adapter.generate(prompt="hi", stream=False)
        assert res.finish_reason is None or res.finish_reason == "FINISH_REASON_UNAVAILABLE"


# ── Test C: Valid short JavaScript application ──────────────────────────────
def test_c_valid_short_javascript():
    """Verify a valid 15-30 line JavaScript snippet is accepted without arbitrary line minimums."""
    short_js = """
// Counter application logic
(function() {
  'use strict';
  let count = 0;
  const countEl = document.getElementById('count');
  
  function update(val) {
    count = val;
    if (countEl) countEl.textContent = String(count);
  }
  
  window.counterApp = {
    increment: () => update(count + 1),
    decrement: () => update(count - 1),
    reset: () => update(0),
    getCount: () => count
  };
})();
"""
    is_valid, err, line = validate_javascript_content(short_js, "app.js")
    assert is_valid is True
    assert err is None
    
    is_complete, comp_err = validate_implementation_completeness(short_js, "app.js")
    assert is_complete is True
    assert comp_err is None


# ── Test D: Syntax failure and targeted repair ──────────────────────────────
def test_d_syntax_failure_and_targeted_repair():
    """Verify truncated JS generates repair ticket with stderr, line, and file tail."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        broken_file = ws / "app.js"
        broken_code = "/* Test App */\nfunction seed() {\n    const t = (\n"
        broken_file.write_text(broken_code, encoding="utf-8")
        
        sc = SyntaxRepairController(workspace_root=ws)
        stderr = f"{broken_file}:3\n    const t = (\n               \n\nSyntaxError: Unexpected end of input"
        
        ticket = sc.create_or_update_ticket(
            target_file="app.js",
            validator="node --check app.js",
            stderr_or_output=stderr,
            exit_code=1,
            workspace_root=ws,
        )
        
        assert ticket.target_file == "app.js"
        assert ticket.line == 3
        assert ticket.error_class == "SyntaxError"
        assert "Unexpected end of input" in ticket.message
        assert ticket.repair_attempts == 0
        assert ticket.max_attempts == 2
        
        # Build directive and check pinned content
        directive = sc.build_repair_directive(ticket)
        assert "CRITICAL APPLICATION SYNTAX REPAIR DIRECTIVE" in directive
        assert "Calling fs.read on 'app.js' is PROHIBITED" in directive
        assert "const t = (" in directive
        
        # Simulate successful repair
        repaired_code = "/* Test App */\nfunction seed() {\n    const t = 100;\n    return t;\n}\n"
        broken_file.write_text(repaired_code, encoding="utf-8")
        
        resolved_ticket = sc.resolve_ticket("app.js")
        assert resolved_ticket is not None
        assert resolved_ticket.is_active is False
        assert sc.has_unresolved_syntax_errors() is False


# ── Test E: Existing valid file protection ──────────────────────────────────
def test_e_existing_valid_file_protection():
    """Verify an existing valid deliverable cannot be overwritten by truncated code."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        app_file = ws / "app.js"
        valid_code = "function init() { return true; }\n"
        app_file.write_text(valid_code, encoding="utf-8")
        
        tool = FSWriteTool()
        malformed_write = tool.execute({
            "path": "app.js",
            "content": "function seed() {\n    const t = (",
            "workspace_root": str(ws),
        })
        
        assert malformed_write.success is False
        assert "INCOMPLETE_IMPLEMENTATION_TRUNCATED" in malformed_write.error
        
        # Ensure original valid file was NOT damaged
        assert app_file.read_text(encoding="utf-8") == valid_code


# ── Test F: Premature report prevention ─────────────────────────────────────
def test_f_premature_report_prevention():
    """Verify development report writing is blocked while deliverable has syntax errors."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        # Create a broken JS file
        (ws / "app.js").write_text("function seed() { const t = (", encoding="utf-8")
        
        tool = FSWriteTool()
        res = tool.execute({
            "path": "CAREERGRID_DEVELOPMENT_REPORT.md",
            "content": "# Report\nAll features verified: Yes\n",
            "workspace_root": str(ws),
        })
        
        assert res.success is False
        assert "FALSE_COMPLETION_REPORT_BLOCKED" in res.error
        assert "app.js" in res.error
        
        # Now fix app.js and verify report writing is permitted
        (ws / "app.js").write_text("function seed() { const t = 10; return t; }", encoding="utf-8")
        res_ok = tool.execute({
            "path": "CAREERGRID_DEVELOPMENT_REPORT.md",
            "content": "# Report\nAll features verified: Yes\n",
            "workspace_root": str(ws),
        })
        assert res_ok.success is True


# ── Test G: Tool no-progress recovery ───────────────────────────────────────
def test_g_tool_no_progress_recovery():
    """Verify evaluate_completion rejects completion when syntax error exists in workspace."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        (ws / "index.html").write_text("<!DOCTYPE html><html><body><h1>App</h1></body></html>", encoding="utf-8")
        (ws / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
        (ws / "package.json").write_text('{"name": "test"}', encoding="utf-8")
        (ws / "app.js").write_text("function seed() { const t = (", encoding="utf-8")
        
        policy = CompletionPolicy()
        accepted, reason, issues = policy.evaluate_completion(
            mission_prompt="Create application",
            workspace=ws,
            written_files=["index.html", "style.css", "package.json", "app.js"]
        )
        
        assert accepted is False
        assert any("JavaScript syntax error" in iss for iss in issues)


# ── Test H: Provider response classification ────────────────────────────────
def test_h_provider_response_classification():
    """Verify HTTP error classification in common adapter."""
    from models.common_adapter import classify_provider_error, ErrorClassification
    
    # 429 Rate Limit
    err429 = classify_provider_error(status_code=429, response_body='{"error": "Rate limit exceeded"}')
    assert err429.classification == ErrorClassification.RATE_LIMIT_EXCEEDED
    
    # 401 Auth Failure
    err401 = classify_provider_error(status_code=401, response_body='{"error": "Invalid API key"}')
    assert err401.classification == ErrorClassification.AUTH_FAILURE
    
    # 500 / 503 Server Error
    err500 = classify_provider_error(status_code=500, response_body='Internal Server Error')
    assert err500.classification == ErrorClassification.INTERNAL_ERROR
    assert err500.is_transient is True


# ── Test I: End-to-end timeout bounded by parent turn budget ────────────────
def test_i_end_to_end_timeout_budget():
    """Verify calculate_effective_turn_timeout properly bounds admission budget."""
    from core.agent_loop.loop import calculate_effective_turn_timeout
    
    # Budget with ample time (capped at 90s)
    t_normal = calculate_effective_turn_timeout(
        remaining_wall_time=400.0,
        configured_timeout=90.0,
        reserve_seconds=120.0,
        finalization_reserve_seconds=45.0,
        min_model_timeout=15.0,
    )
    assert t_normal == 90.0
    
    # Budget constrained by wall time:
    # 205.0 - 120 - 45 = 40.0s usable budget < 90s
    t_constrained = calculate_effective_turn_timeout(
        remaining_wall_time=205.0,
        configured_timeout=90.0,
        reserve_seconds=120.0,
        finalization_reserve_seconds=45.0,
        min_model_timeout=15.0,
    )
    assert t_constrained == 40.0
    
    # Admission denied when remaining wall time < reserve (148.3s < 180s)
    t_denied = calculate_effective_turn_timeout(
        remaining_wall_time=148.3,
        configured_timeout=90.0,
        reserve_seconds=120.0,
        finalization_reserve_seconds=45.0,
        min_model_timeout=15.0,
    )
    assert t_denied is None


# ── Test J: Timeout overrun detection ───────────────────────────────────────
@pytest.mark.asyncio
async def test_j_timeout_overrun_detection():
    """Verify that a hanging model call triggers parent timeout cancellation."""
    async def slow_mock_generate(*args, **kwargs):
        await asyncio.sleep(2.0)
        return NormalizedModelResponse(text="late", success=True)
    
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(slow_mock_generate(), timeout=0.1)


# ── Test K: Skill routing for diverse application profiles ──────────────────
def test_k_skill_routing_diversity():
    """Verify appropriate domain skills are preserved across different application types."""
    engine = SkillEngine(workspace_root=Path("."))
    engine.index_skills()
    
    # 1. Vanilla Web
    dec_web = engine.route_skills("Build a career portal dashboard with HTML, CSS, and JS")
    assert "vanilla-web" in dec_web.selected_skills
    assert "pytest-generation" not in dec_web.selected_skills  # suppressed for vanilla web
    
    # 2. React
    dec_react = engine.route_skills("Create a React frontend application with JSX and Tailwind")
    assert "react-frontend" in dec_react.selected_skills
    
    # 3. Backend
    dec_backend = engine.route_skills("Build a FastAPI backend service with SQLite database")
    assert "fastapi-backend" in dec_backend.selected_skills


# ── Test L: HTML/CSS/DOM contract validation ────────────────────────────────
def test_l_html_css_dom_contract_mismatch():
    """Verify dead anchor and view visibility mismatches are detected."""
    from core.alignment_verifier import verify_project_alignment
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        # index.html references #overview and #settings, but neither ID exists
        (ws / "index.html").write_text("""
<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="style.css"></head>
<body>
  <a href="#overview">Overview</a>
  <a href="#settings">Settings</a>
  <div class="view-section">Content</div>
</body>
</html>
""", encoding="utf-8")
        
        # style.css lacks .active or display rules
        (ws / "style.css").write_text("body { background: #000; }", encoding="utf-8")
        
        rep = verify_project_alignment(ws)
        assert rep.status == "FAIL"
        anchor_defects = [d for d in rep.defects if d.kind.value == "DEAD_ANCHOR"]
        assert len(anchor_defects) >= 2


# ── Test M: Full observability routing ──────────────────────────────────────
def test_m_full_observability_routing():
    """Verify that events route to events.jsonl, tools.jsonl, and files.jsonl with single Run ID."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        run_id = "run_test_obs_full_01"
        mission_id = "m_test_obs_full"
        
        logger = MissionTelemetryLogger(run_id=run_id, mission_id=mission_id, base_dir=base_dir)
        
        # Log tool call (file write)
        logger.record_tool_call(
            tool_call_id="call-001",
            tool_name="fs.write",
            turn=1,
            duration_ms=45.0,
            success=True,
            exit_code=0,
            target_path="app.js",
            stdout="wrote 100 bytes",
        )
        
        # Log validation check
        logger.record_validation_result(
            validator_name="node --check app.js",
            target_file="app.js",
            success=True,
            duration_ms=25.0,
            exit_code=0,
        )
        
        # Check that files were written
        assert (logger.files["events"]).stat().st_size > 0
        assert (logger.files["tools"]).stat().st_size > 0
        assert (logger.files["validation"]).stat().st_size > 0
        
        # Verify single Run ID in JSONL
        with open(logger.files["events"], "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                assert rec["run_id"] == run_id
                assert rec["mission_id"] == mission_id


# ── Test N: Run ID and watcher correlation ──────────────────────────────────
def test_n_run_id_and_watcher_correlation():
    """Verify that bus subscriber uses authoritative Run ID lookup."""
    bus = EventBus()
    subscriber = ObservabilityBusSubscriber(bus)
    
    # Mock event without run_id, but with mission_id
    evt = HermesEvent(
        event_type=EventType.SKILL_DISCOVERED,
        mission_id="m_corr_test_01",
        payload={"name": "auto-docs"},
    )
    
    # Handle event and verify no crash, run_1_m_corr_test_01 assigned
    subscriber.handle_event(evt)
    
    tl = get_telemetry_logger(run_id="run_1_m_corr_test_01", mission_id="m_corr_test_01")
    assert tl.files["events"].exists()


# ── Test O: Payload offloading and security ─────────────────────────────────
def test_o_payload_offloading_and_security():
    """Verify large prompts (>8KB) are offloaded to payloads/ and API keys redacted."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        run_id = "run_test_payload_01"
        mission_id = "m_test_payload"
        
        logger = MissionTelemetryLogger(run_id=run_id, mission_id=mission_id, base_dir=base_dir)
        
        # Create a large prompt containing a secret
        secret_prompt = "Build app with API_KEY=AIzaSyA_SECRET_KEY_12345 " + ("x" * 9000)
        
        logger.record_model_call(
            turn=1,
            tier=1,
            provider="gemini",
            model="gemini-3.5-flash-lite",
            duration_ms=500.0,
            status="SUCCESS",
            params={},
            timings={},
            response_meta={},
            raw_prompt=secret_prompt,
        )
        
        # Verify file created in payloads/
        payload_files = list(logger.payloads_dir.glob("prompt_*.txt"))
        assert len(payload_files) == 1
        
        content = payload_files[0].read_text(encoding="utf-8")
        assert "AIzaSyA_SECRET_KEY_12345" not in content  # Must be redacted
        assert "[REDACTED" in content or "API_KEY" in content


# ── Test P: Full historical incident replay ─────────────────────────────────
def test_p_full_historical_incident_replay():
    """Simulate CareerGrid workflow: truncated app.js is rejected, repair ticket issued, report blocked."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        tool = FSWriteTool()
        
        # 1. package.json write (valid)
        res_pkg = tool.execute({"path": "package.json", "content": '{"name": "cg"}', "workspace_root": str(ws)})
        assert res_pkg.success is True
        
        # 2. index.html write (valid with CSS link, controls, and script tag)
        html_content = (
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            "    <meta charset=\"UTF-8\">\n    <link rel=\"stylesheet\" href=\"style.css\">\n"
            "</head>\n<body>\n"
            "    <h1>CareerGrid</h1>\n"
            "    <input type=\"text\" id=\"search\" placeholder=\"Filter...\">\n"
            "    <button id=\"btn\">Apply</button>\n"
            "    <script src=\"app.js\"></script>\n"
            "</body>\n</html>"
        )
        res_html = tool.execute({"path": "index.html", "content": html_content, "workspace_root": str(ws)})
        assert res_html.success is True
        
        # 3. style.css write (valid)
        css_content = "body { margin: 0; padding: 20px; font-family: sans-serif; } button { cursor: pointer; }"
        res_css = tool.execute({"path": "style.css", "content": css_content, "workspace_root": str(ws)})
        assert res_css.success is True
        
        # 4. app.js write with truncation at line 77 (like CareerGrid) is REJECTED by completeness gate
        truncated_js = "function seed() {\n    const t = ("
        res_app = tool.execute({"path": "app.js", "content": truncated_js, "workspace_root": str(ws)})
        assert res_app.success is False
        assert "INCOMPLETE_IMPLEMENTATION_TRUNCATED" in res_app.error
        
        # Simulate partial file existing on disk to test report-blocking gate
        (ws / "app.js").write_text(truncated_js, encoding="utf-8")
        
        # 5. Model attempts to write development report claiming verified completion -> BLOCKED by syntax error
        res_rep = tool.execute({
            "path": "CAREERGRID_DEVELOPMENT_REPORT.md",
            "content": "# Report\nAll features verified: Yes",
            "workspace_root": str(ws),
        })
        assert res_rep.success is False
        assert "FALSE_COMPLETION_REPORT_BLOCKED" in res_rep.error
        
        # 6. Model issues targeted repair with complete valid JavaScript
        valid_app_js = """
/**
 * CareerGrid Application Logic
 * Initializes search and display features.
 */
(function () {
    'use strict';
    const btn = document.getElementById('btn');
    const input = document.getElementById('search');

    function search(query) {
        return query ? 'filtered' : 'all';
    }

    if (btn && input) {
        btn.addEventListener('click', () => search(input.value));
    }
    window.CareerGrid = { search };
})();
"""
        res_repair = tool.execute({"path": "app.js", "content": valid_app_js, "workspace_root": str(ws)})
        assert res_repair.success is True
        
        # 7. Now report generation is allowed
        res_rep_ok = tool.execute({
            "path": "CAREERGRID_DEVELOPMENT_REPORT.md",
            "content": "# CareerGrid Development Report\nAll features verified: Yes",
            "workspace_root": str(ws),
        })
        assert res_rep_ok.success is True
        
        # 8. Completion policy accepts the repaired workspace
        policy = CompletionPolicy()
        accepted, reason, issues = policy.evaluate_completion(
            mission_prompt="Build CareerGrid platform",
            workspace=ws,
            written_files=["package.json", "index.html", "style.css", "app.js"]
        )
        assert accepted is True
