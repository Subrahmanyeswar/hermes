# tests/test_p0_quality_integrity_and_asset_pipeline.py
"""
P0 Quality Integrity & Asset Pipeline Test Suite for HERMES 2.x.
Verifies professional website generation, design intelligence persistence,
asset provisioning and verification, cross-file integration contract enforcement,
and authoritative browser visual acceptance.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

from core.asset_pipeline import AssetPipeline, AssetManifest, AssetRecord
from core.design_intelligence import DesignBrief, DesignBriefGenerator, ContentCoverageMap
from core.frontend_contract_validator import FrontendContractValidator, FrontendValidationReport
from core.verification_profiles import VerificationProfile, VerificationProfileEvaluator


@pytest.fixture
def temp_workspace():
    """Isolated temporary workspace directory."""
    d = tempfile.mkdtemp(prefix="hermes_quality_test_")
    ws = Path(d).resolve()
    yield ws
    shutil.rmtree(d, ignore_errors=True)


# ── Behavior 1: Asset Pipeline provisions local assets on disk ─────────────────
def test_01_asset_pipeline_provisions_local_assets(temp_workspace):
    manifest = AssetPipeline.provision_assets(
        workspace_root=temp_workspace,
        prompt="Build a WanderWorld travel agency website with destination cards for Bali and Paris",
        domain="travel_tourism",
        mission_id="m_test_assets",
    )
    assert len(manifest.assets) >= 5
    assert (temp_workspace / ".hermes" / "asset_manifest.json").exists()
    assert (temp_workspace / ".artifacts" / "asset_manifest.md").exists()

    # Verify physical file existence and non-zero size
    for rec in manifest.assets:
        p = temp_workspace / rec.relative_path
        assert p.exists()
        assert p.stat().st_size > 0


# ── Behavior 2: Asset Pipeline detects missing local assets ───────────────────
def test_02_asset_pipeline_detects_missing_assets(temp_workspace):
    (temp_workspace / "index.html").write_text(
        '<!DOCTYPE html><html><body><img src="assets/images/destinations/nonexistent.jpg" alt="test"></body></html>',
        encoding="utf-8",
    )
    is_ok, missing, found = AssetPipeline.verify_workspace_assets(temp_workspace)
    assert is_ok is False
    assert "assets/images/destinations/nonexistent.jpg" in missing


# ── Behavior 3: Asset Pipeline passes when referenced images exist ─────────────
def test_03_asset_pipeline_passes_when_all_assets_exist(temp_workspace):
    img_dir = temp_workspace / "assets" / "images" / "destinations"
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "bali.jpg").write_bytes(b"\xff\xd8\xff\xe0testjpegdata")

    (temp_workspace / "index.html").write_text(
        '<!DOCTYPE html><html><body><img src="assets/images/destinations/bali.jpg" alt="Bali"></body></html>',
        encoding="utf-8",
    )
    is_ok, missing, found = AssetPipeline.verify_workspace_assets(temp_workspace)
    assert is_ok is True
    assert len(missing) == 0
    assert "assets/images/destinations/bali.jpg" in found


# ── Behavior 4: Asset directive formatting ────────────────────────────────────
def test_04_asset_directive_contains_verified_paths():
    manifest = AssetManifest(
        domain="travel_tourism",
        assets=[
            AssetRecord(
                asset_id="hero",
                local_path="assets/images/hero.jpg",
                relative_path="assets/images/hero.jpg",
                intended_component="hero",
                subject="Tropical Paradise Hero",
                alt_text="Turquoise Ocean",
            ),
            AssetRecord(
                asset_id="dest_bali",
                local_path="assets/images/destinations/bali.jpg",
                relative_path="assets/images/destinations/bali.jpg",
                intended_component="destinations_grid",
                subject="Bali - Tropical Temple",
                alt_text="Ulun Danu Bratan",
            ),
        ],
    )
    directive = AssetPipeline.get_asset_directive(manifest)
    assert "assets/images/hero.jpg" in directive
    assert "assets/images/destinations/bali.jpg" in directive
    assert "AUTHORITATIVE PRE-PROVISIONED IMAGE ASSET SPECIFICATION" in directive


# ── Behavior 5: Fallback SVG generation ───────────────────────────────────────
def test_05_fallback_svg_generation():
    svg = AssetPipeline._create_svg_fallback("Swiss Alps", 800, 600, "travel_tourism")
    assert "<svg" in svg
    assert "</svg>" in svg
    assert "Swiss Alps" in svg
    assert 'viewBox="0 0 800 600"' in svg


# ── Behavior 6: DesignBrief contains extended architectural fields ────────────
def test_06_design_brief_extended_fields():
    brief = DesignBriefGenerator.generate_brief("Create a luxury travel website called WanderWorld")
    assert brief.domain == "travel_tourism"
    assert len(brief.brand_positioning) > 10
    assert len(brief.layout_strategy) > 10
    assert "navbar" in brief.component_language
    assert "card" in brief.component_language
    assert len(brief.navigation_strategy) > 5
    assert len(brief.asset_plan_requirements) >= 3


# ── Behavior 7: DesignBrief persists artifacts ────────────────────────────────
def test_07_design_brief_persists_artifacts(temp_workspace):
    brief = DesignBriefGenerator.generate_brief("Artisanal Bakery Cafe website")
    json_path, md_path = brief.persist_artifacts(temp_workspace)
    assert json_path.exists()
    assert md_path.exists()
    assert (temp_workspace / ".hermes" / "design_brief.json").exists()
    assert (temp_workspace / ".artifacts" / "design_brief.md").exists()
    
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["domain"] == "culinary_restaurant"


# ── Behavior 8: DesignBrief compact directive word count and tokens ───────────
def test_08_design_brief_compact_directive_bounded():
    brief = DesignBriefGenerator.generate_brief("WanderWorld holiday vacations")
    directive = brief.to_compact_directive()
    assert len(directive.split()) < 200
    assert "Color Palette:" in directive
    assert "Container max-width:" in directive
    assert "Zero horizontal overflow" in directive


# ── Behavior 9: FrontendContractValidator flags missing local assets ──────────
def test_09_validator_flags_missing_local_assets(temp_workspace):
    (temp_workspace / "index.html").write_text(
        '<img src="assets/images/missing.jpg" alt="test">', encoding="utf-8"
    )
    issues = FrontendContractValidator.validate_local_assets(temp_workspace)
    assert len(issues) >= 1
    assert issues[0]["type"] == "MISSING_LOCAL_ASSET"


# ── Behavior 10: FrontendContractValidator JS selector contracts ──────────────
def test_10_validator_js_selector_contracts():
    html = '<div class="destination-card">Bali</div>'
    js = 'const nonExistent = document.querySelector(".fictional-element");'
    css = '.destination-card { padding: 1rem; }'
    issues = FrontendContractValidator.validate_js_selector_contracts(html, js, css)
    assert len(issues) == 1
    assert issues[0]["class_name"] == "fictional-element"


# ── Behavior 11: FrontendContractValidator flags unstyled critical components ──
def test_11_validator_flags_unstyled_critical_components():
    html = '<header class="navbar"></header><div class="cards-grid"><div class="card"></div></div><footer class="footer"></footer>'
    css = 'body { margin: 0; }'
    issues = FrontendContractValidator.validate_css_classes(html, css)
    types = [i["component"] for i in issues]
    assert "navbar" in types
    assert "card" in types
    assert "grid" in types
    assert "footer" in types


# ── Behavior 12: Category consistency validation ──────────────────────────────
def test_12_validator_category_consistency():
    html = '<div class="filters"><button data-category="beach">Beach</button><button data-category="desert">Desert</button></div>'
    js = 'const items = [{ name: "Bali", category: "beach" }, { name: "Tokyo", category: "culture" }];'
    issues = FrontendContractValidator.validate_category_consistency(html, js)
    assert any(i["category"] == "desert" for i in issues)


# ── Behavior 13: Render target overwrite detection ────────────────────────────
def test_13_validator_render_target_overwrite():
    html = '<section id="destinations"><h2>Featured Destinations</h2><div class="filters"></div></section>'
    js = 'document.getElementById("destinations").innerHTML = "<div>Overwritten</div>";'
    issues = FrontendContractValidator.validate_render_targets(html, js)
    assert len(issues) == 1
    assert issues[0]["type"] == "DANGEROUS_SECTION_OVERWRITE"


# ── Behavior 14: Missing DOM IDs detection ────────────────────────────────────
def test_14_validator_missing_dom_ids():
    html = '<div id="booking-modal"></div>'
    js = 'const form = document.getElementById("booking-form");'
    issues = FrontendContractValidator.validate_dom_ids(html, js)
    assert len(issues) == 1
    assert issues[0]["id"] == "booking-form"


# ── Behavior 15: Full report validation on verified workspace ─────────────────
def test_15_validator_full_report_passed(temp_workspace):
    html = '''<!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><link rel="stylesheet" href="style.css"></head>
    <body>
      <nav class="navbar"><a href="#">WanderWorld</a></nav>
      <section id="hero" class="hero"><h1>WanderWorld</h1></section>
      <section id="destinations">
        <div class="filters"><button data-category="beach">Beach</button></div>
        <div id="destinations-grid" class="cards-grid"></div>
      </section>
      <div id="modal" class="modal"></div>
      <footer class="footer"><p>Copyright 2026</p></footer>
      <script src="app.js"></script>
    </body>
    </html>'''

    css = ''':root { --primary: #0e7490; --bg: #f8fafc; --text: #0f172a; }
    body { margin: 0; overflow-x: hidden; font-family: sans-serif; background: var(--bg); color: var(--text); }
    .navbar { display: flex; padding: 1rem; }
    .hero { min-height: 400px; }
    .cards-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
    .card { border-radius: 12px; }
    .modal { position: fixed; top: 0; left: 0; z-index: 1000; display: none; }
    .footer { padding: 2rem; }
    @media (max-width: 768px) { .cards-grid { grid-template-columns: 1fr; } }'''

    js = '''const grid = document.getElementById("destinations-grid");
    const modal = document.getElementById("modal");
    const items = [{ id: 1, name: "Bali", category: "beach" }];
    grid.innerHTML = items.map(i => `<div class="card">${i.name}</div>`).join("");'''

    (temp_workspace / "index.html").write_text(html, encoding="utf-8")
    (temp_workspace / "style.css").write_text(css, encoding="utf-8")
    (temp_workspace / "app.js").write_text(js, encoding="utf-8")

    validator = FrontendContractValidator(temp_workspace)
    report = validator.validate_all()
    assert report.is_valid is True
    assert len(report.errors) == 0


# ── Behavior 16: Browser QA marks NOT_RUN when evidence unavailable ──────────
def test_16_browser_qa_not_run_when_evidence_unavailable(temp_workspace):
    validator = FrontendContractValidator(temp_workspace)
    qa = validator.verify_browser_visual_qa(temp_workspace, browser_eval_data=None)
    assert qa["passed"] is False
    assert qa["visual_qa_status"] == "NOT_RUN"
    assert qa["functional_qa_status"] == "NOT_RUN"


# ── Behavior 17: Browser QA detects horizontal overflow ───────────────────────
def test_17_browser_qa_detects_horizontal_overflow(temp_workspace):
    validator = FrontendContractValidator(temp_workspace)
    data = {
        "has_horizontal_overflow": True,
        "console_errors": [],
    }
    qa = validator.verify_browser_visual_qa(temp_workspace, browser_eval_data=data)
    assert qa["passed"] is False
    assert qa["checks"]["no_horizontal_overflow"] is False
    assert qa["visual_qa_status"] == "FAIL"


# ── Behavior 18: Browser QA detects broken images ─────────────────────────────
def test_18_browser_qa_detects_broken_images(temp_workspace):
    validator = FrontendContractValidator(temp_workspace)
    data = {
        "images": [{"src": "assets/bali.jpg", "naturalWidth": 0, "complete": True}],
    }
    qa = validator.verify_browser_visual_qa(temp_workspace, browser_eval_data=data)
    assert qa["passed"] is False
    assert qa["checks"]["images_loaded"] is False
    assert qa["functional_qa_status"] == "FAIL"


# ── Behavior 19: Browser QA detects console errors ────────────────────────────
def test_19_browser_qa_detects_console_errors(temp_workspace):
    validator = FrontendContractValidator(temp_workspace)
    data = {
        "console_errors": ["TypeError: Cannot set property 'innerHTML' of null"],
    }
    qa = validator.verify_browser_visual_qa(temp_workspace, browser_eval_data=data)
    assert qa["passed"] is False
    assert qa["checks"]["zero_console_errors"] is False


# ── Behavior 20-23: Skill application evidence evaluation ─────────────────────
def test_20_skill_evidence_taste_design(temp_workspace):
    brief = DesignBriefGenerator.generate_brief("Travel website")
    ev = FrontendContractValidator.evaluate_skill_application_evidence(
        temp_workspace, active_skills=["taste-design"], design_brief=brief
    )
    assert ev["taste-design"]["applied"] is True


def test_21_skill_evidence_design_system(temp_workspace):
    (temp_workspace / "style.css").write_text(
        ":root { --color-primary: #0e7490; --color-bg: #fff; --color-text: #000; }\nbody { color: var(--color-text); }",
        encoding="utf-8",
    )
    ev = FrontendContractValidator.evaluate_skill_application_evidence(
        temp_workspace, active_skills=["design-system"]
    )
    assert ev["design-system"]["applied"] is True


def test_22_skill_evidence_design_engineering(temp_workspace):
    (temp_workspace / "index.html").write_text('<div class="cards-grid"><div class="card"></div></div>', encoding="utf-8")
    (temp_workspace / "style.css").write_text('.cards-grid { display: grid; }', encoding="utf-8")
    ev = FrontendContractValidator.evaluate_skill_application_evidence(
        temp_workspace, active_skills=["design-engineering"]
    )
    assert ev["design-engineering"]["applied"] is True


def test_23_skill_evidence_web_design_guidelines(temp_workspace):
    (temp_workspace / "index.html").write_text('<img src="test.jpg" alt="Description">', encoding="utf-8")
    (temp_workspace / "style.css").write_text('body { overflow-x: hidden; } @media (max-width: 768px) { body { font-size: 14px; } }', encoding="utf-8")
    ev = FrontendContractValidator.evaluate_skill_application_evidence(
        temp_workspace, active_skills=["web-design-guidelines"]
    )
    assert ev["web-design-guidelines"]["applied"] is True


# ── Behavior 24: Profile C fails when contract errors detected ────────────────
def test_24_profile_c_fails_on_contract_errors(temp_workspace):
    # HTML queries #missing-container in JS, which causes contract error
    (temp_workspace / "index.html").write_text(
        "<!DOCTYPE html><html><body><div id='root'></div><script src='app.js'></script></body></html>",
        encoding="utf-8",
    )
    (temp_workspace / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    (temp_workspace / "app.js").write_text(
        "document.getElementById('missing-container').innerHTML = '<p>Fail</p>';",
        encoding="utf-8",
    )
    prompt = "Create a simple web application"
    res = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_C, temp_workspace, prompt, written_files=["index.html", "style.css", "app.js"]
    )
    assert res.passed is False
    assert any("Frontend contract defect" in iss for iss in res.issues)


# ── Behavior 25: Profile C fails when photographic assets missing ─────────────
def test_25_profile_c_fails_when_demanded_photography_missing(temp_workspace):
    # Valid HTML/CSS/JS, but prompt demands travel photography and no image files exist in workspace
    (temp_workspace / "index.html").write_text(
        "<!DOCTYPE html><html><body><h1>WanderWorld</h1><script src='app.js'></script></body></html>",
        encoding="utf-8",
    )
    (temp_workspace / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    (temp_workspace / "app.js").write_text("console.log('WanderWorld ready');", encoding="utf-8")

    prompt = "Create a visually impressive travel agency website called WanderWorld with travel photography hero and destination cards"
    res = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_C, temp_workspace, prompt, written_files=["index.html", "style.css", "app.js"]
    )
    assert res.passed is False
    assert any("Visual asset requirement failed" in iss for iss in res.issues)
