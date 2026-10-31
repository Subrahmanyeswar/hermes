# tests/test_recovery_targeted_repair.py
"""
Regression test suite verifying targeted recovery brief generation,
completed-file churn prevention, and scaffold qualification in HERMES.
Directly reproduces and guards against the failure pattern of mission m_506cb069.
"""

import json
from pathlib import Path
import pytest

from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase


def test_parse_scaffold_target():
    """Verify that parse_scaffold_target extracts filename and targeted instructions."""
    # 1. Missing entrypoint script tag (m_506cb069 failure)
    target, action = WebsiteMvpGate.parse_scaffold_target(
        "Scaffold missing/incomplete: index.html (missing entrypoint <script> tag)"
    )
    assert target == "index.html"
    assert "entrypoint script tag" in action

    # 2. Incomplete main.js
    target, action = WebsiteMvpGate.parse_scaffold_target(
        "Scaffold missing/incomplete: main.js (incomplete or contains placeholder stubs: missing methods)"
    )
    assert target == "main.js"
    assert "placeholder stubs" in action

    # 3. Missing style.css
    target, action = WebsiteMvpGate.parse_scaffold_target("Scaffold missing/incomplete: style.css")
    assert target == "style.css"
    assert "Create 'style.css'" in action

    # 4. Build verification requirement
    target, action = WebsiteMvpGate.parse_scaffold_target(
        "Build not verified. Project build must pass (npm run build)."
    )
    assert target == "npm run build"
    assert "npm run build" in action


def test_vanilla_web_app_phase_evaluation(tmp_path: Path):
    """
    Verify that vanilla HTML/CSS/JS applications without a build script
    in package.json auto-qualify through Phase 2 without failing on npm run build.
    """
    # Create complete scaffold
    pkg = {
        "name": "test-taskflow",
        "version": "1.0.0",
        "scripts": {"start": "npx http-server ."}
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (tmp_path / "index.html").write_text(
        "<!DOCTYPE html><html><head><link rel=\"stylesheet\" href=\"style.css\"></head>"
        "<body><div id=\"app\"></div><script src=\"app.js\"></script></body></html>",
        encoding="utf-8"
    )
    (tmp_path / "style.css").write_text("/* Main application stylesheet */\nbody { background: #fff; margin: 0; padding: 0; font-family: sans-serif; }", encoding="utf-8")
    (tmp_path / "app.js").write_text(
        "document.addEventListener('DOMContentLoaded', () => { console.log('ready'); });",
        encoding="utf-8"
    )

    gate = WebsiteMvpGate(workspace_root=tmp_path)
    ok, missing = gate.check_scaffold_complete(tmp_path)
    assert ok is True
    assert len(missing) == 0

    phase = gate.evaluate_phase(tmp_path)
    # Since build is not required and static deliverables exist, should be Phase 4 Enhancement
    assert phase == MvpPhase.PHASE_4_ENHANCEMENT
    assert len(gate.get_unmet_requirements(tmp_path)) == 0


def test_scaffold_detects_truncated_html(tmp_path: Path):
    """Verify that truncated index.html missing script tag is detected."""
    (tmp_path / "package.json").write_text('{"name": "test", "version": "1.0.0"}', encoding="utf-8")
    # Truncated index.html cut off at line 69
    (tmp_path / "index.html").write_text(
        "<!DOCTYPE html><html><head><link rel=\"stylesheet\" href=\"style.css\"></head><body><div>",
        encoding="utf-8"
    )
    (tmp_path / "style.css").write_text("body { background: #fff; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('app');", encoding="utf-8")

    gate = WebsiteMvpGate(workspace_root=tmp_path)
    ok, missing = gate.check_scaffold_complete(tmp_path)
    assert ok is False
    assert any("missing entrypoint <script> tag" in m for m in missing)
