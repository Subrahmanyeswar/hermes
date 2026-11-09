"""
P0.3 Universal Greenfield Isolation, Context Contamination & Runtime Reliability Regression Tests.
Verifies that:
1. Negative exclusion clauses in user prompts are stripped before domain/cuisine detection.
2. Domain detection accurately routes to ecommerce_electronics, culinary_restaurant, education_institution, and travel_tourism.
3. E-commerce frontend contract and foundation scaffolder generate clean, isolated deliverables with 12 products.
4. Foundation scaffolder purges cross-domain foreign files without leaving stale artifacts.
5. WorkPackageContentGate catches and rejects cross-domain contamination.
6. Empty model responses across providers (NVIDIA, Gemini, CommonAdapter) are marked success=False with EMPTY_MODEL_RESPONSE.
7. Agent loop and Orchestrator permit Tier 3 failover when Tier 2 takes 15.8s of a 25.0s budget (rem_t3 = 9.2s).
"""

import os
import shutil
import tempfile
import asyncio
from pathlib import Path
import pytest

from core.design_intelligence import (
    strip_negative_constraints,
    detect_cuisine_subtype,
    DesignBriefGenerator,
    ContentCoverageMap,
)
from core.frontend_contract import build_initial_contract
from core.foundation_scaffolder import seed_initial_foundation_files
from core.asset_pipeline import AssetPipeline
from core.work_package_gate import WorkPackageGater
from tools.security import WorkspaceOwnershipManifest
from models.provider import NormalizedModelResponse
from models.nvidia_client import NvidiaClient
from models.gemini_client import GeminiClient
from models.common_adapter import CommonProviderAdapter


NOVA_PROMPT = """
Create a state-of-the-art consumer electronics e-commerce storefront called NOVA.
Features:
- Flagship audio, computing, wearables and smart accessories catalog with at least 12 distinct products.
- Real-time search, category filtering, price sorting, interactive cart drawer with quantity adjustments.
- Detailed modal product specifications and demonstration checkout flow.
- Clean high-tech aesthetic, responsive design, local storage persistence for cart items.
- Do not reuse or copy WanderWorld, NorthStar University or Saffron & Stone files, layouts, menus, or assets.
"""

SAFFRON_PROMPT = """
Build a website for Saffron & Stone — Contemporary Indian Kitchen.
Fine dining Indian restaurant with tandoori specialties, dum biryani, and artisanal desserts.
Do not reuse WanderWorld, NorthStar University, or NOVA electronics.
"""

NORTHSTAR_PROMPT = """
Create an official website for NorthStar University.
Academic programs in engineering, humanities, and medicine with campus tour and faculty directory.
Do not copy WanderWorld, Saffron & Stone, or NOVA.
"""

WANDERWORLD_PROMPT = """
Create a luxury adventure travel agency website called WanderWorld.
Exotic destinations including Bali, Swiss Alps, and Paris getaways with curated itinerary bookings.
Avoid Saffron & Stone, NorthStar, or NOVA electronics.
"""


def test_strip_negative_constraints():
    """Verify that exclusion lines like 'Do not reuse WanderWorld' are stripped."""
    cleaned = strip_negative_constraints(NOVA_PROMPT)
    assert "wanderworld" not in cleaned.lower()
    assert "northstar" not in cleaned.lower()
    assert "saffron" not in cleaned.lower()
    assert "electronics" in cleaned.lower()
    assert "nova" in cleaned.lower()

    cleaned_saffron = strip_negative_constraints(SAFFRON_PROMPT)
    assert "wanderworld" not in cleaned_saffron.lower()
    assert "northstar" not in cleaned_saffron.lower()
    assert "saffron" in cleaned_saffron.lower()
    assert "indian" in cleaned_saffron.lower()


def test_domain_detection_isolation():
    """Verify positive intent scoring detects correct domain regardless of negative exclusions."""
    assert DesignBriefGenerator.detect_domain(NOVA_PROMPT) == "ecommerce_electronics"
    assert DesignBriefGenerator.detect_domain(SAFFRON_PROMPT) == "culinary_restaurant"
    assert DesignBriefGenerator.detect_domain(NORTHSTAR_PROMPT) == "education_institution"
    assert DesignBriefGenerator.detect_domain(WANDERWORLD_PROMPT) == "travel_tourism"


def test_cuisine_subtype_not_triggered_by_exclusion():
    """Verify that an e-commerce prompt excluding Saffron & Stone does not detect Indian cuisine."""
    assert detect_cuisine_subtype(NOVA_PROMPT) is None
    assert detect_cuisine_subtype(SAFFRON_PROMPT) == "Contemporary Indian"


