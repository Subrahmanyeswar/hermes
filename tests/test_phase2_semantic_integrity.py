# tests/test_phase2_semantic_integrity.py
"""
HERMES 2.x — Phase 2 Semantic Integrity & Anti-Circular Acceptance Verification Suite.
Validates prompt-authoritative brand parsing, domain classification, dynamic deterministic
marketplace synthesis, unified asset paths, and prompt-authoritative work package gates.
"""

import json
from pathlib import Path
import pytest

from core.design_intelligence import (
    DesignBriefGenerator,
    detect_brand_name,
)
from core.semantic_synthesizer import SemanticDomainSynthesizer
from core.asset_pipeline import AssetPipeline
from core.frontend_contract import FrontendContractBuilder
from core.universal_renderer import UniversalContentRenderer
from core.mission_spec import MissionSpecification
from core.work_package_gate import WorkPackageGate


VERDANT_LOOP_PROMPT = """Brand: VERDANT LOOP
Business: Circular Construction Materials Marketplace.
Marketplace connecting construction companies, architects, builders, and material recovery suppliers.
Catalogue: Reclaimed timber, Recycled structural steel, Salvaged bricks, Recycled glass aggregates, Low-carbon concrete, Reclaimed stone, Recycled insulation, Reclaimed architectural fixtures.
Features: Category filters, real-time search, price sorting, quote basket with live subtotal, detail modal, supplier onboarding form."""


def test_t1_verdant_loop_brand_extraction():
    """T1: Verifies prompt-authoritative brand extraction on VERDANT LOOP prompt."""
    b1 = detect_brand_name(VERDANT_LOOP_PROMPT)
    assert b1 == "VERDANT LOOP"

    # Negative blacklist: generic identity phrases must NOT extract "identity"
    b2 = detect_brand_name("Build website with brand identity and high aesthetic")
    assert b2 != "identity"

    b3 = detect_brand_name("1. Professional navigation with brand identity.\n2. Clean layout.")
    assert b3 != "identity"

    # Header and title formats
    b4 = detect_brand_name("Brand Name: VERDANT LOOP\nIndustry: Construction")
    assert b4 == "VERDANT LOOP"

    b5 = detect_brand_name("## Company: VERDANT LOOP\nWebsite for marketplace")
    assert b5 == "VERDANT LOOP"


def test_t2_verdant_loop_domain_detection():
    """T2: Verifies domain detection identifies ecommerce_marketplace, NOT architecture_interior."""
    domain = DesignBriefGenerator.detect_domain(VERDANT_LOOP_PROMPT)
    assert domain == "ecommerce_marketplace"
    assert domain != "architecture_interior"


def test_t3_verdant_loop_archetype_detection():
    """T3: Verifies archetype detection classifies VERDANT LOOP as a marketplace."""
    archetype = DesignBriefGenerator.detect_archetype(VERDANT_LOOP_PROMPT)
    assert archetype == "marketplace"


def test_t4_verdant_loop_semantic_synthesis(tmp_path):
    """T4: Verifies deterministic synthesis for VERDANT LOOP extracts all 8 products and proper assets."""
    payload = SemanticDomainSynthesizer.synthesize(VERDANT_LOOP_PROMPT, tmp_path)

    assert payload.requested_brand == "VERDANT LOOP"
    assert payload.business_domain == "ecommerce_marketplace"
    assert payload.application_archetype == "marketplace"
    assert "Circular Construction Materials Marketplace" in payload.domain_subtype

    # Verify 8 products
    assert len(payload.content_entities) == 8
    categories = {e["category"] for e in payload.content_entities}
    assert "timber" in categories
    assert "steel" in categories
    assert "masonry" in categories
    assert "aggregates" in categories
    assert "concrete" in categories
    assert "insulation" in categories
    assert "fixtures" in categories

    # Verify clean asset paths
    for e in payload.content_entities:
        assert e["image_path"].startswith("assets/images/products/")

    # Verify hero asset
    hero = next(a for a in payload.asset_requirements if a["component"] == "hero")
    assert hero["relative_path"] == "assets/images/hero/hero-materials.jpg"


def test_t5_asset_pipeline_marketplace_provisioning(tmp_path):
    """T5: Verifies AssetPipeline provisions all marketplace assets cleanly on disk."""
    manifest = AssetPipeline.provision_assets(
        workspace_root=tmp_path,
        prompt=VERDANT_LOOP_PROMPT,
        domain="ecommerce_marketplace",
    )
    assert manifest is not None
    assert len(manifest.assets) >= 9

    # Check disk files
    hero_file = tmp_path / "assets" / "images" / "hero" / "hero-materials.jpg"
    assert hero_file.exists()
    assert hero_file.stat().st_size > 0

    expected_products = [
        "timber.jpg", "steel.jpg", "bricks.jpg", "glass-aggregates.jpg",
        "concrete.jpg", "stone.jpg", "insulation.jpg", "fixtures.jpg"
    ]
    for p in expected_products:
        p_file = tmp_path / "assets" / "images" / "products" / p
        assert p_file.exists(), f"Missing provisioned product image: {p}"
        assert p_file.stat().st_size > 0


