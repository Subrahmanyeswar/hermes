# tests/test_p0_5_2_1_content_fidelity.py
"""
HERMES 2.x — P0.5.2.1 Content Fidelity & Factual Integrity Test Suite.
Validates:
1. Exact preservation of all 8 requested catalogue entities without unauthorized substitutions.
2. Rejection of unsupported environmental claims and fabricated metrics (UNSUPPORTED_ENVIRONMENTAL_CLAIM).
3. Rejection of product substitutions (REQUIRED_ENTITY_SUBSTITUTION).
4. Explicit disclosure of illustrative demonstration pricing.
5. Cross-domain regression stability across all benchmark archetypes.
"""

import json
from pathlib import Path
import pytest

from core.design_intelligence import DesignBriefGenerator, detect_brand_name
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

CANONICAL_ENTITIES = [
    "Reclaimed Timber",
    "Recycled Structural Steel",
    "Salvaged Bricks",
    "Recycled Glass Aggregates",
    "Low-Carbon Concrete",
    "Reclaimed Stone",
    "Recycled Insulation",
    "Reclaimed Architectural Fixtures",
]


def test_t1_exact_canonical_entities_synthesized(tmp_path):
    """Test 1: Synthesizer produces exactly the 8 canonical requested entities without substitutions."""
    spec = SemanticDomainSynthesizer.synthesize(VERDANT_LOOP_PROMPT, tmp_path)
    assert len(spec.content_entities) == 8, f"Expected 8 entities, got {len(spec.content_entities)}"
    
    titles = [e.get("title") for e in spec.content_entities]
    for canon in CANONICAL_ENTITIES:
        assert canon in titles, f"Canonical entity '{canon}' not found in synthesized titles: {titles}"

    # Verify no brass hardware or granite paver substitutions exist in titles
    for t in titles:
        assert "brass hardware" not in t.lower(), f"Unauthorized substitution in title: {t}"
        assert "granite paver" not in t.lower(), f"Unauthorized substitution in title: {t}"


def test_t2_gate_rejects_architectural_fixtures_substitution(tmp_path):
    """Test 2: Gate rejects substitution of Reclaimed Architectural Fixtures with Brass Hardware."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)
    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)

    # Render clean first
    UniversalContentRenderer.render(tmp_path, spec)

    # Deliberately substitute Reclaimed Architectural Fixtures with Salvaged Heavy-Duty Brass Hardware
    app_js_path = tmp_path / "app.js"
    js_text = app_js_path.read_text(encoding="utf-8")
    js_text = js_text.replace("Reclaimed Architectural Fixtures", "Salvaged Heavy-Duty Brass Hardware")
    app_js_path.write_text(js_text, encoding="utf-8")

    html_path = tmp_path / "index.html"
    html_text = html_path.read_text(encoding="utf-8")
    html_text = html_text.replace("Reclaimed Architectural Fixtures", "Salvaged Heavy-Duty Brass Hardware")
    html_path.write_text(html_text, encoding="utf-8")

    result = WorkPackageGate.evaluate_content_gate(tmp_path)
    assert result.passed is False
    assert any("REQUIRED_ENTITY_SUBSTITUTION" in m for m in result.missing_criteria)
    assert any("Reclaimed Architectural Fixtures" in m for m in result.missing_criteria)


def test_t3_gate_rejects_reclaimed_stone_substitution(tmp_path):
    """Test 3: Gate rejects substitution of Reclaimed Stone with Granite Pavers."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)
    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)

    UniversalContentRenderer.render(tmp_path, spec)

    app_js_path = tmp_path / "app.js"
    js_text = app_js_path.read_text(encoding="utf-8")
    js_text = js_text.replace("Reclaimed Stone", "Granite Pavers")
    app_js_path.write_text(js_text, encoding="utf-8")

    html_path = tmp_path / "index.html"
    html_text = html_path.read_text(encoding="utf-8")
    html_text = html_text.replace("Reclaimed Stone", "Granite Pavers")
    html_path.write_text(html_text, encoding="utf-8")

    result = WorkPackageGate.evaluate_content_gate(tmp_path)
    assert result.passed is False
    assert any("REQUIRED_ENTITY_SUBSTITUTION" in m for m in result.missing_criteria)
    assert any("Reclaimed Stone" in m for m in result.missing_criteria)


