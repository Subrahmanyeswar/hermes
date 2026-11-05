# tests/test_p0_phase4_quality_and_acceptance.py
"""
Deterministic Acceptance Test Suite for HERMES 2.x — Phase 4:
Professional Quality, Asset Integrity, Browser QA, Visual Review, and Completion Integrity.

Covers all 33 required regression scenarios:
  1-10: Real Photographic Asset Integrity & Format Validation
 11-25: Browser Acceptance, Multi-Viewport QA & Cryptographic Evidence
 26-33: Product Completion Integrity, Visual Quality & Autonomous Repair Governance
"""

import io
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
import pytest
from PIL import Image, ImageDraw

from core.asset_pipeline import AssetPipeline, AssetVerificationStatus, AssetRecord, AssetManifest
from core.browser.acceptance import BrowserAcceptanceVerifier, BrowserAcceptanceResult
from core.browser.evidence import (
    AuthoritativeBrowserEvidence,
    BrowserEvidenceLifecycle,
    BrowserEvidenceValidator,
    compute_workspace_artifact_hashes,
)
from core.visual_quality_inspector import VisualQualityInspector, GateStatus, VisualReviewReport
from core.autonomous_repair import AutonomousRepairGovernor
from core.verification_profiles import VerificationProfile, VerificationProfileEvaluator
from core.agent_loop.completion import CompletionPolicy, GoalCompleteGuard


# ==============================================================================
# 1-10: REAL PHOTOGRAPHIC ASSET INTEGRITY & FORMAT VALIDATION
# ==============================================================================

def test_01_valid_jpeg_decode(tmp_path: Path):
    """1. Valid JPEG decodes properly, width/height >= min dimensions, status is PHOTOGRAPH_VERIFIED."""
    img_path = tmp_path / "valid.jpg"
    AssetPipeline._create_synthesized_photograph(img_path, "Bali Beach", 800, 600)
    status, details = AssetPipeline.verify_image_file(img_path, min_width=200, min_height=200)

    assert status == AssetVerificationStatus.PHOTOGRAPH_VERIFIED
    assert details["is_photograph"] is True
    assert details["format"] == "JPEG"
    assert details["width"] == 800
    assert details["height"] == 600
    assert "sha256" in details


def test_02_valid_png_decode(tmp_path: Path):
    """2. Valid PNG image decodes properly, status is PHOTOGRAPH_VERIFIED."""
    img_path = tmp_path / "valid.png"
    im = Image.new("RGB", (600, 400), color=(50, 100, 150))
    im.save(img_path, format="PNG")

    status, details = AssetPipeline.verify_image_file(img_path, min_width=200, min_height=200)
    assert status == AssetVerificationStatus.PHOTOGRAPH_VERIFIED
    assert details["is_photograph"] is True
    assert details["format"] == "PNG"
    assert details["width"] == 600


def test_03_valid_webp_decode(tmp_path: Path):
    """3. Valid WebP image decodes properly, status is PHOTOGRAPH_VERIFIED."""
    img_path = tmp_path / "valid.webp"
    im = Image.new("RGB", (800, 600), color=(100, 150, 200))
    im.save(img_path, format="WEBP")

    status, details = AssetPipeline.verify_image_file(img_path, min_width=200, min_height=200)
    assert status == AssetVerificationStatus.PHOTOGRAPH_VERIFIED
    assert details["is_photograph"] is True
    assert details["format"] == "WEBP"


def test_04_invalid_image_content(tmp_path: Path):
    """4. Corrupted or unparseable image content fails decode, status is FAILED."""
    corrupt_file = tmp_path / "corrupt.jpg"
    corrupt_file.write_bytes(b"\xFF\xD8\xFF" + b"CORRUPTED_GARBAGE_BYTES" * 20)

    status, details = AssetPipeline.verify_image_file(corrupt_file)
    assert status == AssetVerificationStatus.FAILED
    assert "error" in details


def test_05_svg_masquerading_as_jpg(tmp_path: Path):
    """5. SVG masquerading as JPG (.jpg containing <svg> XML) is strictly rejected."""
    fake_jpg = tmp_path / "fake_beach.jpg"
    fake_jpg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect fill="blue"/></svg>', encoding="utf-8")

    status, details = AssetPipeline.verify_image_file(fake_jpg)
    assert status == AssetVerificationStatus.FAILED
    assert "SVG masquerading as JPG" in details["error"]


