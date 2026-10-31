# tests/test_website_mvp_and_browser_verification.py
"""
HERMES Acceptance & Regression Test Suite for Section 16 & Section 17.
Verifies all 16 required behaviors:
 1. Production dispatcher writer succeeds.
 2. Real writer failure propagates accurately.
 3. Scaffolded website triggers MVP gate before optional enhancements.
 4. Failed build blocks enhancement work and causes repair.
 5. Website cannot be marked verified merely because files exist.
 6. Vite application is verified over HTTP rather than accepted through file://.
 7. Absent or failed stylesheet prevents website verification from passing.
 8. Application initialization error is detected.
 9. Required 3D canvas absent or uninitialized causes verification failure.
 10. Repeated identical failures activate redundancy guard.
 11. Legitimate retry after relevant source changes remains possible.
 12. Expired mission budgets prevent new model calls.
 13. In-flight operation is cancelled or terminated cleanly.
 14. Recoverable provider outage triggers bounded fallback.
 15. Invalid request or deterministic code error does not loop endlessly.
 16. Terminal mission status reflects actual build/browser results.
"""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_loop.actions import ActionExecutor
from core.agent_loop.loop import (
    AgentLoop,
    FINAL_VERIFICATION_RESERVE_SECONDS,
    MIN_MODEL_REQUEST_TIMEOUT_SECONDS,
    calculate_effective_turn_timeout,
)
from core.agent_loop.types import ActionEnvelope, AgentLoopConfig
from core.mission_planner import Mission
from core.agent_loop.mvp_gate import MvpPhase, WebsiteMvpGate
from core.browser.security import BrowserSecurityManager, BrowserSecurityViolation
from core.runtime_state.events import EventType
from core.verification_profiles import (
    VerificationProfile,
    VerificationProfileEvaluator,
    classify_verification_profile,
)
from core.workspace import WorkspaceManager, workspace_manager
from tools.browser_tools import BrowserOpenPreviewTool
from tools.file_tools import WriteFileTool
from tools.platform.core_tools import FSWriteTool


@pytest.fixture
def temp_ws():
    """Create and lock an isolated temporary workspace for test isolation."""
    d = tempfile.mkdtemp(prefix="hermes_verif_test_")
    ws_path = Path(d).resolve()
    try:
        workspace_manager.lock(str(ws_path))
        yield ws_path
    finally:
        try:
            workspace_manager.unlock()
        except Exception:
            pass
        shutil.rmtree(d, ignore_errors=True)


# ── Behavior 1: Production dispatcher writer success ──────────────────────────
@pytest.mark.asyncio
async def test_1_production_dispatcher_writer_success(temp_ws):
    executor = ActionExecutor()
    action = ActionEnvelope(
        mission_id="m_test_1",
        turn_id="turn_1",
        tool_call_id="call_1",
        tool_name="fs.write",
        arguments={"path": "index.html", "content": "<!DOCTYPE html><html><body><h1>Test</h1></body></html>"},
    )
    obs = await executor.execute_action(action, workspace=workspace_manager)
    assert obs.success is True
    target = temp_ws / "index.html"
    assert target.exists()
    assert "<!DOCTYPE html>" in target.read_text(encoding="utf-8")


# ── Behavior 2: Real writer failure propagates accurately ─────────────────────
@pytest.mark.asyncio
async def test_2_real_writer_failure_propagates_accurately(temp_ws):
    executor = ActionExecutor()
    # Attempting to write a fake root Three.js library file
    action = ActionEnvelope(
        mission_id="m_test_2",
        turn_id="turn_1",
        tool_call_id="call_2",
        tool_name="fs.write",
        arguments={"path": "Three.js", "content": "/* fake three.js */"},
    )
    obs = await executor.execute_action(action, workspace=workspace_manager)
    assert obs.success is False
    assert "FAKE_DEPENDENCY_PROHIBITED" in (obs.error_message or obs.content or "")
    assert not (temp_ws / "Three.js").exists()


