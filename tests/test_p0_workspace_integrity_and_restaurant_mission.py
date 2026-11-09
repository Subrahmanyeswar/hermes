import os
import sys
import shutil
import tempfile
from pathlib import Path
import pytest

from tools.security import (
    gate_16_destructive_workspace_cleanup,
    check_all_gates,
)
from tools.shell_tools import _translate_single_command
from core.design_intelligence import DesignBriefGenerator, ContentCoverageMap
from core.frontend_contract import FrontendContractBuilder
from core.asset_pipeline import AssetPipeline
from core.foundation_scaffolder import seed_initial_foundation_files
from core.work_package_gate import WorkPackageGater


# ------------------------------------------------------------------------------
# 1. GATE 16 & SHELL DESTRUCTIVE CLEANUP PROTECTION TESTS
# ------------------------------------------------------------------------------

def test_gate_16_blocks_destructive_rm_rf():
    """Verify Gate 16 blocks recursive deletion targeting workspace foundation files."""
    bad_cmd = "rm -rf assets images package.json style.css index.html app.js .ar"
    passed, reason = gate_16_destructive_workspace_cleanup(bad_cmd)
    assert not passed, "Gate 16 must reject destructive rm -rf command"
    assert "protected project source deliverables" in reason.lower()

    # Also test through check_all_gates
    passed_all, reason_all = check_all_gates(bad_cmd)
    assert not passed_all
    assert "Gate 16" in reason_all or "Destructive cleanup" in reason_all


def test_gate_16_blocks_wildcard_and_root_deletion():
    """Verify Gate 16 blocks deletion of root or wildcard directory."""
    for cmd in ["rm -rf *", "rm -rf .", "rm -r .", "rmdir /s /q .", "del /s /q *"]:
        passed, reason = gate_16_destructive_workspace_cleanup(cmd)
        assert not passed, f"Gate 16 should block: {cmd}"


def test_gate_16_allows_safe_commands():
    """Verify Gate 16 does not block normal, safe commands."""
    safe_cmds = [
        "ls -la",
        "cat index.html",
        "rm scratch_test.txt",
        "rm -f temp.log",
        "python -m pytest",
        "git status",
    ]
    for cmd in safe_cmds:
        passed, reason = gate_16_destructive_workspace_cleanup(cmd)
        assert passed, f"Gate 16 should allow safe command '{cmd}', but failed: {reason}"


def test_shell_tools_translation_safeguard():
    """Verify shell_tools translation layer blocks rm targeting foundation files."""
    bad_cmd = "rm -rf assets images package.json style.css index.html app.js .ar"
    ps_cmd = _translate_single_command(bad_cmd, py=sys.executable)
    assert "Destructive deletion" in ps_cmd
    assert "126" in ps_cmd


# ------------------------------------------------------------------------------
# 2. DOMAIN DETECTION & COVERAGE MAP TESTS
# ------------------------------------------------------------------------------

def test_restaurant_domain_detection():
    """Verify restaurant prompts are strictly detected as culinary_restaurant."""
    prompts = [
        "Create a Michelin-caliber restaurant website called Saffron & Stone with artisanal Mediterranean dining",
        "Build a high-end bistro website with seasonal menu, chef profile, and reservations",
        "Develop an artisanal culinary dining destination with wood-fired hearth and private cellar",
    ]
    for p in prompts:
        domain = DesignBriefGenerator.detect_domain(p)
        assert domain == "culinary_restaurant", f"Expected culinary_restaurant for '{p}', got {domain}"


def test_restaurant_content_coverage_map():
    """Verify ContentCoverageMap produces all required sections for restaurant domain."""
    prompt = "Build Saffron & Stone artisanal restaurant with menu, chef, ambience, private dining, reservations"
    coverage = ContentCoverageMap.from_prompt(prompt)
    assert coverage.domain == "culinary_restaurant"
    assert "menu" in coverage.sections
    assert "chef" in coverage.sections
    assert "ambience" in coverage.sections
    assert "private_dining" in coverage.sections
    assert "booking" in coverage.sections
    assert len(coverage.required_cards) >= 6


# ------------------------------------------------------------------------------
# 3. FRONTEND CONTRACT TESTS
# ------------------------------------------------------------------------------

def test_restaurant_frontend_contract_generation():
    """Verify FrontendContractBuilder.build_initial_contract builds Saffron & Stone contract."""
    prompt = "Create Saffron & Stone Michelin-caliber restaurant website with Mediterranean cuisine"
    contract = FrontendContractBuilder.build_initial_contract(prompt)
    assert contract.app_name == "Saffron & Stone"
    assert contract.css.design_tokens["--primary-color"] == "#8b3a1a"
    assert contract.css.design_tokens["--accent-gold"] == "#e5982e"

    comp_ids = [c.id for c in contract.components]
    assert "menu" in comp_ids
    assert "chef" in comp_ids
    assert "reservation-modal" in comp_ids
    assert "dish-modal" in comp_ids


# ------------------------------------------------------------------------------
# 4. ASSET PIPELINE TESTS
# ------------------------------------------------------------------------------