def test_t6_frontend_contract_marketplace():
    """T6: Verifies FrontendContractBuilder creates the ecommerce_marketplace contract."""
    contract = FrontendContractBuilder.build_initial_contract(
        mission_id="m_test_market",
        task=VERDANT_LOOP_PROMPT,
    )
    assert contract.business_domain == "ecommerce_marketplace"
    assert contract.app_name == "VERDANT LOOP"

    c_ids = [c.id for c in contract.components]
    assert "navbar" in c_ids
    assert "hero" in c_ids
    assert "benefits" in c_ids
    assert "materials" in c_ids
    assert "quote-basket" in c_ids
    assert "onboarding" in c_ids
    assert "sustainability" in c_ids
    assert "contact" in c_ids
    assert "details-modal" in c_ids

    static_ids = contract.dom_and_state.required_static_ids
    assert "quote-basket" in static_ids
    assert "basket-items-list" in static_ids
    assert "basket-subtotal" in static_ids
    assert "price-sort" in static_ids


def test_t7_architecture_hero_asset_path_fix():
    """T7: Verifies architecture hero asset path is unified to assets/images/hero/hero-general.jpg."""
    contract = FrontendContractBuilder.build_initial_contract(
        mission_id="m_arch_test",
        task="Architecture and Interior Design Studio FORM & FIELD",
    )
    hero_item = next(a for a in contract.assets if a.intended_component == "hero")
    assert hero_item.relative_path == "assets/images/hero/hero-general.jpg"
    assert "hero-architecture.jpg" not in hero_item.relative_path


def test_t8_universal_renderer_marketplace(tmp_path):
    """T8: Verifies UniversalContentRenderer generates index.html, style.css, app.js for marketplace."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    ok = UniversalContentRenderer.render(tmp_path, spec)
    assert ok is True

    # index.html checks
    html_text = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "VERDANT LOOP" in html_text
    assert 'id="showcase-search"' in html_text
    assert 'id="price-sort"' in html_text
    assert 'id="quote-basket"' in html_text
    assert 'id="basket-items-list"' in html_text
    assert 'id="basket-subtotal"' in html_text
    assert 'id="details-modal"' in html_text
    assert "Demonstration Mode" in html_text

    # style.css checks
    css_text = (tmp_path / "style.css").read_text(encoding="utf-8")
    assert ".quote-basket" in css_text
    assert ".basket-table" in css_text
    assert ".price-tag" in css_text
    assert ".sort-container" in css_text

    # app.js checks
    js_text = (tmp_path / "app.js").read_text(encoding="utf-8")
    assert "renderBasket" in js_text
    assert "addToBasket" in js_text
    assert "updateQuantity" in js_text
    assert "isMarketplace = true" in js_text

    # package.json checks
    pkg = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert pkg["name"] == "verdant-loop"


def test_t9_anti_circular_gate_rejection_architecture_hijacking(tmp_path):
    """T9: Verifies WorkPackageGate rejects an architecture studio hijack on a marketplace prompt."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)

    # Poison deliverables with architectural studio content
    html_content = """<!DOCTYPE html><html><head><title>identity — Architecture & Interior Design Studio</title></head>
    <body><header id="navbar"><h1>identity</h1></header>
    <section id="hero"><h2>Studio Manifesto</h2></section>
    <section id="philosophy"><h2>Spatial Philosophy & Tectonic Materiality</h2></section>
    <div id="showcase-grid"><article>Cantilever Pavilion Residence</article></div>
    <form id="contact-form">Demonstration Mode</form>
    <script src="app.js"></script></body></html>"""
    (tmp_path / "index.html").write_text(html_content, encoding="utf-8")
    (tmp_path / "style.css").write_text(":root { --primary-color: #000; } body { color: #000; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('Cantilever Pavilion');", encoding="utf-8")

    result = WorkPackageGate.evaluate_content_gate(tmp_path)
    assert result.passed is False
    assert any("CONTENT_DOMAIN_MISMATCH" in m for m in result.missing_criteria)


