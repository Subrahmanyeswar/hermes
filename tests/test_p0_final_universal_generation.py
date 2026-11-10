# tests/test_p0_final_universal_generation.py
"""
P0 Final Universal Greenfield Generation & Architectural Reliability Regression Suite.
Validates universal prompt-driven generation, cross-domain isolation, generic marker rejection,
residual ledger gating, dynamic asset provisioning, tool execution reliability, and mission specs.
"""

import json
import shutil
from pathlib import Path
import pytest

from core.design_intelligence import DesignBriefGenerator, detect_brand_name, extract_prompt_color_palette
from core.frontend_contract import FrontendContractBuilder
from core.foundation_scaffolder import seed_initial_foundation_files
from core.work_package_gate import WorkPackageGater
from core.asset_pipeline import AssetPipeline
from core.mission_spec import MissionSpecification
from tools.shell_tools import BashExecTool
from tools.file_tools import ReadFileTool


@pytest.fixture
def temp_ws(tmp_path):
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    yield ws
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)


def test_universal_brand_and_domain_fidelity():
    """Verify exact brand and domain extraction across diverse industries."""
    prompts_and_expectations = [
        (
            "# Mission: Build FORM & FIELD — Premium Architecture and Interior Design Studio Website\n"
            "A fictional website for an independent architecture and interior design studio called **FORM & FIELD**.",
            "FORM & FIELD",
            "architecture_interior",
        ),
        (
            "Build Paws & Claws Veterinary Clinic — Comprehensive Pet Care Website\n"
            "A fictional clinic called **Paws & Claws Veterinary Clinic**.",
            "Paws & Claws Veterinary Clinic",
            "veterinary_pet_care",
        ),
        (
            "# Mission: Build NOVA — Premium Consumer Electronics",
            "NOVA",
            "ecommerce_electronics",
        ),
        (
            "Build ATLAS Robotics — Industrial Automation & Robotics Company",
            "ATLAS Robotics",
            "robotics_automation",
        ),
        (
            "Build Saffron & Stone — Contemporary Indian Dining",
            "Saffron & Stone",
            "culinary_restaurant",
        ),
        (
            "Build NorthStar University — Higher Education and Research",
            "NorthStar University",
            "education_institution",
        ),
        (
            "Build WanderWorld — Luxury Experiential Travel Agency",
            "WanderWorld",
            "travel_tourism",
        ),
        (
            "Build a web portal for BioSynth Marine Genetics. Researching marine coral resilience.",
            "BioSynth Marine Genetics",
            "modern_editorial",  # dynamic general domain
        ),
    ]

    for p, exp_brand, exp_domain in prompts_and_expectations:
        brand = detect_brand_name(p)
        domain = DesignBriefGenerator.detect_domain(p)
        assert exp_brand in brand, f"Brand mismatch for {p}: got {brand!r}, expected {exp_brand!r}"
        assert domain == exp_domain, f"Domain mismatch for {p}: got {domain!r}, expected {exp_domain!r}"


def test_prompt_custom_color_palette_extraction():
    """Verify prompt color keywords are accurately converted to hex tokens."""
    prompt = "Visual Direction: Warm ivory, charcoal, and muted olive color palette."
    tokens = extract_prompt_color_palette(prompt)
    assert tokens.get("primary") == "#1c1d21"  # charcoal
    assert tokens.get("background") == "#fbf9f5"  # warm ivory
    assert tokens.get("accent") == "#556b2f"  # muted olive