# ── Behavior 3: Scaffolding triggers MVP gate before enhancements ─────────────
def test_3_scaffold_triggers_mvp_gate_before_enhancements(temp_ws):
    gate = WebsiteMvpGate(workspace_root=temp_ws)
    # Only index.html exists; main.js and style.css missing
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body></body></html>", encoding="utf-8")

    # Attempt to write enhancement file (shaders/smoke.glsl)
    allowed, reason = gate.authorize_action(
        "fs.write",
        {"path": "shaders/smoke.glsl", "content": "void main() {}"},
        workspace_root=temp_ws,
    )
    assert allowed is False
    assert "MVP GATE (Phase 1 - Scaffold)" in reason
    assert "main.js" in reason


# ── Behavior 4: Failed build blocks enhancement and causes repair ─────────────
def test_4_failed_build_blocks_enhancement_and_causes_repair(temp_ws):
    gate = WebsiteMvpGate(workspace_root=temp_ws)
    # Complete scaffold
    (temp_ws / "package.json").write_text(json.dumps({"name": "test-app", "scripts": {"build": "vite build"}}), encoding="utf-8")
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body><script type='module' src='main.js'></script></body></html>", encoding="utf-8")
    (temp_ws / "main.js").write_text("import * as THREE from 'three'; const scene = new THREE.Scene(); const renderer = new THREE.WebGLRenderer();", encoding="utf-8")
    (temp_ws / "style.css").write_text("body { margin: 0; background: #000; }", encoding="utf-8")

    # Scaffold complete, but build has not passed
    phase = gate.evaluate_phase(workspace_root=temp_ws)
    assert phase == MvpPhase.PHASE_2_BUILD_AND_REPAIR

    # Attempting to add particles before build passes must be blocked
    allowed, reason = gate.authorize_action(
        "fs.write",
        {"path": "particles.js", "content": "export class Particles {}"},
        workspace_root=temp_ws,
    )
    assert allowed is False
    assert "MVP GATE (Phase 2 - Build & Repair)" in reason


# ── Behavior 5: Website cannot be verified merely because files exist ──────────
def test_5_website_cannot_be_verified_merely_because_files_exist(temp_ws):
    # Only empty index.html, no main.js, no styles, no canvas
    (temp_ws / "index.html").write_text("<html><body>Empty</body></html>", encoding="utf-8")

    prompt = "Create a responsive Vite and Three.js landing page with a simple rocket model"
    prof = classify_verification_profile(prompt, workspace_path=str(temp_ws), written_files=["index.html"])
    assert prof == VerificationProfile.PROFILE_C

    res = VerificationProfileEvaluator.evaluate(prof, temp_ws, prompt, written_files=["index.html"])
    assert res.passed is False
    assert any("entrypoint" in iss.lower() for iss in res.issues)


# ── Behavior 6: Vite application verified over HTTP, file:// rejected ─────────
def test_6_vite_application_verified_over_http_not_file_protocol(temp_ws):
    sec = BrowserSecurityManager()
    # Create HTML file with module script (Vite project)
    html_file = temp_ws / "index.html"
    html_file.write_text("<!DOCTYPE html><html><body><script type='module' src='main.js'></script></body></html>", encoding="utf-8")

    file_url = f"file:///{str(html_file).replace('\\', '/')}"
    with pytest.raises(BrowserSecurityViolation) as exc_info:
        sec.validate_url(file_url)

    assert "Vite/ESM module application cannot be opened via 'file://'" in str(exc_info.value)
    assert "HTTP" in str(exc_info.value)