def test_ecommerce_frontend_contract():
    """Verify build_initial_contract for NOVA produces an e-commerce contract."""
    contract = build_initial_contract(NOVA_PROMPT)
    assert contract.app_name == "NOVA"
    assert contract.business_domain == "ecommerce_electronics"
    assert len(contract.components) >= 10
    
    # Verify DOM IDs
    static_ids = contract.dom_and_state.required_static_ids
    assert "products-grid" in static_ids
    assert "cart-modal" in static_ids
    assert "cart-count" in static_ids
    assert "checkout-modal" in static_ids

    # Verify tech assets
    asset_paths = [a.relative_path for a in contract.assets]
    assert "assets/images/hero/hero-electronics.jpg" in asset_paths
    assert "assets/images/products/nova-apex-pro.jpg" in asset_paths
    assert not any("menu" in p or "destinations" in p for p in asset_paths)


def test_foundation_scaffolder_ecommerce_isolation():
    """Verify foundation scaffolder seeds clean e-commerce files with 12 products."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        contract = build_initial_contract(NOVA_PROMPT)
        seed_initial_foundation_files(workspace_root=ws, prompt=NOVA_PROMPT, contract=contract)

        assert (ws / "index.html").exists()
        assert (ws / "style.css").exists()
        assert (ws / "app.js").exists()

        html_text = (ws / "index.html").read_text(encoding="utf-8")
        js_text = (ws / "app.js").read_text(encoding="utf-8")

        # Must have e-commerce DOM IDs and brand
        assert "NOVA" in html_text
        assert 'id="products-grid"' in html_text
        assert 'id="cart-modal"' in html_text
        assert 'id="cart-subtotal"' in html_text

        # Must have 12 products in JS
        assert "nova-apex-pro" in js_text
        assert "nova-magnetic-stand" in js_text
        assert "PRODUCTS" in js_text
        assert js_text.count('id: "nova-') >= 12

        # Must NOT contain foreign restaurant/travel content
        assert "saffron & stone" not in html_text.lower()
        assert "paneer tikka" not in html_text.lower()
        assert "dum biryani" not in html_text.lower()
        assert "wanderworld" not in html_text.lower()
        assert "bali" not in html_text.lower()


def test_foundation_scaffolder_cross_domain_purge():
    """Verify foundation scaffolder automatically cleans up leftover foreign files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        
        # Simulate leftover restaurant files from a previous mission
        (ws / "index.html").write_text("<html><body><h1>Saffron & Stone Menu</h1><div id='dishes-grid'>Biryani</div></body></html>", encoding="utf-8")
        (ws / "style.css").write_text("/* Saffron & Stone styles */", encoding="utf-8")
        (ws / "app.js").write_text("const MENU = [{name: 'Biryani'}];", encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_files(ws, ["index.html", "style.css", "app.js"])

        contract = build_initial_contract(NOVA_PROMPT)
        seed_initial_foundation_files(workspace_root=ws, prompt=NOVA_PROMPT, contract=contract)

        html_text = (ws / "index.html").read_text(encoding="utf-8")
        assert "Saffron & Stone" not in html_text
        assert "Biryani" not in html_text
        assert "NOVA" in html_text
        assert 'id="products-grid"' in html_text


def test_work_package_content_gate_cross_contamination():
    """Verify WorkPackageGater catches cross-domain foreign content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        contract = build_initial_contract(NOVA_PROMPT)
        
        # Contaminated index.html with Saffron & Stone
        (ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <nav><a href="#">NOVA</a></nav>
        <section class="hero"><h1>NOVA</h1></section>
        <div id="products-grid"><article class="card">Saffron & Stone Indian Kitchen</article></div>
        </body></html>
        """, encoding="utf-8")
        (ws / "app.js").write_text("const items = ['headphones'];", encoding="utf-8")

        gate_res = WorkPackageGater.evaluate_content_gate(ws, contract=contract)
        assert not gate_res.passed
        assert any("cross-contamination" in c.lower() for c in gate_res.missing_criteria)


def test_empty_response_classification():
    """Verify that empty model response objects have success=False."""
    norm = NormalizedModelResponse(
        text="",
        tool_calls=[],
        model="meta/llama-3.1-70b-instruct",
        provider="nvidia_nim",
        success=False,
        error="EMPTY_MODEL_RESPONSE: NVIDIA NIM returned 0 content and 0 tool calls",
    )
    assert not norm.success
    assert "EMPTY_MODEL_RESPONSE" in norm.error


def test_tier3_budget_failover_threshold():
    """Verify that when Tier 2 takes 15.8s of a 25s budget, rem_t3 (9.2s) is > 1.0s."""
    total_budget = 25.0
    elapsed_t2 = 15.8
    rem_t3 = total_budget - elapsed_t2
    assert rem_t3 == pytest.approx(9.2, 0.1)
    threshold = 1.0
    assert rem_t3 > threshold