def test_t4_gate_rejects_missing_canonical_entity(tmp_path):
    """Test 4: Gate rejects arbitrary missing canonical product (e.g. Recycled Insulation missing)."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)
    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)

    UniversalContentRenderer.render(tmp_path, spec)

    app_js_path = tmp_path / "app.js"
    js_text = app_js_path.read_text(encoding="utf-8")
    js_text = js_text.replace("Recycled Insulation", "Acoustic Fiberglass Roll")
    app_js_path.write_text(js_text, encoding="utf-8")

    html_path = tmp_path / "index.html"
    html_text = html_path.read_text(encoding="utf-8")
    html_text = html_text.replace("Recycled Insulation", "Acoustic Fiberglass Roll")
    html_path.write_text(html_text, encoding="utf-8")

    result = WorkPackageGate.evaluate_content_gate(tmp_path)
    assert result.passed is False
    assert any("REQUIRED_ENTITY_SUBSTITUTION" in m for m in result.missing_criteria)
    assert any("Recycled Insulation" in m for m in result.missing_criteria)


def test_t5_gate_rejects_unsupported_carbon_reduction_claim(tmp_path):
    """Test 5: Gate rejects unsupported carbon reduction percentages."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)
    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)

    UniversalContentRenderer.render(tmp_path, spec)

    # Poison index.html with fabricated carbon reduction metric
    html_path = tmp_path / "index.html"
    html_text = html_path.read_text(encoding="utf-8")
    html_text = html_text.replace("</body>", "<div class='metric'>99.4% carbon reduction achieved</div></body>")
    html_path.write_text(html_text, encoding="utf-8")

    result = WorkPackageGate.evaluate_content_gate(tmp_path)
    assert result.passed is False
    assert any("UNSUPPORTED_ENVIRONMENTAL_CLAIM" in m for m in result.missing_criteria)


def test_t6_gate_rejects_unsupported_supplier_count(tmp_path):
    """Test 6: Gate rejects unsupported supplier count claims."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)
    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)

    UniversalContentRenderer.render(tmp_path, spec)

    # Poison index.html with fabricated supplier count
    html_path = tmp_path / "index.html"
    html_text = html_path.read_text(encoding="utf-8")
    html_text = html_text.replace("</body>", "<div class='stat'>Over 320+ verified suppliers on the platform</div></body>")
    html_path.write_text(html_text, encoding="utf-8")

    result = WorkPackageGate.evaluate_content_gate(tmp_path)
    assert result.passed is False
    assert any("UNSUPPORTED_ENVIRONMENTAL_CLAIM" in m for m in result.missing_criteria)


def test_t7_gate_rejects_unsupported_diversion_tonnage(tmp_path):
    """Test 7: Gate rejects fabricated diversion tonnages."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)
    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)

    UniversalContentRenderer.render(tmp_path, spec)

    # Poison index.html with fabricated diversion tonnage
    html_path = tmp_path / "index.html"
    html_text = html_path.read_text(encoding="utf-8")
    html_text = html_text.replace("</body>", "<p>48,000+ tonnes diverted from landfill</p></body>")
    html_path.write_text(html_text, encoding="utf-8")

    result = WorkPackageGate.evaluate_content_gate(tmp_path)
    assert result.passed is False
    assert any("UNSUPPORTED_ENVIRONMENTAL_CLAIM" in m for m in result.missing_criteria)