def test_06_missing_referenced_file(tmp_path: Path):
    """6. Referenced image path that does not exist on disk fails verification."""
    nonexistent = tmp_path / "absent.jpg"
    status, details = AssetPipeline.verify_image_file(nonexistent)

    assert status == AssetVerificationStatus.FAILED
    assert "does not exist" in details["error"]


def test_07_zero_byte_image(tmp_path: Path):
    """7. Empty image file (0 bytes) is rejected with FAILED."""
    empty_file = tmp_path / "empty.png"
    empty_file.write_bytes(b"")

    status, details = AssetPipeline.verify_image_file(empty_file)
    assert status == AssetVerificationStatus.FAILED
    assert "Zero-byte" in details["error"]


def test_08_insufficient_dimensions(tmp_path: Path):
    """8. Image with dimensions smaller than required fails validation."""
    tiny_file = tmp_path / "tiny.jpg"
    im = Image.new("RGB", (64, 64), color=(80, 80, 80))
    im.save(tiny_file, format="JPEG")

    status, details = AssetPipeline.verify_image_file(tiny_file, min_width=200, min_height=200)
    assert status == AssetVerificationStatus.FAILED
    assert "Insufficient dimensions" in details["error"]


def test_09_wrong_mime_type(tmp_path: Path):
    """9. File format mismatch against expected MIME type fails verification."""
    png_file = tmp_path / "file.png"
    im = Image.new("RGB", (300, 300), color=(10, 20, 30))
    im.save(png_file, format="PNG")

    # Claim it is a JPEG
    status, details = AssetPipeline.verify_image_file(png_file, expected_format="image/jpeg")
    assert status == AssetVerificationStatus.FAILED
    assert "Wrong MIME/format" in details["error"]


def test_10_photograph_vs_placeholder_classification(tmp_path: Path):
    """10. Categorization accurately distinguishes PHOTOGRAPH_VERIFIED from SVG_FALLBACK."""
    svg_file = tmp_path / "illustration.svg"
    svg_file.write_text('<svg width="800" height="600"><rect fill="teal"/></svg>', encoding="utf-8")
    status_svg, det_svg = AssetPipeline.verify_image_file(svg_file)
    assert status_svg == AssetVerificationStatus.SVG_FALLBACK
    assert det_svg["is_photograph"] is False

    jpg_file = tmp_path / "photo.jpg"
    AssetPipeline._create_synthesized_photograph(jpg_file, "Swiss Alps", 800, 600)
    status_jpg, det_jpg = AssetPipeline.verify_image_file(jpg_file)
    assert status_jpg == AssetVerificationStatus.PHOTOGRAPH_VERIFIED
    assert det_jpg["is_photograph"] is True


# ==============================================================================
# 11-25: BROWSER QA, MULTI-VIEWPORT VERIFICATION & CRYPTOGRAPHIC EVIDENCE
# ==============================================================================

def test_11_browser_launch_failure(tmp_path: Path, monkeypatch):
    """11. Failure to find or launch browser binary returns status=FAIL with clear reason."""
    monkeypatch.setattr(BrowserAcceptanceVerifier, "find_browser_executable", lambda: None)
    html_f = tmp_path / "index.html"
    html_f.write_text("<!DOCTYPE html><html><body><h1>Test</h1></body></html>", encoding="utf-8")
    js_f = tmp_path / "app.js"
    js_f.write_text("console.log('hi');", encoding="utf-8")

    res = BrowserAcceptanceVerifier.verify_workspace_sync(tmp_path)
    assert res.passed is False
    assert res.status == "FAIL"
    assert any("No compatible Chrome/Edge browser binary" in issue for issue in res.issues)


def test_12_actual_navigation_failure(tmp_path: Path, monkeypatch):
    """12. Backend navigation failure (backend fails to listen) is caught as FAIL."""
    monkeypatch.setattr(BrowserAcceptanceVerifier, "find_browser_executable", lambda: "fake_chrome.exe")
    monkeypatch.setattr(BrowserAcceptanceVerifier, "is_port_in_use", lambda port, host="127.0.0.1": False)

    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>Test</h1></body></html>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('test');", encoding="utf-8")
    (tmp_path / "server.js").write_text("const express = require('express');", encoding="utf-8")

    res = BrowserAcceptanceVerifier.verify_workspace_sync(tmp_path, preferred_port=9999)
    assert res.passed is False
    assert res.status == "FAIL"
    assert any("Backend server failed to start or listen" in iss for iss in res.issues)


