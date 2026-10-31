# tests/test_browser_evidence_integrity.py
"""
Test Suite for Browser Evidence Integrity & Lifecycle Verification.
Validates:
1. Static files cannot certify interactive browser verification.
2. Stale artifact evidence is rejected (hash mismatch).
3. Browser evidence must match workspace and mission.
4. A fake JSON with {"status": "passed"} cannot certify without valid provenance and hashes.
5. Browser console errors prevent acceptance.
6. Behavioral failures prevent acceptance.
"""

import json
import time
from pathlib import Path
import pytest

from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase
from core.browser.evidence import (
    AuthoritativeBrowserEvidence,
    BrowserEvidenceLifecycle,
    BrowserEvidenceValidator,
    compute_workspace_artifact_hashes,
    persist_authoritative_evidence,
)


@pytest.fixture
def interactive_workspace(tmp_path: Path) -> Path:
    """Create a temporary interactive web application workspace."""
    (tmp_path / "index.html").write_text("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Interactive App</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <button id="btn-draw">Draw</button>
    <canvas id="pixel-canvas" width="300" height="300"></canvas>
    <script src="app.js"></script>
</body>
</html>""", encoding="utf-8")
    
    (tmp_path / "style.css").write_text("""/* Application Styling */
body { margin: 0; padding: 20px; background: #121214; color: #f8fafc; font-family: sans-serif; }
#pixel-canvas { border: 2px solid #8b5cf6; display: block; }
""", encoding="utf-8")

    (tmp_path / "app.js").write_text("""// Complete Interactive Application Entrypoint
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('btn-draw');
    const canvas = document.getElementById('pixel-canvas');
    if (btn && canvas) {
        btn.addEventListener('click', () => {
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#8b5cf6';
            ctx.fillRect(10, 10, 50, 50);
        });
    }
});
""", encoding="utf-8")

    (tmp_path / "package.json").write_text(json.dumps({
        "name": "interactive-app",
        "version": "1.0.0",
        "description": "Production interactive test application",
        "scripts": {"dev": "vite"}
    }), encoding="utf-8")
    return tmp_path


def test_static_files_cannot_certify_interactive_browser_verification(interactive_workspace: Path):
    """
    Scenario 1: Verify that merely having index.html, style.css, and app.js
    does NOT certify browser_verified = True for an interactive application.
    """
    gate = WebsiteMvpGate(workspace_root=interactive_workspace, mission_id="m_test_static")
    gate.build_passed = True
    
    # Phase must evaluate to PHASE_3_HTTP_BROWSER_VERIFICATION, NOT PHASE_4
    phase = gate.evaluate_phase(interactive_workspace)
    assert phase == MvpPhase.PHASE_3_HTTP_BROWSER_VERIFICATION
    assert gate.browser_verified is False
    assert gate.evidence_lifecycle == BrowserEvidenceLifecycle.UNAVAILABLE
    
    unmet = gate.get_unmet_requirements(interactive_workspace)
    assert any("Authoritative browser qualification not passed" in u for u in unmet)


def test_stale_artifact_evidence_is_rejected(interactive_workspace: Path):
    """
    Scenario 2: Verify that if an artifact is modified after verification,
    the evidence is marked STALE and rejected.
    """
    hashes = compute_workspace_artifact_hashes(interactive_workspace)
    ev = AuthoritativeBrowserEvidence(
        evidence_id="ev_001",
        mission_id="m_test_stale",
        workspace_root=str(interactive_workspace),
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
    persist_authoritative_evidence(interactive_workspace, ev)

    # Initial check should pass
    gate = WebsiteMvpGate(workspace_root=interactive_workspace, mission_id="m_test_stale")
    gate.build_passed = True
    phase = gate.evaluate_phase(interactive_workspace)
    assert phase == MvpPhase.PHASE_4_ENHANCEMENT
    assert gate.browser_verified is True
    assert gate.evidence_lifecycle == BrowserEvidenceLifecycle.PASSED

    # Mutate app.js with valid new content (> 40B)
    (interactive_workspace / "app.js").write_text("""// Complete Interactive Application Entrypoint (Mutated After Test)
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('btn-draw');
    const canvas = document.getElementById('pixel-canvas');
    if (btn && canvas) {
        btn.addEventListener('click', () => {
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#ef4444';
            ctx.fillRect(20, 20, 60, 60);
        });
    }
});
""", encoding="utf-8")

    # Re-evaluating phase must flag evidence as STALE and reset browser_verified
    gate.browser_verified = False  # Reset flag to re-evaluate
    phase_after_mutation = gate.evaluate_phase(interactive_workspace)
    assert phase_after_mutation == MvpPhase.PHASE_3_HTTP_BROWSER_VERIFICATION
    assert gate.browser_verified is False
    assert gate.evidence_lifecycle == BrowserEvidenceLifecycle.STALE
    assert "hash changed" in (gate.last_browser_error or "").lower()


def test_browser_evidence_must_match_workspace_and_mission(interactive_workspace: Path, tmp_path: Path):
    """
    Scenario 3: Evidence bound to a different workspace or mission ID must be rejected.
    """
    other_workspace = tmp_path / "other_ws"
    other_workspace.mkdir()
    
    hashes = compute_workspace_artifact_hashes(interactive_workspace)
    ev = AuthoritativeBrowserEvidence(
        evidence_id="ev_002",
        mission_id="m_mission_A",
        workspace_root=str(other_workspace),  # Wrong workspace
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
    persist_authoritative_evidence(interactive_workspace, ev)

    gate = WebsiteMvpGate(workspace_root=interactive_workspace, mission_id="m_mission_A")
    gate.build_passed = True
    gate.evaluate_phase(interactive_workspace)
    assert gate.browser_verified is False
    assert gate.evidence_lifecycle == BrowserEvidenceLifecycle.FAILED
    assert "workspace mismatch" in (gate.last_browser_error or "").lower()


def test_fake_json_without_provenance_is_rejected(interactive_workspace: Path):
    """
    Scenario 4: An arbitrary JSON file with {"status": "passed"} but missing
    provenance, hashes, and audits must be rejected.
    """
    fake_ev_file = interactive_workspace / "browser-qualification.json"
    fake_ev_file.write_text(json.dumps({"status": "passed", "http_status": 200}), encoding="utf-8")

    gate = WebsiteMvpGate(workspace_root=interactive_workspace, mission_id="m_fake")
    gate.build_passed = True
    gate.evaluate_phase(interactive_workspace)
    assert gate.browser_verified is False
    assert gate.evidence_lifecycle == BrowserEvidenceLifecycle.FAILED
    assert "untrusted evidence provenance" in (gate.last_browser_error or "").lower()


def test_browser_console_errors_prevent_acceptance(interactive_workspace: Path):
    """
    Scenario 14: An evidence record reporting console errors must be classified as FAILED.
    """
    hashes = compute_workspace_artifact_hashes(interactive_workspace)
    ev = AuthoritativeBrowserEvidence(
        evidence_id="ev_003",
        mission_id="m_console_err",
        workspace_root=str(interactive_workspace),
        status=BrowserEvidenceLifecycle.PASSED,
        tested_url="http://127.0.0.1:8000/index.html",
        server_origin="http://127.0.0.1:8000",
        verification_timestamp=time.time(),
        artifact_hashes=hashes,
        viewports_tested=[{"width": 1440, "height": 900}],
        browser_result={"interactions_passed": True, "dom_elements_verified": True},
        console_audit={"uncaught_errors": 2, "errors": ["TypeError: null is not an object"]},
        network_audit={"failed_requests": 0},
        provenance="hermes.cdp.verifier.v2",
    )
    persist_authoritative_evidence(interactive_workspace, ev)

    gate = WebsiteMvpGate(workspace_root=interactive_workspace, mission_id="m_console_err")
    gate.build_passed = True
    gate.evaluate_phase(interactive_workspace)
    assert gate.browser_verified is False
    assert gate.evidence_lifecycle == BrowserEvidenceLifecycle.FAILED
    assert "uncaught error" in (gate.last_browser_error or "").lower()


def test_behavioral_failure_prevents_acceptance(interactive_workspace: Path):
    """
    Scenario 15: If browser_result.interactions_passed is False, acceptance is rejected.
    """
    hashes = compute_workspace_artifact_hashes(interactive_workspace)
    ev = AuthoritativeBrowserEvidence(
        evidence_id="ev_004",
        mission_id="m_behavior_fail",
        workspace_root=str(interactive_workspace),
        status=BrowserEvidenceLifecycle.PASSED,
        tested_url="http://127.0.0.1:8000/index.html",
        server_origin="http://127.0.0.1:8000",
        verification_timestamp=time.time(),
        artifact_hashes=hashes,
        viewports_tested=[{"width": 1440, "height": 900}],
        browser_result={"interactions_passed": False, "dom_elements_verified": True, "failure_reason": "Button click threw exception"},
        console_audit={"uncaught_errors": 0},
        network_audit={"failed_requests": 0},
        provenance="hermes.cdp.verifier.v2",
    )
    persist_authoritative_evidence(interactive_workspace, ev)

    gate = WebsiteMvpGate(workspace_root=interactive_workspace, mission_id="m_behavior_fail")
    gate.build_passed = True
    gate.evaluate_phase(interactive_workspace)
    assert gate.browser_verified is False
    assert gate.evidence_lifecycle == BrowserEvidenceLifecycle.FAILED
    assert "interactions not certified passed" in (gate.last_browser_error or "").lower()
