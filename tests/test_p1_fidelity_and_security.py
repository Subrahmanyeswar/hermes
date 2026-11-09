"""
HERMES 2.x — P1 Final Restaurant Fidelity & Workspace Security Regression Test Suite.

Validates:
1. Independent identification of business domain and Indian cuisine subtype.
2. Content fidelity: Indian cuisine preserved through contract generation without Mediterranean substitution.
3. Authentic Indian menu items (paneer tikka, dum biryani, tandoori salmon, etc.) and no invented Michelin credentials.
4. Workspace ownership manifest: user-owned files survive domain switching.
5. Gate 16 protection on internal Python file operations (can_safely_delete_file, safe_delete_file, safe_rmtree).
6. Safe deletion of verified temporary artifacts while strictly shielding deliverables.
7. Responsive tablet navigation alignment (1024px single-line balance).
"""

import json
import shutil
import tempfile
from pathlib import Path
import pytest

from core.design_intelligence import (
    DesignBriefGenerator,
    detect_cuisine_subtype,
    ContentCoverageMap,
)
from core.frontend_contract import build_initial_contract
from core.foundation_scaffolder import seed_initial_foundation_files
from tools.security import (
    WorkspaceOwnershipManifest,
    can_safely_delete_file,
    safe_delete_file,
    safe_rmtree,
    gate_16_destructive_workspace_cleanup,
)
from tools.file_tools import DeleteFileTool


class TestCuisineAndDomainFidelity:
    """Tests ensuring business domain and cuisine subtype are independently resolved and preserved."""

    def test_domain_and_cuisine_separately_identified(self):
        prompt = "Create a modern luxury website for Saffron & Stone — Contemporary Indian Kitchen with private dining."
        domain = DesignBriefGenerator.detect_domain(prompt)
        cuisine = detect_cuisine_subtype(prompt)

        assert domain == "culinary_restaurant", f"Expected culinary_restaurant, got {domain}"
        assert cuisine == "Contemporary Indian", f"Expected Contemporary Indian, got {cuisine}"

    def test_mediterranean_cuisine_not_substituted(self):
        prompt = "Saffron & Stone — Contemporary Indian Kitchen. Tandoori specialities and dum biryani."
        brief = DesignBriefGenerator.generate_brief(prompt)

        assert brief.domain == "culinary_restaurant"
        assert brief.cuisine_subtype == "Contemporary Indian"
        assert "Mediterranean" not in brief.brand_identity
        assert "Mediterranean" not in brief.visual_direction
        assert (
            "Indian" in brief.target_audience
            or "Indian" in brief.visual_direction
            or "Indian" in brief.brand_personality
        )

    def test_contract_preserves_indian_cuisine_and_positioning(self):
        prompt = "Saffron & Stone — Contemporary Indian Kitchen. Rich spices, clay oven cooking, warm hospitality."
        contract = build_initial_contract(prompt)

        assert contract.business_domain == "culinary_restaurant"
        assert contract.cuisine_subtype == "Contemporary Indian"
        assert "Indian" in contract.brand_positioning
        assert "Contemporary Indian" in contract.brand_positioning
        assert "Mediterranean" not in contract.brand_positioning

    def test_coverage_map_requires_authentic_indian_menu(self):
        prompt = "Saffron & Stone — Contemporary Indian Kitchen"
        coverage = ContentCoverageMap.from_prompt(prompt)

        # Indian authentic dishes present
        assert any("paneer" in item.lower() for item in coverage.required_cards), "Paneer not found"
        assert any("biryani" in item.lower() for item in coverage.required_cards), "Biryani not found"
        assert any("tandoori" in item.lower() for item in coverage.required_cards), "Tandoori not found"
        assert any("naan" in item.lower() or "kulcha" in item.lower() for item in coverage.required_cards), "Indian breads not found"
        assert any("kulfi" in item.lower() or "gulab jamun" in item.lower() for item in coverage.required_cards), "Traditional dessert not found"

        # Mediterranean items must NOT be present
        assert not any("tagine" in item.lower() for item in coverage.required_cards), "Tagine should not be present"
        assert not any("mezze" in item.lower() for item in coverage.required_cards), "Mezze should not be present"
        assert not any("baklava" in item.lower() for item in coverage.required_cards), "Baklava should not be present"

    def test_no_invented_michelin_claims_in_scaffolder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            prompt = "Saffron & Stone — Contemporary Indian Kitchen"
            seed_initial_foundation_files(ws, prompt)

            index_html = (ws / "index.html").read_text(encoding="utf-8")
            style_css = (ws / "style.css").read_text(encoding="utf-8")
            app_js = (ws / "app.js").read_text(encoding="utf-8")

            # Check no fake Michelin star mentions
            assert "Michelin" not in index_html, "Invented Michelin star found in index.html"
            assert "Michelin" not in app_js, "Invented Michelin star found in app.js"

            # Check authentic Indian cuisine items in markup
            assert "Contemporary Indian Kitchen" in index_html
            assert "Dum Biryani" in index_html or "dum biryani" in index_html.lower()
            assert "Paneer Tikka" in index_html or "paneer" in index_html.lower()
            assert "Tandoori" in index_html or "tandoori" in index_html.lower()

            # Check tablet navigation refinement at 1024px in style.css
            assert "@media (max-width: 1024px)" in style_css
            assert "white-space: nowrap" in style_css