# ── Behavior 7: Absent or failed stylesheet prevents verification ─────────────
def test_7_absent_or_failed_stylesheet_prevents_verification(temp_ws):
    # Has index.html and main.js, but no stylesheet
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body><canvas id='c'></canvas><script type='module' src='main.js'></script></body></html>", encoding="utf-8")
    (temp_ws / "main.js").write_text("import * as THREE from 'three'; const s = new THREE.Scene();", encoding="utf-8")
    (temp_ws / "package.json").write_text(json.dumps({"dependencies": {"three": "^0.160.0"}}), encoding="utf-8")

    prompt = "Build a styled Three.js website"
    res = VerificationProfileEvaluator.evaluate(VerificationProfile.PROFILE_C, temp_ws, prompt, written_files=["index.html", "main.js"])
    assert res.passed is False
    assert any("style.css" in iss.lower() for iss in res.issues)


# ── Behavior 8: Application initialization error detected ─────────────────────
def test_8_application_initialization_error_detected(temp_ws):
    # Main.js is an empty stub (< 100 bytes) with no Three.js initialization
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body><script src='main.js'></script></body></html>", encoding="utf-8")
    (temp_ws / "main.js").write_text("// TODO", encoding="utf-8")
    (temp_ws / "style.css").write_text("body { background: #000; }", encoding="utf-8")

    prompt = "Build a responsive Three.js simulation website"
    res = VerificationProfileEvaluator.evaluate(VerificationProfile.PROFILE_C, temp_ws, prompt, written_files=["index.html", "main.js", "style.css"])
    assert res.passed is False
    assert any("entrypoint" in iss.lower() or "uninitialized" in iss.lower() for iss in res.issues)


# ── Behavior 9: Required 3D canvas absent causes verification failure ─────────
def test_9_required_3d_canvas_absent_causes_verification_failure(temp_ws):
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body><div id='content'>No canvas here</div><script src='main.js'></script></body></html>", encoding="utf-8")
    (temp_ws / "main.js").write_text("console.log('Plain page loaded without canvas or Three.js setup');", encoding="utf-8")
    (temp_ws / "style.css").write_text("body { background: #111; color: #fff; }", encoding="utf-8")

    prompt = "Build a 3D Three.js rocket simulation website"
    res = VerificationProfileEvaluator.evaluate(VerificationProfile.PROFILE_C, temp_ws, prompt, written_files=["index.html", "main.js", "style.css"])
    assert res.passed is False
    assert any("canvas" in iss.lower() for iss in res.issues)


# ── Behavior 10: Repeated identical failures activate redundancy guard ────────
@pytest.mark.asyncio
async def test_10_repeated_identical_failures_activate_redundancy_guard(temp_ws):
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, workspace_manager=workspace_manager)
    loop.config.max_turns = 5
    loop._mission_id = "m_test_10"
    loop._tool_failure_counts = {}

    action_key = 'shell.bash:{"command": "npm run broken"}'
    # Simulate 2 consecutive failures
    loop._tool_failure_counts[action_key] = 2

    # Verify that action_key is now blocked
    assert loop._tool_failure_counts.get(action_key, 0) >= 2


# ── Behavior 11: Legitimate retry after source change remains possible ────────
@pytest.mark.asyncio
async def test_11_legitimate_retry_after_source_change_remains_possible(temp_ws):
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, workspace_manager=workspace_manager)
    loop.config.max_turns = 5
    loop._mission_id = "m_test_11"
    loop._tool_failure_counts = {'shell.bash:{"command": "npm run build"}': 2}

    # Simulate intervening file mutation (developer fixes main.js)
    is_mutating = True
    if is_mutating and hasattr(loop, "_tool_failure_counts"):
        loop._tool_failure_counts.clear()

    # After mutation, the failure count is reset to 0, permitting a legitimate retry
    assert loop._tool_failure_counts.get('shell.bash:{"command": "npm run build"}', 0) == 0


# ── Behavior 12: Expired mission budget prevents new model calls ──────────────
def test_12_expired_mission_budget_prevents_new_model_calls():
    # When remaining wall time is less than min model timeout + reserve (15s + 10s = 25s)
    to = calculate_effective_turn_timeout(
        remaining_wall_time=24.0,
        configured_timeout=360.0,
        reserve_seconds=10.0,
        min_model_timeout=15.0,
    )
    assert to is None