def test_architecture_studio_greenfield_scaffolding(temp_ws):
    """Verify FORM & FIELD architecture studio produces complete, prompt-aligned deliverables."""
    prompt = """# Mission: Build FORM & FIELD — Premium Architecture and Interior Design Studio Website
A fictional website for an independent architecture and interior design studio called **FORM & FIELD**.
Visual Direction: Warm ivory, charcoal, and muted olive color palette.
Sections:
- Hero
- Portfolio with 6 architectural projects
- Sustainable design philosophy
- Consultation booking form
"""
    brief = DesignBriefGenerator.generate_brief(prompt)
    contract = FrontendContractBuilder.build_initial_contract(prompt, "m_arch_test", design_brief=brief)

    assert contract.app_name == "FORM & FIELD"
    assert contract.business_domain == "architecture_interior"
    assert contract.css.design_tokens.get("--primary-color") == "#1c1d21"
    assert contract.css.design_tokens.get("--bg-main") == "#fbf9f5"

    seeded = seed_initial_foundation_files(temp_ws, prompt, contract, brief)
    assert seeded is True

    # Check files exist
    assert (temp_ws / "package.json").exists()
    assert (temp_ws / "index.html").exists()
    assert (temp_ws / "style.css").exists()
    assert (temp_ws / "app.js").exists()

    # Verify zero generic placeholders
    html = (temp_ws / "index.html").read_text(encoding="utf-8")
    js = (temp_ws / "app.js").read_text(encoding="utf-8")
    pkg = json.loads((temp_ws / "package.json").read_text(encoding="utf-8"))

    assert "Modern Web Application" not in html
    assert "console.log('App ready');" not in js
    assert pkg["name"] == "form-and-field"
    assert "FORM & FIELD" in html

    # Verify gate evaluations
    res_f = WorkPackageGater.evaluate_foundation_gate(temp_ws, contract, brief)
    res_c = WorkPackageGater.evaluate_content_gate(temp_ws, contract)
    assert res_f.passed is True, f"Foundation failed: {res_f.missing_criteria}"
    assert res_c.passed is True, f"Content failed: {res_c.missing_criteria}"


def test_generic_placeholder_strict_rejection(temp_ws):
    """Verify work package gates reject uncustomized template stubs."""
    (temp_ws / ".hermes").mkdir(exist_ok=True)
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><head><title>Modern Web Application</title></head><body><h1>Welcome to Modern Application</h1></body></html>", encoding="utf-8")
    (temp_ws / "style.css").write_text(":root { --primary: #000; } body { margin: 0; }", encoding="utf-8")
    (temp_ws / "app.js").write_text("console.log('App ready');", encoding="utf-8")
    (temp_ws / "package.json").write_text('{"name": "modern-web-app", "version": "1.0.0"}', encoding="utf-8")

    contract = FrontendContractBuilder.build_initial_contract("Build FORM & FIELD studio", "m_stub", None)

    res_f = WorkPackageGater.evaluate_foundation_gate(temp_ws, contract, None)
    res_c = WorkPackageGater.evaluate_content_gate(temp_ws, contract)

    assert res_f.passed is False
    assert any("Modern Web Application" in m for m in res_f.missing_criteria)
    assert any("console.log('App ready');" in m for m in res_f.missing_criteria)

    assert res_c.passed is False
    assert any("Modern Web Application" in m for m in res_c.missing_criteria)