class TestWorkspaceSecurityAndOwnershipManifest:
    """Tests ensuring internal Python deletion paths respect Gate 16 and protect user files."""

    def test_user_owned_files_not_deleted_on_domain_switch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)

            # User manually creates an existing index.html and style.css
            user_html = ws / "index.html"
            user_html.write_text("<!DOCTYPE html><html><body>User Custom Project</body></html>", encoding="utf-8")
            user_css = ws / "style.css"
            user_css.write_text("/* User Custom Styles */", encoding="utf-8")

            # No manifest exists yet (it's user-owned)
            assert not WorkspaceOwnershipManifest.is_generated_file(user_html, ws)

            # Attempt deletion via safe_delete_file
            can_del, reason = can_safely_delete_file(user_html, ws)
            assert not can_del
            assert "user-owned" in reason.lower() or "not recorded" in reason.lower()

            del_ok = safe_delete_file(user_html, ws)
            assert not del_ok
            assert user_html.exists(), "User-owned index.html was deleted!"

    def test_registered_generated_files_can_be_safely_purged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)

            gen_file = ws / "index.html"
            gen_file.write_text("<h1>Generated Content</h1>", encoding="utf-8")

            # Register as generated by HERMES
            WorkspaceOwnershipManifest.register_generated_files(ws, [gen_file], source="foundation_scaffolder")
            assert WorkspaceOwnershipManifest.is_generated_file(gen_file, ws)

            # Deletion without explicit regeneration authorization is blocked
            can_del_unauth, _ = can_safely_delete_file(gen_file, ws)
            assert not can_del_unauth

            # Deletion WITH explicit regeneration authorization succeeds
            can_del, reason = can_safely_delete_file(gen_file, ws, reason="explicit_regeneration")
            assert can_del
            del_ok = safe_delete_file(gen_file, ws, reason="explicit_regeneration")
            assert del_ok
            assert not gen_file.exists()

    def test_verified_temp_files_allowed_for_deletion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)

            temp_f = ws / ".hermes" / "tmp" / "temp_preview.html"
            temp_f.parent.mkdir(parents=True, exist_ok=True)
            temp_f.write_text("<html>temp</html>", encoding="utf-8")

            can_del, _ = can_safely_delete_file(temp_f, ws)
            assert can_del
            del_ok = safe_delete_file(temp_f, ws)
            assert del_ok
            assert not temp_f.exists()

    def test_safe_rmtree_blocks_workspace_root_and_source_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)

            # Workspace root
            ok = safe_rmtree(ws, ws)
            assert not ok

            # Protected directories like images / assets
            assets_dir = ws / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            ok = safe_rmtree(assets_dir, ws)
            assert not ok

            # Temporary directory can be rmtree'd
            tmp_sub = ws / ".hermes" / "tmp" / "run_123"
            tmp_sub.mkdir(parents=True, exist_ok=True)
            (tmp_sub / "dummy.txt").write_text("dummy", encoding="utf-8")

            ok = safe_rmtree(tmp_sub, ws)
            assert ok
            assert not tmp_sub.exists()

    def test_delete_file_tool_respects_ownership(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)

            user_file = ws / "app.js"
            user_file.write_text("console.log('user code');", encoding="utf-8")

            tool = DeleteFileTool()
            res = tool.execute(DeleteFileTool.Input(path=str(user_file), confirm=True))

            assert res.exit_code == 126
            err = (res.error or res.output).lower()
            assert "gate" in err or "blocked" in err or "security" in err
            assert user_file.exists()