def test_t8_gate_rejects_unverified_certification_claim(tmp_path):
    """Test 8: Gate rejects unverified certification and 100% verified claims."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)
    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)

    UniversalContentRenderer.render(tmp_path, spec)

    # Poison index.html with unverified claim
    html_path = tmp_path / "index.html"
    html_text = html_path.read_text(encoding="utf-8")
    html_text = html_text.replace("</body>", "<span>100% verified reclaimed materials guaranteed</span></body>")
    html_path.write_text(html_text, encoding="utf-8")

    result = WorkPackageGate.evaluate_content_gate(tmp_path)
    assert result.passed is False
    assert any("UNSUPPORTED_ENVIRONMENTAL_CLAIM" in m for m in result.missing_criteria)


def test_t9_illustrative_pricing_disclosure_rendered(tmp_path):
    """Test 9: Verifies that illustrative price disclosures are present in rendered HTML and JS."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)
    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)

    UniversalContentRenderer.render(tmp_path, spec)

    html_text = (tmp_path / "index.html").read_text(encoding="utf-8")
    js_text = (tmp_path / "app.js").read_text(encoding="utf-8")

    # Verify illustrative disclosures
    assert "illustrative" in html_text.lower() or "illustrative" in js_text.lower()
    assert "Unit Price (Illustrative)" in js_text
    assert "Subtotal (Illustrative)" in js_text


def test_t10_clean_verdant_loop_passes_all_gates(tmp_path):
    """Test 10: Clean greenfield VERDANT LOOP generation passes Foundation and Content gates."""
    spec = MissionSpecification.from_prompt(VERDANT_LOOP_PROMPT, tmp_path)
    spec.persist(tmp_path)

    brief = DesignBriefGenerator.generate_brief(spec.user_prompt, spec.business_domain)
    (tmp_path / ".hermes" / "design_brief.json").write_text(json.dumps(brief.to_dict(), indent=2), encoding="utf-8")
    contract = FrontendContractBuilder.build_initial_contract(task=spec.user_prompt, mission_id=spec.mission_id, design_brief=brief)
    (tmp_path / ".hermes" / "frontend_contract.json").write_text(json.dumps(contract.to_dict(), indent=2), encoding="utf-8")

    AssetPipeline.provision_assets(tmp_path, VERDANT_LOOP_PROMPT, spec.business_domain)
    UniversalContentRenderer.render(tmp_path, spec)

    fg = WorkPackageGate.evaluate_foundation_gate(tmp_path, contract=contract, design_brief=brief)
    assert fg.passed is True, f"Foundation gate failed: {fg.missing_criteria}"

    cg = WorkPackageGate.evaluate_content_gate(tmp_path, contract=contract)
    assert cg.passed is True, f"Content gate failed: {cg.missing_criteria}"


def test_t11_cross_domain_regression_benchmarks():
    """Test 11: Cross-domain benchmark regression remains fully intact."""
    test_benchmarks = [
        ("Brand: Saffron & Stone. Contemporary Indian dining celebrating heritage clay oven tandoor cooking and dum biryani.", "Saffron & Stone", "culinary_restaurant"),
        ("NOVA — Cutting-edge consumer electronics brand offering premium smartphones, laptops, audio, smartwatches.", "NOVA", "ecommerce_electronics"),
        ("ATLAS Robotics — Industrial automation company designing autonomous mobile robots and robotic arms.", "ATLAS Robotics", "robotics_automation"),
        ("WanderWorld — Premier luxury travel agency showcasing world-class holiday destinations and curated travel packages.", "WanderWorld", "travel_tourism"),
        ("NorthStar University — World-class educational institution fostering academic excellence and multidisciplinary innovation.", "NorthStar University", "education_institution"),
        ("FORM & FIELD — Independent architecture and interior design studio crafting timeless spaces with sustainable materials.", "FORM & FIELD", "architecture_interior"),
    ]

    for task, expected_brand, expected_domain in test_benchmarks:
        brand = detect_brand_name(task)
        domain = DesignBriefGenerator.detect_domain(task)
        assert brand == expected_brand, f"Brand mismatch for {task}: expected {expected_brand}, got {brand}"
        assert domain == expected_domain, f"Domain mismatch for {task}: expected {expected_domain}, got {domain}"