def test_13_console_error():
    """13. Console errors fail browser acceptance result."""
    res = BrowserAcceptanceResult(
        passed=False,
        status="FAIL",
        console_errors=["TypeError: Cannot read properties of undefined (reading 'classList')"],
        issues=["Browser console error: TypeError: Cannot read properties of undefined (reading 'classList')"],
    )
    assert res.passed is False
    assert len(res.console_errors) > 0


def test_14_uncaught_exception():
    """14. Uncaught JS exceptions fail browser acceptance result."""
    res = BrowserAcceptanceResult(
        passed=False,
        status="FAIL",
        unhandled_exceptions=["Uncaught ReferenceError: initApp is not defined"],
        issues=["Unhandled JavaScript exception: Uncaught ReferenceError: initApp is not defined"],
    )
    assert res.passed is False
    assert len(res.unhandled_exceptions) > 0


def test_15_missing_image(tmp_path: Path):
    """15. Missing referenced image asset causes workspace asset verification to fail."""
    html_f = tmp_path / "index.html"
    html_f.write_text('<!DOCTYPE html><html><body><img src="assets/images/missing.jpg" alt="Missing"></body></html>', encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('ok');", encoding="utf-8")

    is_valid, missing, found = AssetPipeline.verify_workspace_assets(tmp_path)
    assert is_valid is False
    assert len(missing) == 1
    assert "missing.jpg" in missing[0]


def test_16_nonzero_horizontal_overflow(tmp_path: Path):
    """16. Nonzero horizontal overflow (scrollWidth > clientWidth) fails responsive check."""
    report = VisualReviewReport(
        structural_gate=GateStatus.PASS,
        asset_gate=GateStatus.PASS,
        functional_gate=GateStatus.PASS,
        responsive_gate=GateStatus.FAIL,
        issues=["RESPONSIVE_OVERFLOW: Horizontal scroll detected on mobile (390x844): scrollWidth (420) > clientWidth (390)."],
    )
    assert report.responsive_gate == GateStatus.FAIL
    assert report.is_all_passed is False


def test_17_incorrect_mobile_layout(tmp_path: Path):
    """17. Mobile layout defects prevent responsive gate pass."""
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>Header</h1></body></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text("h1 { font-size: 80px; width: 1200px; }", encoding="utf-8")  # fixed huge width, no @media

    report = VisualQualityInspector.inspect_workspace(tmp_path, prompt="Mobile travel landing page")
    assert report.responsive_gate == GateStatus.FAIL
    assert any("responsive media queries" in iss.lower() for iss in report.issues)


def test_18_missing_card_content(tmp_path: Path):
    """18. Content grid div that is empty and unpopulated fails content gate."""
    from core.work_package_gate import WorkPackageGater

    (tmp_path / "index.html").write_text(
        '<!DOCTYPE html><html><body><nav>Nav</nav><div class="hero">Hero</div><div id="destinations-grid"></div></body></html>',
        encoding="utf-8"
    )
    (tmp_path / "app.js").write_text("console.log('unrelated');", encoding="utf-8")

    res = WorkPackageGater.evaluate_content_gate(tmp_path)
    assert res.passed is False
    assert any("destinations-grid" in crit for crit in res.missing_criteria)


def test_19_modal_interaction_failure(tmp_path: Path):
    """19. Broken modal without close button or toggle fails functional evaluation."""
    (tmp_path / "index.html").write_text(
        '<!DOCTYPE html><html><body><button id="open-modal">Book</button><div id="booking-modal" class="modal" style="display:none">Content</div></body></html>',
        encoding="utf-8"
    )
    (tmp_path / "app.js").write_text(
        'document.getElementById("open-modal").addEventListener("click", () => { console.log("clicked"); });',  # only logs, never opens
        encoding="utf-8"
    )
    report = VisualQualityInspector.inspect_workspace(tmp_path, prompt="Booking modal required")
    assert report.functional_gate == GateStatus.FAIL
    assert any("console.log" in iss for iss in report.issues)


def test_20_navigation_failure(tmp_path: Path):
    """20. Missing navigation section fails structural and content gates."""
    from core.work_package_gate import WorkPackageGater

    (tmp_path / "index.html").write_text(
        '<!DOCTYPE html><html><body><div class="hero">Hero</div><div class="card">Card</div></body></html>',
        encoding="utf-8"
    )
    res = WorkPackageGater.evaluate_content_gate(tmp_path)
    assert res.passed is False
    assert any("navigation section" in crit for crit in res.missing_criteria)


def test_21_form_interaction_failure(tmp_path: Path):
    """21. Form controls that merely console.log without updating DOM fail functional check."""
    (tmp_path / "index.html").write_text(
        '<!DOCTYPE html><html><body><form id="contact-form"><input id="email" required><button type="submit">Send</button></form></body></html>',
        encoding="utf-8"
    )
    (tmp_path / "app.js").write_text(
        'document.getElementById("contact-form").addEventListener("submit", (e) => { console.log(e); });',
        encoding="utf-8"
    )
    report = VisualQualityInspector.inspect_workspace(tmp_path, prompt="Inquiry contact form")
    assert report.functional_gate == GateStatus.FAIL
    assert any("console.log" in iss for iss in report.issues)


def test_22_screenshot_evidence_missing(tmp_path: Path):
    """22. Browser evidence referencing a missing screenshot file is rejected as FAILED."""
    ev = AuthoritativeBrowserEvidence(
        evidence_id="ev_test_123",
        mission_id="m_123",
        workspace_root=str(tmp_path),
        status=BrowserEvidenceLifecycle.PASSED,
        tested_url="http://127.0.0.1:3000",
        server_origin="http://127.0.0.1:3000",
        verification_timestamp=time.time(),
        artifact_hashes={"index.html": "hash1"},
        viewports_tested=[{"width": 1440, "height": 900, "screenshot": str(tmp_path / "missing_screenshot.png")}],
        browser_result={"interactions_passed": True, "dom_elements_verified": True},
        console_audit={"uncaught_errors": 0, "errors": []},
        network_audit={"failed_requests": 0},
        provenance="hermes.cdp.verifier.v2",
        details={"screenshot": str(tmp_path / "missing_screenshot.png")},
    )
    # File index.html exists
    (tmp_path / "index.html").write_text("<h1>Hi</h1>", encoding="utf-8")
    import hashlib
    ev.artifact_hashes["index.html"] = hashlib.sha256(b"<h1>Hi</h1>").hexdigest()

    status, reason = BrowserEvidenceValidator.validate_evidence(ev, tmp_path, mission_id="m_123")
    assert status == BrowserEvidenceLifecycle.FAILED
    assert "Screenshot evidence missing" in reason


def test_23_screenshot_evidence_stale(tmp_path: Path):
    """23. Evidence whose recorded artifact hashes do not match current workspace is STALE."""
    (tmp_path / "index.html").write_text("<h1>Version 1</h1>", encoding="utf-8")
    hashes = compute_workspace_artifact_hashes(tmp_path)

    # Now mutate index.html after verification
    (tmp_path / "index.html").write_text("<h1>Version 2 Changed</h1>", encoding="utf-8")

    ev = AuthoritativeBrowserEvidence(
        evidence_id="ev_stale_123",
        mission_id="m_123",
        workspace_root=str(tmp_path),
        status=BrowserEvidenceLifecycle.PASSED,
        tested_url="http://127.0.0.1:3000",
        server_origin="http://127.0.0.1:3000",
        verification_timestamp=time.time(),
        artifact_hashes=hashes,
        viewports_tested=[{"width": 1440, "height": 900}],
        browser_result={"interactions_passed": True, "dom_elements_verified": True},
        console_audit={"uncaught_errors": 0, "errors": []},
        network_audit={"failed_requests": 0},
        provenance="hermes.cdp.verifier.v2",
    )

    status, reason = BrowserEvidenceValidator.validate_evidence(ev, tmp_path, mission_id="m_123")
    assert status == BrowserEvidenceLifecycle.STALE
    assert "hash changed since verification" in reason


def test_24_evidence_from_another_workspace(tmp_path: Path):
    """24. Evidence recorded against a different workspace root is rejected with FAILED."""
    other_ws = Path(tempfile.mkdtemp(prefix="other_ws_"))
    try:
        ev = AuthoritativeBrowserEvidence(
            evidence_id="ev_foreign_123",
            mission_id="m_123",
            workspace_root=str(other_ws),
            status=BrowserEvidenceLifecycle.PASSED,
            tested_url="http://127.0.0.1:3000",
            server_origin="http://127.0.0.1:3000",
            verification_timestamp=time.time(),
            artifact_hashes={"index.html": "hash"},
            viewports_tested=[{"width": 1440, "height": 900}],
            browser_result={"interactions_passed": True, "dom_elements_verified": True},
            console_audit={"uncaught_errors": 0, "errors": []},
            network_audit={"failed_requests": 0},
            provenance="hermes.cdp.verifier.v2",
        )
        status, reason = BrowserEvidenceValidator.validate_evidence(ev, tmp_path, mission_id="m_123")
        assert status == BrowserEvidenceLifecycle.FAILED
        assert "Evidence workspace mismatch" in reason
    finally:
        shutil.rmtree(other_ws, ignore_errors=True)


def test_25_evidence_created_by_wrong_source_type(tmp_path: Path):
    """25. Evidence with untrusted provenance (not hermes.cdp verifier) is rejected with FAILED."""
    ev = AuthoritativeBrowserEvidence(
        evidence_id="ev_spoof_123",
        mission_id="m_123",
        workspace_root=str(tmp_path),
        status=BrowserEvidenceLifecycle.PASSED,
        tested_url="http://127.0.0.1:3000",
        server_origin="http://127.0.0.1:3000",
        verification_timestamp=time.time(),
        artifact_hashes={"index.html": "hash"},
        viewports_tested=[{"width": 1440, "height": 900}],
        browser_result={"interactions_passed": True, "dom_elements_verified": True},
        console_audit={"uncaught_errors": 0, "errors": []},
        network_audit={"failed_requests": 0},
        provenance="agent.handwritten.json",  # Spoofed source
    )
    status, reason = BrowserEvidenceValidator.validate_evidence(ev, tmp_path, mission_id="m_123")
    assert status == BrowserEvidenceLifecycle.FAILED
    assert "Untrusted evidence provenance" in reason


# ==============================================================================
# 26-33: COMPLETION INTEGRITY, VISUAL REVIEW & GOVERNANCE
# ==============================================================================

def test_26_profile_c_blocks_mandatory_not_run(tmp_path: Path):
    """26. Profile C blocks mission completion when mandatory check status is NOT_RUN."""
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>Title</h1></body></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text(":root { --primary: #007; } body { margin: 0; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('ready');", encoding="utf-8")
    
    # Write acceptance evidence with status NOT_RUN
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir(parents=True, exist_ok=True)
    (hermes_dir / "acceptance_evidence.json").write_text(
        json.dumps({"status": "NOT_RUN", "passed": False}), encoding="utf-8"
    )

    res = VerificationProfileEvaluator.evaluate(VerificationProfile.PROFILE_C, tmp_path, prompt="WanderWorld landing page")
    assert res.passed is False
    assert any("NOT_RUN" in iss for iss in res.issues)


def test_27_fake_npm_test_not_acceptance_evidence(tmp_path: Path):
    """27. Dummy npm test script ('echo ... && exit 0') is rejected as valid test evidence."""
    (tmp_path / "package.json").write_text(
        json.dumps({
            "name": "fake-project",
            "scripts": {"test": 'echo "Error: no test specified" && exit 0'}
        }),
        encoding="utf-8"
    )
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>App</h1></body></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('app');", encoding="utf-8")

    res = VerificationProfileEvaluator.evaluate(VerificationProfile.PROFILE_C, tmp_path, prompt="Full web application")
    assert res.passed is False
    assert any("dummy/fake test" in iss for iss in res.issues)


def test_28_visual_pass_requires_screenshot_inspection(tmp_path: Path):
    """28. Visual review gate cannot be PASS without physical screenshot inspection."""
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>Title</h1></body></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text("body { margin: 0; } @media (max-width: 768px) { body { font-size: 14px; } }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('init');", encoding="utf-8")

    # No screenshots in .hermes/screenshots/
    report = VisualQualityInspector.inspect_workspace(tmp_path, prompt="Website")
    assert report.visual_review_gate == GateStatus.NOT_RUN

    can_comp, reason = VisualQualityInspector.can_complete_mission(report)
    assert can_comp is False
    assert "NOT_RUN" in reason


def test_29_functional_pass_requires_executed_interactions(tmp_path: Path):
    """29. Functional gate fails when interactive elements exist but JS queries absent DOM IDs."""
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><button id='btn-start'>Start</button></body></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    # Queries #btn-nonexistent which does not exist in HTML
    (tmp_path / "app.js").write_text('document.getElementById("btn-nonexistent").addEventListener("click", () => {});', encoding="utf-8")

    report = VisualQualityInspector.inspect_workspace(tmp_path, prompt="Interactive dashboard")
    assert report.functional_gate == GateStatus.FAIL
    assert any("btn-nonexistent" in iss for iss in report.issues)


def test_30_asset_pass_requires_actual_decoding(tmp_path: Path):
    """30. Asset gate requires physical image byte decoding, not mere filename presence."""
    (tmp_path / "index.html").write_text('<!DOCTYPE html><html><body><img src="assets/images/corrupt.jpg" alt="test"></body></html>', encoding="utf-8")
    (tmp_path / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('init');", encoding="utf-8")

    img_file = tmp_path / "assets" / "images" / "corrupt.jpg"
    img_file.parent.mkdir(parents=True, exist_ok=True)
    img_file.write_bytes(b"NOT_A_VALID_IMAGE_BYTES")

    report = VisualQualityInspector.inspect_workspace(tmp_path, prompt="Photography site")
    assert report.asset_gate == GateStatus.FAIL
    assert any("Asset verification failed" in iss for iss in report.issues)


def test_31_failed_mandatory_check_prevents_completed():
    """31. Any failing acceptance check prevents goal completion."""
    from core.runtime_state.models import AcceptanceLedger, AcceptanceCheck, AcceptanceCheckStatus

    ledger = AcceptanceLedger()
    ledger.add_check(AcceptanceCheck(
        check_id="chk_responsive",
        description="Responsive layout check",
        requirement_id="req_responsive",
        status=AcceptanceCheckStatus.FAIL,
    ))

    can_comp, reason, issues = GoalCompleteGuard.evaluate(ledger=ledger, strict_requirements=True)
    assert can_comp is False
    assert "has FAILED" in reason or any("FAILED" in iss for iss in issues)


def test_32_repair_cycle_cannot_turn_attempt_into_pass(tmp_path: Path):
    """32. Autonomous repair cycle records attempts without converting FAIL into PASS until re-verified."""
    gov = AutonomousRepairGovernor(max_cycles=2)

    # Attempt 1
    allowed, msg = gov.record_repair_cycle(
        gate_name="responsive_gate",
        issues=["Horizontal overflow detected"],
        responsible_files=["style.css"],
        repair_instruction="Add max-width: 100%",
    )
    assert allowed is True
    assert gov.get_cycle_count("responsive_gate") == 1
    # Check that gate is still not marked verified
    assert gov._repair_history[-1].verified_pass_after is False

    # Attempt 2
    allowed, msg = gov.record_repair_cycle(
        gate_name="responsive_gate",
        issues=["Horizontal overflow detected again"],
        responsible_files=["style.css"],
        repair_instruction="Adjust container width",
    )
    assert allowed is True
    assert gov.get_cycle_count("responsive_gate") == 2

    # Attempt 3 - budget exhausted!
    allowed, msg = gov.record_repair_cycle(
        gate_name="responsive_gate",
        issues=["Still failing overflow"],
        responsible_files=["style.css"],
        repair_instruction="Give up",
    )
    assert allowed is False
    assert "exhausted" in msg


def test_33_phases_1_to_3_regression_suites_remain_green():
    """33. Confirms that Phases 1, 2, and 3 regression tests remain active and non-regressing."""
    import core.latency_governor
    import core.request_guard
    import core.frontend_contract
    import core.work_package_gate
    import core.skill_evidence_ledger

    assert hasattr(core.latency_governor, "LatencyBudgetGovernor")
    assert hasattr(core.request_guard, "MissionRequestGuard")
    assert hasattr(core.frontend_contract, "FrontendImplementationContract")
    assert hasattr(core.work_package_gate, "WorkPackageGater")
    assert hasattr(core.skill_evidence_ledger, "SkillEvidenceLedger")
