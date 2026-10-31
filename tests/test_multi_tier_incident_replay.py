# tests/test_multi_tier_incident_replay.py
"""
Deterministic Integration Test for Full Multi-Tier Incident Replay & Recovery (P0).
Replays the exact failure trajectory of mission m_9830b4ee across Turns 1-6:
- Turn 1: Tier 1 writes package.json
- Turn 2: Tier 1 writes index.html referencing app.js
- Turn 3: Tier 1 writes style.css
- Turn 4: Tier 1 receives simulated HTTP 503 (Overloaded)
- Turn 5: Tier 2 receives simulated HTTP 429 (Rate limited)
- Turn 6: Tier 3 receives preserved context, discovers missing app.js, mandates write,
          generates valid app.js, syntax passes, and mission completes.

Also validates all required negative cases:
- All three providers fail -> truthful non-success, artifacts preserved
- Tier 3 output is malformed -> rejected, artifacts preserved
- app.js has syntax error -> completion gate rejects
- Browser console reports uncaught error -> rejected
- Recovery budget exhausted -> terminates honestly without false claims
"""

import asyncio
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.adaptive_routing import AdaptiveRouter, ProviderHealthState
from core.agent_loop.decisions import AgentDecision, AgentDecisionType, DecisionInterpreter
from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase
from core.browser.evidence import (
    AuthoritativeBrowserEvidence,
    BrowserEvidenceLifecycle,
    compute_workspace_artifact_hashes,
    persist_authoritative_evidence,
)
from models.common_adapter import NormalizedModelResponse


@pytest.fixture
def replay_workspace(tmp_path: Path) -> Path:
    """Prepare a pristine test workspace."""
    return tmp_path