def test_sequential_cross_domain_isolation(tmp_path):
    """Verify consecutive missions across completely different industries remain 100% isolated."""
    ws_nova = tmp_path / "ws_nova"
    ws_arch = tmp_path / "ws_arch"
    ws_vet = tmp_path / "ws_vet"

    # Mission 1: NOVA Electronics
    prompt_nova = "# Mission: Build NOVA — Premium Consumer Electronics"
    brief_nova = DesignBriefGenerator.generate_brief(prompt_nova)
    contract_nova = FrontendContractBuilder.build_initial_contract(prompt_nova, "m_nova", brief_nova)
    seed_initial_foundation_files(ws_nova, prompt_nova, contract_nova, brief_nova)

    html_nova = (ws_nova / "index.html").read_text(encoding="utf-8")
    assert "NOVA" in html_nova
    assert "FORM & FIELD" not in html_nova
    assert "Paws & Claws" not in html_nova

    # Mission 2: Architecture Studio immediately following
    prompt_arch = "# Mission: Build FORM & FIELD — Premium Architecture and Interior Design Studio Website"
    brief_arch = DesignBriefGenerator.generate_brief(prompt_arch)
    contract_arch = FrontendContractBuilder.build_initial_contract(prompt_arch, "m_arch", brief_arch)
    seed_initial_foundation_files(ws_arch, prompt_arch, contract_arch, brief_arch)

    html_arch = (ws_arch / "index.html").read_text(encoding="utf-8")
    assert "FORM & FIELD" in html_arch
    assert "NOVA" not in html_arch
    assert "smartphones" not in html_arch.lower()
    assert "laptops" not in html_arch.lower()
    assert "saffron" not in html_arch.lower()

    # Mission 3: Veterinary Clinic immediately following
    prompt_vet = "Build Paws & Claws Veterinary Clinic — Comprehensive Pet Care Website"
    brief_vet = DesignBriefGenerator.generate_brief(prompt_vet)
    contract_vet = FrontendContractBuilder.build_initial_contract(prompt_vet, "m_vet", brief_vet)
    seed_initial_foundation_files(ws_vet, prompt_vet, contract_vet, brief_vet)

    html_vet = (ws_vet / "index.html").read_text(encoding="utf-8")
    assert "Paws & Claws" in html_vet
    assert "FORM & FIELD" not in html_vet
    assert "NOVA" not in html_vet
    assert "monolith pavilion" not in html_vet.lower()


def test_asset_pipeline_architecture_provisioning(temp_ws):
    """Verify AssetPipeline provisions verified photography for architecture studio."""
    manifest = AssetPipeline.provision_assets(
        workspace_root=temp_ws,
        prompt="# Mission: Build FORM & FIELD — Premium Architecture and Interior Design Studio Website",
        domain="architecture_interior",
        mission_id="m_arch_asset_test"
    )

    assert len(manifest.assets) >= 7
    for asset in manifest.assets:
        p = temp_ws / asset.relative_path
        assert p.exists()
        assert p.stat().st_size > 5000
        assert asset.status in ("PHOTOGRAPH_VERIFIED", "OTHER_IMAGE_VERIFIED")


def test_tool_dir_command_execution():
    """Verify Windows dir command execution translates cleanly and exits 0."""
    tool = BashExecTool()
    res = tool.execute(tool.Input(command="dir"))
    assert res.success is True
    assert res.exit_code == 0
    assert "index.html" in res.output or "core" in res.output or ".git" in res.output


def test_read_file_directory_handling(temp_ws):
    """Verify read_file on a directory returns structured details without crashing."""
    tool = ReadFileTool()
    sub_dir = temp_ws / "test_folder"
    sub_dir.mkdir(parents=True, exist_ok=True)

    res = tool.execute(tool.Input(path=str(sub_dir)))
    assert res.success is False
    assert res.exit_code == 1
    assert "is a directory" in res.error.lower()
    assert res.details.get("code") == "PATH_IS_DIRECTORY"


def test_mission_specification_lifecycle(temp_ws):
    """Verify MissionSpecification creation, persistence, and loading."""
    prompt = "# Mission: Build FORM & FIELD — Premium Architecture and Interior Design Studio Website"
    spec = MissionSpecification.from_prompt(
        prompt=prompt,
        workspace_root=temp_ws,
        mission_id="m_spec_test"
    )

    assert spec.requested_brand == "FORM & FIELD"
    assert spec.business_domain == "architecture_interior"
    assert "portfolio" in spec.required_sections

    json_p, md_p = spec.persist(temp_ws)
    assert json_p.exists()
    assert md_p.exists()

    loaded = MissionSpecification.load_from_workspace(temp_ws)
    assert loaded is not None
    assert loaded.requested_brand == "FORM & FIELD"
    assert loaded.business_domain == "architecture_interior"