def test_t10_anti_circular_gate_rejection_brand_corruption(tmp_path):
    """T10: Verifies WorkPackageGate rejects brand corrupted to 'identity'."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)

    html_content = """<!DOCTYPE html><html><head><title>identity</title></head>
    <body><header id="navbar"><h1>identity</h1></header>
    <section id="hero"><h2>Circular Marketplace</h2></section>
    <div id="showcase-grid"><article>Reclaimed timber and steel</article></div>
    <form id="contact-form">Demonstration Mode</form>
    <script src="app.js"></script></body></html>"""
    (tmp_path / "index.html").write_text(html_content, encoding="utf-8")
    (tmp_path / "style.css").write_text(":root { --primary-color: #000; } body { color: #000; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('ready');", encoding="utf-8")

    res_f = WorkPackageGate.evaluate_foundation_gate(tmp_path)
    assert res_f.passed is False
    assert any("identity" in m.lower() for m in res_f.missing_criteria)


def test_t11_gate_rejection_on_missing_local_assets(tmp_path):
    """T11: Verifies WorkPackageGate rejects deliverables referencing nonexistent local assets."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)

    # Provision standard assets first to create manifest
    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)

    # HTML referencing missing local asset (hero-missing.jpg does not exist)
    html_content = """<!DOCTYPE html><html><head><title>VERDANT LOOP</title></head>
    <body><header id="navbar"><h1>VERDANT LOOP</h1></header>
    <section id="hero"><img src="assets/images/hero/hero-missing.jpg" alt="Hero"></section>
    <div id="showcase-grid"><img src="assets/images/products/timber-missing.jpg" alt="Timber"></div>
    <form id="contact-form">Demonstration Mode</form>
    <script src="app.js"></script></body></html>"""
    (tmp_path / "index.html").write_text(html_content, encoding="utf-8")
    (tmp_path / "style.css").write_text(":root { --primary-color: #000; } body { color: #000; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('ready');", encoding="utf-8")

    result = WorkPackageGate.evaluate_content_gate(tmp_path)
    assert result.passed is False
    assert any("MISSING_LOCAL_ASSET" in m for m in result.missing_criteria)


def test_t12_gate_acceptance_on_valid_verdant_loop(tmp_path):
    """T12: End-to-end Greenfield qualification: full pipeline on VERDANT LOOP passes all gates."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)

    # Persist DesignBrief and FrontendImplementationContract into .hermes/
    brief = DesignBriefGenerator.generate_brief(spec.user_prompt, spec.business_domain)
    (tmp_path / ".hermes" / "design_brief.json").write_text(json.dumps(brief.to_dict(), indent=2), encoding="utf-8")
    contract = FrontendContractBuilder.build_initial_contract(task=spec.user_prompt, mission_id=spec.mission_id, design_brief=brief)
    (tmp_path / ".hermes" / "frontend_contract.json").write_text(json.dumps(contract.to_dict(), indent=2), encoding="utf-8")

    # Provision genuine assets
    manifest = AssetPipeline.provision_assets(
        workspace_root=tmp_path,
        prompt=VERDANT_LOOP_PROMPT,
        domain=spec.business_domain,
    )
    assert manifest is not None

    # Render deliverables
    ok = UniversalContentRenderer.render(tmp_path, spec)
    assert ok is True

    # Evaluate Foundation Gate
    res_f = WorkPackageGate.evaluate_foundation_gate(tmp_path, contract=contract, design_brief=brief)
    assert res_f.passed is True, f"Foundation gate failed: {res_f.missing_criteria}"

    # Evaluate Content Gate
    res_c = WorkPackageGate.evaluate_content_gate(tmp_path, contract=contract)
    assert res_c.passed is True, f"Content gate failed: {res_c.missing_criteria}"


def test_t13_regression_saffron_and_stone():
    """T13: Cross-domain regression: Saffron & Stone contemporary Indian restaurant."""
    p = "Brand: Saffron & Stone. Contemporary Indian dining celebrating heritage clay oven tandoor cooking and dum biryani."
    assert detect_brand_name(p) == "Saffron & Stone"
    assert DesignBriefGenerator.detect_domain(p) == "culinary_restaurant"
    assert DesignBriefGenerator.detect_cuisine_subtype(p) == "Contemporary Indian"


def test_t14_regression_nova_electronics():
    """T14: Cross-domain regression: NOVA consumer electronics."""
    p = "NOVA — Cutting-edge consumer electronics brand offering premium smartphones, laptops, audio, smartwatches."
    assert detect_brand_name(p) == "NOVA"
    assert DesignBriefGenerator.detect_domain(p) == "ecommerce_electronics"


def test_t15_regression_atlas_robotics():
    """T15: Cross-domain regression: ATLAS Robotics industrial automation."""
    p = "ATLAS Robotics — Industrial automation company designing autonomous mobile robots and robotic arms."
    assert detect_brand_name(p) == "ATLAS Robotics"
    assert DesignBriefGenerator.detect_domain(p) == "robotics_automation"


def test_t16_regression_wanderworld_tourism():
    """T16: Cross-domain regression: WanderWorld luxury travel agency."""
    p = "WanderWorld — Premier luxury travel agency showcasing world-class holiday destinations and curated travel packages."
    assert detect_brand_name(p) == "WanderWorld"
    assert DesignBriefGenerator.detect_domain(p) == "travel_tourism"


def test_t17_regression_northstar_university():
    """T17: Cross-domain regression: NorthStar University higher education."""
    p = "NorthStar University — World-class educational institution fostering academic excellence and multidisciplinary innovation."
    assert detect_brand_name(p) == "NorthStar University"
    assert DesignBriefGenerator.detect_domain(p) == "education_institution"


def test_t18_regression_form_and_field_architecture():
    """T18: Cross-domain regression: FORM & FIELD architecture studio."""
    p = "FORM & FIELD — Independent architecture and interior design studio crafting timeless spaces with sustainable materials."
    assert detect_brand_name(p) == "FORM & FIELD"
    assert DesignBriefGenerator.detect_domain(p) == "architecture_interior"
    assert DesignBriefGenerator.detect_archetype(p) == "portfolio_studio"