def test_restaurant_asset_provisioning():
    """Verify AssetPipeline provisions culinary assets for restaurant prompt."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        manifest = AssetPipeline.provision_assets(
            workspace_root=ws,
            prompt="Saffron & Stone artisanal Mediterranean restaurant",
            domain="culinary_restaurant",
        )
        assert manifest.domain == "culinary_restaurant"
        assert len(manifest.assets) >= 8

        # Verify key image files exist and are decodable
        hero_img = ws / "assets" / "images" / "hero" / "hero-restaurant.jpg"
        assert hero_img.exists()
        assert hero_img.stat().st_size > 1000

        menu_img = ws / "assets" / "images" / "menu" / "saffron-lamb-tagine.jpg"
        assert menu_img.exists()
        assert menu_img.stat().st_size > 1000


# ------------------------------------------------------------------------------
# 5. FOUNDATION SCAFFOLDER & STALE FILE PURGE TESTS
# ------------------------------------------------------------------------------

def test_foundation_scaffolder_restaurant_generation():
    """Verify foundation scaffolder creates complete restaurant application files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        prompt = "Create Saffron & Stone artisanal Mediterranean restaurant website"
        res = seed_initial_foundation_files(workspace_root=ws, prompt=prompt)
        assert res is True

        html_file = ws / "index.html"
        css_file = ws / "style.css"
        js_file = ws / "app.js"
        pkg_file = ws / "package.json"

        assert html_file.exists() and html_file.stat().st_size > 2000
        assert css_file.exists() and css_file.stat().st_size > 2000
        assert js_file.exists() and js_file.stat().st_size > 2000
        assert pkg_file.exists()

        html_text = html_file.read_text(encoding="utf-8")
        assert "Saffron & Stone" in html_text
        assert 'id="menu-grid"' in html_text
        assert 'id="reservation-modal"' in html_text
        assert 'id="dish-modal"' in html_text
        assert "WanderWorld" not in html_text
        assert "NorthStar" not in html_text

        js_text = js_file.read_text(encoding="utf-8")
        assert "DISHES" in js_text
        assert "Saffron Lamb Tagine" in js_text
        assert "openDishDetail" in js_text


def test_foundation_scaffolder_purges_stale_wanderworld_files():
    """Verify deterministic scaffolder purges stale WanderWorld files for restaurant mission."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        # Seed fake stale WanderWorld files
        (ws / "index.html").write_text("<html><body><h1>WanderWorld Travel destinations-grid Bali</h1></body></html>", encoding="utf-8")
        (ws / "style.css").write_text("/* WanderWorld style */", encoding="utf-8")
        (ws / "app.js").write_text("// WanderWorld app", encoding="utf-8")
        (ws / "package.json").write_text('{"name": "wanderworld"}', encoding="utf-8")

        prompt = "Create Saffron & Stone artisanal restaurant website"
        res = seed_initial_foundation_files(workspace_root=ws, prompt=prompt)
        assert res is True

        new_html = (ws / "index.html").read_text(encoding="utf-8")
        assert "Saffron & Stone" in new_html
        assert "WanderWorld" not in new_html
        assert "destinations-grid" not in new_html


# ------------------------------------------------------------------------------
# 6. WORK PACKAGE GATE INTEGRITY & CROSS-CONTAMINATION TESTS
# ------------------------------------------------------------------------------

def test_work_package_gate_passes_clean_restaurant():
    """Verify WorkPackageGater approves the clean seeded restaurant workspace."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        prompt = "Create Saffron & Stone artisanal Mediterranean restaurant"
        brief = DesignBriefGenerator.generate_brief(prompt)
        brief.persist_artifacts(ws)
        contract = FrontendContractBuilder.build_initial_contract(prompt, design_brief=brief)
        contract.save_to_workspace(ws)
        AssetPipeline.provision_assets(workspace_root=ws, prompt=prompt, domain="culinary_restaurant")
        seed_initial_foundation_files(workspace_root=ws, prompt=prompt, contract=contract, design_brief=brief)

        f_res = WorkPackageGater.evaluate_foundation_gate(workspace_root=ws, contract=contract)
        assert f_res.passed, f"Foundation gate failed: {f_res.summary} Blocked by: {f_res.missing_criteria}"

        c_res = WorkPackageGater.evaluate_content_gate(workspace_root=ws, contract=contract)
        assert c_res.passed, f"Content gate failed: {c_res.summary} Blocked by: {c_res.missing_criteria}"

        fn_res = WorkPackageGater.evaluate_functionality_gate(workspace_root=ws, contract=contract)
        assert fn_res.passed, f"Functionality gate failed: {fn_res.summary} Blocked by: {fn_res.missing_criteria}"


def test_work_package_gate_catches_cross_contamination():
    """Verify WorkPackageGater catches foreign WanderWorld artifacts in a restaurant project."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        prompt = "Create Saffron & Stone artisanal Mediterranean restaurant"
        contract = FrontendContractBuilder.build_initial_contract(prompt)
        AssetPipeline.provision_assets(workspace_root=ws, prompt=prompt, domain="culinary_restaurant")
        seed_initial_foundation_files(workspace_root=ws, prompt=prompt, contract=contract)

        # Inject contaminated string into index.html
        html_p = ws / "index.html"
        content = html_p.read_text(encoding="utf-8")
        html_p.write_text(content + "\n<!-- Stale WanderWorld Bali package -->", encoding="utf-8")

        res = WorkPackageGater.evaluate_content_gate(workspace_root=ws, contract=contract)
        assert not res.passed
        assert any("Cross-contamination detected" in err for err in res.missing_criteria)