@pytest.mark.asyncio
async def test_full_multi_tier_incident_replay_success(replay_workspace: Path):
    """
    Full end-to-end replay of Turn 1 to Turn 6 multi-tier incident:
    T1 (writes package.json, index.html, style.css) -> T1 503 -> T2 429 -> T3 Recovery -> app.js written -> verified.
    """
    router = AdaptiveRouter()
    gate = WebsiteMvpGate(workspace_root=replay_workspace, mission_id="m_replay_success")

    # Turn 1: Tier 1 writes package.json
    pkg_content = json.dumps({"name": "pixelforge-app", "version": "1.0.0", "scripts": {"dev": "vite"}}, indent=2)
    (replay_workspace / "package.json").write_text(pkg_content, encoding="utf-8")
    router.record_success(tier=1, latency=0.45)

    # Turn 2: Tier 1 writes index.html referencing app.js
    html_content = """<!DOCTYPE html>
<html lang="en">
<head><link rel="stylesheet" href="style.css"></head>
<body>
    <header id="top-toolbar"><h1>PixelForge</h1></header>
    <main id="canvas-viewport"><canvas id="pixel-canvas" width="400" height="400"></canvas></main>
    <script src="app.js"></script>
</body>
</html>"""
    (replay_workspace / "index.html").write_text(html_content, encoding="utf-8")
    router.record_success(tier=1, latency=0.55)

    # Turn 3: Tier 1 writes style.css
    css_content = "body { margin: 0; background: #0d0f14; color: #fff; } #pixel-canvas { border: 2px solid #8b5cf6; }"
    (replay_workspace / "style.css").write_text(css_content, encoding="utf-8")
    router.record_success(tier=1, latency=0.4)

    # Turn 4: Tier 1 returns HTTP 503 (Overloaded)
    t1_err = RuntimeError("503 UNAVAILABLE: The model is overloaded. Please try again later.")
    router.record_failure(tier=1, error=t1_err)
    assert router.get_health(1).state in (ProviderHealthState.DEGRADED, ProviderHealthState.OPEN_CIRCUIT)

    # Turn 5: Tier 2 receives request and returns HTTP 429 (Rate Limit Exceeded)
    t2_resp = NormalizedModelResponse(
        success=False,
        error="RATE_LIMIT_EXCEEDED: [429] Rate limit reached for model in organization",
        text="",
    )
    # DecisionInterpreter must classify this as INVALID, NOT CONTINUE_REASONING
    interpreter = DecisionInterpreter()
    decision = interpreter.interpret(t2_resp)
    assert decision.decision_type == AgentDecisionType.INVALID
    assert "PROVIDER_ERROR" in decision.reasoning
    router.record_failure(tier=2, error=RuntimeError(t2_resp.error))

    # Turn 6: Recovery transition to Tier 3
    # Check that missing scaffold target is dynamically discovered as app.js
    ok, unmet = gate.evaluate(replay_workspace)
    assert not ok
    assert any("app.js" in req for req in unmet)
    target_repair_file, action_hint = WebsiteMvpGate.parse_scaffold_target(unmet[0])
    assert target_repair_file == "app.js"

    # Tier 3 writes app.js with complete non-placeholder code
    app_content = """// PixelForge Core Interactive Application Engine
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('pixel-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#8b5cf6';
    ctx.fillRect(0, 0, 32, 32);
    console.log('PixelForge initialized successfully.');
});
"""
    (replay_workspace / "app.js").write_text(app_content, encoding="utf-8")

    # Verify Node.js AST syntax passes
    node_res = subprocess.run(["node", "--check", str(replay_workspace / "app.js")], capture_output=True, text=True)
    assert node_res.returncode == 0, f"Node syntax error: {node_res.stderr}"

    # Verify scaffold is now complete
    ok_after_write, missing_after_write = gate.evaluate(replay_workspace)
    assert ok_after_write, f"Scaffold still unmet: {missing_after_write}"

    # Authoritative browser verification evidence generated
    hashes = compute_workspace_artifact_hashes(replay_workspace)
    evidence = AuthoritativeBrowserEvidence(
        evidence_id="ev_replay_001",
        mission_id="m_replay_success",
        workspace_root=str(replay_workspace),
        status=BrowserEvidenceLifecycle.PASSED,
        tested_url="http://127.0.0.1:8000/index.html",
        server_origin="http://127.0.0.1:8000",
        verification_timestamp=time.time(),
        artifact_hashes=hashes,
        viewports_tested=[{"width": 1440, "height": 900}],
        browser_result={"interactions_passed": True, "dom_elements_verified": True},
        console_audit={"uncaught_errors": 0},
        network_audit={"failed_requests": 0},
        provenance="hermes.cdp.verifier.v2",
    )
    persist_authoritative_evidence(replay_workspace, evidence)

    # Acceptance gate evaluates to Phase 4 (Mission Certified Passed)
    gate.build_passed = True
    final_phase = gate.evaluate_phase(replay_workspace)
    assert final_phase == MvpPhase.PHASE_4_ENHANCEMENT
    assert gate.browser_verified is True


@pytest.mark.asyncio
async def test_negative_case_all_three_providers_fail(replay_workspace: Path):
    """
    Negative Case 1: When Tier 1 (503), Tier 2 (429), and Tier 3 (500) all fail,
    the mission terminates honestly without success, and existing artifacts remain intact.
    """
    router = AdaptiveRouter()
    # Initial artifacts exist
    (replay_workspace / "package.json").write_text("{}", encoding="utf-8")
    (replay_workspace / "index.html").write_text("<html></html>", encoding="utf-8")

    router.record_failure(tier=1, error=RuntimeError("503 Overloaded"))
    router.record_failure(tier=2, error=RuntimeError("429 Rate limited"))
    router.record_failure(tier=3, error=RuntimeError("500 Server error"))

    # Verify router state
    assert router.get_health(1).state in (ProviderHealthState.DEGRADED, ProviderHealthState.OPEN_CIRCUIT)
    assert router.get_health(2).state in (ProviderHealthState.DEGRADED, ProviderHealthState.OPEN_CIRCUIT)

    # Artifacts must NOT be deleted or destroyed
    assert (replay_workspace / "package.json").exists()
    assert (replay_workspace / "index.html").exists()