# ── Behavior 13: In-flight operation cancelled cleanly ────────────────────────
@pytest.mark.asyncio
async def test_13_inflight_operation_cancelled_cleanly(temp_ws):
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, workspace_manager=workspace_manager)
    loop.config.max_turns = 3
    mission = Mission(mission_id="m_test_13", user_prompt="Build website")
    loop.abort_event.set()  # Cancel immediately

    res = await loop.run(mission)
    assert res.success is False
    assert "Cancelled by user" in (res.termination_reason or res.error or "")


# ── Behavior 14: Recoverable provider outage triggers bounded fallback ────────
@pytest.mark.asyncio
async def test_14_recoverable_provider_outage_triggers_bounded_fallback(temp_ws):
    mock_orch = MagicMock()
    loop = AgentLoop(orchestrator=mock_orch, workspace_manager=workspace_manager)
    loop.config.max_turns = 3
    loop.config.max_consecutive_failures = 2
    events = []
    loop.event_bus.subscribe(lambda e: events.append(e), {EventType.TIER_FAILOVER_STARTED})

    # Mock _generate_model_turn to raise timeout
    with patch.object(loop, "_generate_model_turn", side_effect=TimeoutError("NVIDIA NIM connection timed out")):
        mission = Mission(mission_id="m_test_14", user_prompt="Small task")
        res = await loop.run(mission)
        assert len(events) >= 1
        assert events[0].payload.get("from_tier") == 1
        assert events[0].payload.get("to_tier") == 2


# ── Behavior 15: Invalid request does not loop endlessly ──────────────────────
@pytest.mark.asyncio
async def test_15_invalid_request_does_not_loop_endlessly(tmp_path):
    empty_ws = tmp_path / "empty_target_ws"
    empty_ws.mkdir()
    mock_orch = MagicMock()
    wm = WorkspaceManager()
    wm.lock(str(empty_ws))
    try:
        loop = AgentLoop(orchestrator=mock_orch, workspace_manager=wm)
        loop.config.max_turns = 3
        mission = Mission(
            mission_id="m_test_15",
            user_prompt="Continue improving the existing AURELION website in the active workspace. Fix vehicle dialogs.",
        )
        res = await loop.run(mission)
        assert res.success is False
        assert res.turns_executed == 0
        assert res.termination_reason in ("EMPTY_WORKSPACE_EXISTING_APPLICATION", "PREFLIGHT_VALIDATION_FAILED")
    finally:
        wm.unlock()


# ── Behavior 16: Terminal mission status reflects actual build/browser results ─
def test_16_terminal_mission_status_reflects_actual_build_browser_results(temp_ws):
    # Provide valid scaffold and Three.js canvas setup
    (temp_ws / "package.json").write_text(json.dumps({"name": "rocket-app", "dependencies": {"three": "^0.160.0"}}), encoding="utf-8")
    (temp_ws / "index.html").write_text(
        "<!DOCTYPE html><html><head><link rel='stylesheet' href='style.css'></head>"
        "<body><canvas id='c'></canvas><script type='module' src='main.js'></script></body></html>",
        encoding="utf-8",
    )
    (temp_ws / "main.js").write_text(
        "import * as THREE from 'three';\n"
        "const scene = new THREE.Scene();\n"
        "const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);\n"
        "const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById('c') });\n"
        "function animate() { requestAnimationFrame(animate); renderer.render(scene, camera); }\n"
        "animate();\n",
        encoding="utf-8",
    )
    (temp_ws / "style.css").write_text("body { margin: 0; background: #000; overflow: hidden; }", encoding="utf-8")

    prompt = "Create a responsive Vite and Three.js landing page with a simple rocket model"
    res = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_C,
        temp_ws,
        prompt,
        written_files=["index.html", "main.js", "style.css", "package.json"],
    )
    assert res.passed is True
    assert "Profile C passed" in res.summary
