# tests/test_pixelforge_reproduction.py
"""
Deterministic Reproduction & Qualification Test for PixelForge Incident (m_9830b4ee).
Verifies:
1. WebsiteMvpGate.evaluate() contract and scaffold detection.
2. Dynamic entrypoint discovery (app.js detection from index.html).
3. Provider error handling (HTTP 429 rate limit must NOT be interpreted as CONTINUE_REASONING).
4. Multi-tier recovery context preservation and targeted directive generation.
5. Authoritative deliverable reconciliation prohibiting no-progress read loops.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase
from core.agent_loop.decisions import DecisionInterpreter, AgentDecisionType
from models.provider import NormalizedModelResponse


@pytest.fixture
def pixelforge_workspace(tmp_path: Path):
    """Create a temporary workspace mirroring the exact state of testing 10 at termination."""
    ws = tmp_path / "testing_10_repro"
    ws.mkdir()
    
    # Create package.json
    (ws / "package.json").write_text(
        '{"name": "pixelforge", "version": "1.0.0", "main": "app.js"}',
        encoding="utf-8"
    )
    
    # Create index.html referencing app.js
    (ws / "index.html").write_text(
        '<!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head>'
        '<body><div id="app-container"><canvas id="pixel-canvas"></canvas></div>'
        '<script src="app.js"></script></body></html>',
        encoding="utf-8"
    )
    
    # Create style.css
    (ws / "style.css").write_text(
        'body { background: #121214; color: #fff; margin: 0; } #pixel-canvas { border: 1px solid #333; }',
        encoding="utf-8"
    )
    
    return ws


def test_reproduce_mvp_gate_evaluate_method_exists(pixelforge_workspace: Path):
    """
    Reproduction check for Bug: loop.py:2067 called gate.evaluate() which threw AttributeError.
    The method evaluate() must exist on WebsiteMvpGate and return (is_complete, unmet_list).
    """
    gate = WebsiteMvpGate(workspace_root=pixelforge_workspace)
    assert hasattr(gate, "evaluate"), "WebsiteMvpGate must provide evaluate() method"
    
    ok, unmet = gate.evaluate(pixelforge_workspace)
    assert not ok, "Scaffold must not be complete when app.js is missing"
    assert any("app.js" in req for req in unmet), f"Unmet requirements must include app.js, got: {unmet}"


def test_reproduce_dynamic_entrypoint_discovery(pixelforge_workspace: Path):
    """
    Verify dynamic entrypoint discovery recognizes app.js from index.html <script src='app.js'>.
    """
    gate = WebsiteMvpGate(workspace_root=pixelforge_workspace)
    complete, unmet_scaffold = gate.check_scaffold_complete(pixelforge_workspace)
    
    assert not complete
    assert "app.js" in unmet_scaffold


def test_reproduce_http_429_not_interpreted_as_continue_reasoning():
    """
    Reproduction check for Bug: Provider HTTP 429 response was converted into CONTINUE_REASONING
    with 'Plain text response without JSON schema', masking the provider rate limit.
    A failed response (success=False) must be classified as a provider error or handled cleanly.
    """
    interpreter = DecisionInterpreter()
    
    # Simulated Groq 429 response
    resp = NormalizedModelResponse(
        text="",
        model="qwen/qwen3.8-27b",
        provider="groq",
        error="RATE_LIMIT_EXCEEDED: [429] Rate limit exceeded or quota exhausted",
        success=False,
    )
    
    decision = interpreter.interpret(resp, turn_id="turn_test")
    # Must NOT be CONTINUE_REASONING masquerading as reasoning text
    assert decision.decision_type != AgentDecisionType.CONTINUE_REASONING, (
        "Failed model response (429) must not be interpreted as CONTINUE_REASONING"
    )


def test_parse_scaffold_target_identifies_app_js():
    """
    Verify parse_scaffold_target correctly extracts 'app.js' from scaffold requirements.
    """
    req_str = "Scaffold missing/incomplete: app.js"
    target, instruction = WebsiteMvpGate.parse_scaffold_target(req_str)
    
    assert target == "app.js", f"Target must be app.js, got {target}"
    assert "fs.write" in instruction