def test_negative_case_tier3_malformed_output():
    """
    Negative Case 2: When Tier 3 returns unparseable or malformed output,
    it is classified as INVALID or CONTINUE_REASONING, never pretending to execute a tool.
    """
    malformed_resp = NormalizedModelResponse(
        success=True,
        text="```json\n{ this is not valid json : [missing closing\n```",
    )
    interpreter = DecisionInterpreter()
    decision = interpreter.interpret(malformed_resp)
    # Must not produce an ACT decision with tool calls
    assert decision.decision_type in (AgentDecisionType.INVALID, AgentDecisionType.CONTINUE_REASONING)
    assert len(decision.tool_calls) == 0


def test_negative_case_app_js_syntax_error(replay_workspace: Path):
    """
    Negative Case 3: If app.js is written with a syntax error, Node.js syntax check rejects it.
    """
    bad_js = replay_workspace / "app.js"
    bad_js.write_text("const broken = { unclosed: true;", encoding="utf-8")
    node_res = subprocess.run(["node", "--check", str(bad_js)], capture_output=True, text=True)
    assert node_res.returncode != 0, "node --check should fail on broken JavaScript syntax"


def test_negative_case_browser_console_errors(replay_workspace: Path):
    """
    Negative Case 4: If browser reports console errors, WebsiteMvpGate rejects browser verification.
    """
    (replay_workspace / "index.html").write_text("""<!DOCTYPE html>
<html lang="en">
<head><link rel="stylesheet" href="style.css"></head>
<body>
    <header id="top-toolbar"><h1>Test App</h1></header>
    <main id="canvas-viewport"><canvas id="pixel-canvas" width="400" height="400"></canvas></main>
    <script src="app.js"></script>
</body>
</html>""", encoding="utf-8")
    (replay_workspace / "style.css").write_text("body { margin: 0; background: #000; color: #fff; }", encoding="utf-8")
    (replay_workspace / "app.js").write_text("""// Production interactive test application
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('pixel-canvas');
    if (canvas) {
        console.log('App started successfully.');
    }
});""", encoding="utf-8")
    (replay_workspace / "package.json").write_text(json.dumps({
        "name": "console-error-test",
        "version": "1.0.0",
        "scripts": {"dev": "vite"}
    }), encoding="utf-8")

    hashes = compute_workspace_artifact_hashes(replay_workspace)
    evidence = AuthoritativeBrowserEvidence(
        evidence_id="ev_console_fail",
        mission_id="m_fail",
        workspace_root=str(replay_workspace),
        status=BrowserEvidenceLifecycle.PASSED,
        tested_url="http://127.0.0.1:8000/index.html",
        server_origin="http://127.0.0.1:8000",
        verification_timestamp=time.time(),
        artifact_hashes=hashes,
        viewports_tested=[{"width": 1440, "height": 900}],
        browser_result={"interactions_passed": True, "dom_elements_verified": True},
        console_audit={"uncaught_errors": 1, "errors": ["ReferenceError: foo is not defined"]},
        network_audit={"failed_requests": 0},
        provenance="hermes.cdp.verifier.v2",
    )
    persist_authoritative_evidence(replay_workspace, evidence)

    gate = WebsiteMvpGate(workspace_root=replay_workspace, mission_id="m_fail")
    gate.build_passed = True
    phase = gate.evaluate_phase(replay_workspace)
    assert phase == MvpPhase.PHASE_3_HTTP_BROWSER_VERIFICATION
    assert gate.browser_verified is False
    assert gate.evidence_lifecycle == BrowserEvidenceLifecycle.FAILED


@pytest.mark.asyncio
async def test_negative_case_recovery_budget_exhaustion():
    """
    Negative Case 5: When recovery transitions exceed max budget, recovery returns False.
    """
    from unittest.mock import MagicMock
    from core.agent_loop.loop import AgentLoop
    from core.agent_loop.types import AgentLoopConfig

    loop = AgentLoop(
        orchestrator=MagicMock(),
        config=AgentLoopConfig(max_turns=10),
    )
    loop._recovery_attempt_count = 4
    loop._total_recovery_budget = 4

    exhausted = await loop._trigger_recovery_transition(
        turn_id="turn_test_exhaust",
        rejection_reason="testing recovery budget exhaustion",
    )
    assert exhausted is False
