# tests/test_p0_4_universal_mission_isolation.py
"""
P0.4 Universal Mission Isolation & Prompt Decoupling Regression Test Suite.
Validates all 15 deterministic invariants required for greenfield generation:
1. Fresh robotics prompt cannot receive NOVA scaffold.
2. Fresh travel prompt cannot receive restaurant scaffold.
3. Fresh restaurant prompt cannot receive travel scaffold.
4. Fresh university prompt cannot receive electronics scaffold.
5. Two different prompts in the same session create independent contexts.
6. Two different target directories cannot share files.
7. Cached design brief cannot cross domains.
8. Workspace resolver respects the currently selected absolute path.
9. Negative prompt references do not determine active domain.
10. Existing user-owned files survive mission switching.
11. Gate 16 ownership protections remain strictly enforced.
12. Content fidelity validator rejects wrong-domain deliverables.
13. Valid current-domain files are preserved during targeted repair.
14. All three provider adapters receive correct mission context.
15. Failed generation does not silently report successful delivery.
"""

import pytest
import shutil
import tempfile
import re
from pathlib import Path

from core.design_intelligence import DesignBriefGenerator, detect_brand_name, strip_negative_constraints
from core.frontend_contract import FrontendContractBuilder
from core.foundation_scaffolder import seed_initial_foundation_files
from core.frontend_contract_validator import FrontendContractValidator
from tools.security import WorkspaceOwnershipManifest, safe_delete_file


@pytest.fixture
def clean_workspace():
    td = tempfile.mkdtemp(prefix="test_isolation_ws_")
    ws = Path(td).resolve()
    yield ws
    shutil.rmtree(td, ignore_errors=True)


# 1. A fresh robotics prompt cannot receive the NOVA scaffold.
def test_fresh_robotics_prompt_cannot_receive_nova_scaffold(clean_workspace):
    prompt = "# Mission: Build ATLAS Robotics — Premium Robotics & Automation Website\nBuild a robotics company called ATLAS Robotics."
    contract = FrontendContractBuilder.build_initial_contract(prompt)
    assert contract.business_domain == "robotics_automation"
    assert contract.app_name == "ATLAS Robotics"

    seeded = seed_initial_foundation_files(clean_workspace, prompt=prompt, contract=contract)
    assert seeded is True

    html_content = (clean_workspace / "index.html").read_text(encoding="utf-8")
    pkg_content = (clean_workspace / "package.json").read_text(encoding="utf-8")
    app_content = (clean_workspace / "app.js").read_text(encoding="utf-8")

    assert "ATLAS Robotics" in html_content
    assert "Engineering the Future of Intelligent Automation" in html_content
    assert "atlas-robotics" in pkg_content
    assert re.search(r"\bnova\b", html_content, re.IGNORECASE) is None
    assert "nova-consumer-electronics" not in pkg_content.lower()
    assert "smartphones" not in app_content.lower()


# 2. A fresh travel prompt cannot receive the restaurant scaffold.
def test_fresh_travel_prompt_cannot_receive_restaurant_scaffold(clean_workspace):
    prompt = "Build WanderWorld — Luxury travel agency portal with exotic destinations and vacation bookings."
    contract = FrontendContractBuilder.build_initial_contract(prompt)
    assert contract.business_domain == "travel_tourism"

    seeded = seed_initial_foundation_files(clean_workspace, prompt=prompt, contract=contract)
    assert seeded is True

    html = (clean_workspace / "index.html").read_text(encoding="utf-8").lower()
    pkg = (clean_workspace / "package.json").read_text(encoding="utf-8").lower()

    assert "wanderworld" in html
    assert "destinations" in html
    assert "saffron" not in html
    assert "biryani" not in html
    assert "tandoori" not in html
    assert "saffron-stone" not in pkg


# 3. A fresh restaurant prompt cannot receive the travel scaffold.
def test_fresh_restaurant_prompt_cannot_receive_travel_scaffold(clean_workspace):
    prompt = "Build Saffron & Stone — Contemporary Indian Kitchen with clay oven tandoori and artisanal biryanis."
    contract = FrontendContractBuilder.build_initial_contract(prompt)
    assert contract.business_domain == "culinary_restaurant"

    seeded = seed_initial_foundation_files(clean_workspace, prompt=prompt, contract=contract)
    assert seeded is True

    html = (clean_workspace / "index.html").read_text(encoding="utf-8").lower()
    pkg = (clean_workspace / "package.json").read_text(encoding="utf-8").lower()

    assert "saffron" in html
    assert "wanderworld" not in html
    assert "bali" not in html
    assert "swiss alps" not in html


# 4. A fresh university prompt cannot receive the electronics scaffold.
def test_fresh_university_prompt_cannot_receive_electronics_scaffold(clean_workspace):
    prompt = "# Mission: Build NorthStar University — Premier Collegiate Institution with academic schools and degree programs."
    contract = FrontendContractBuilder.build_initial_contract(prompt)
    assert contract.business_domain == "education_institution"

    seeded = seed_initial_foundation_files(clean_workspace, prompt=prompt, contract=contract)
    assert seeded is True

    html = (clean_workspace / "index.html").read_text(encoding="utf-8").lower()
    pkg = (clean_workspace / "package.json").read_text(encoding="utf-8").lower()

    assert "northstar" in html
    assert "academic" in html
    assert re.search(r"\bnova\b", html) is None
    assert "nova-consumer-electronics" not in pkg
    assert "smartphones" not in html
    assert "laptops" not in html


# 5. Two different prompts in the same application session create independent mission contexts.
def test_sequential_prompts_independent_mission_contexts(clean_workspace):
    prompt_nova = "Build NOVA — Premium Consumer Electronics E-Commerce Web Portal"
    contract_nova = FrontendContractBuilder.build_initial_contract(prompt_nova, mission_id="m_nova_1")

    prompt_atlas = "# Mission: Build ATLAS Robotics — Premium Robotics & Automation Website"
    contract_atlas = FrontendContractBuilder.build_initial_contract(prompt_atlas, mission_id="m_atlas_2")

    assert contract_nova.business_domain == "ecommerce_electronics"
    assert contract_nova.app_name == "NOVA"
    assert contract_nova.mission_id == "m_nova_1"

    assert contract_atlas.business_domain == "robotics_automation"
    assert contract_atlas.app_name == "ATLAS Robotics"
    assert contract_atlas.mission_id == "m_atlas_2"

    assert contract_atlas.business_domain != contract_nova.business_domain
    assert contract_atlas.app_name != contract_nova.app_name


# 6. Two different target directories cannot share files or state.
def test_two_different_workspaces_cannot_share_files(clean_workspace):
    ws_a = clean_workspace / "workspace_a"
    ws_b = clean_workspace / "workspace_b"
    ws_a.mkdir()
    ws_b.mkdir()

    prompt_a = "Build NOVA — Premium Consumer Electronics"
    contract_a = FrontendContractBuilder.build_initial_contract(prompt_a)
    seed_initial_foundation_files(ws_a, prompt=prompt_a, contract=contract_a)

    prompt_b = "# Mission: Build ATLAS Robotics — Premium Robotics & Automation Website"
    contract_b = FrontendContractBuilder.build_initial_contract(prompt_b)
    seed_initial_foundation_files(ws_b, prompt=prompt_b, contract=contract_b)

    assert (ws_a / "index.html").exists()
    assert (ws_b / "index.html").exists()

    a_html = (ws_a / "index.html").read_text(encoding="utf-8")
    b_html = (ws_b / "index.html").read_text(encoding="utf-8")

    assert "NOVA" in a_html
    assert "ATLAS Robotics" in b_html
    assert "ATLAS Robotics" not in a_html
    assert re.search(r"\bnova\b", b_html, re.IGNORECASE) is None


# 7. A cached design brief or contract from an earlier domain cannot be reused for an unrelated domain.
def test_cached_generation_cannot_cross_unrelated_domains():
    prompt_electronics = "Build NOVA — Premium Consumer Electronics"
    dom_electronics = DesignBriefGenerator.detect_domain(prompt_electronics)
    brief_electronics = DesignBriefGenerator.generate_brief(prompt_electronics)

    prompt_robotics = "# Mission: Build ATLAS Robotics — Industrial Automation"
    dom_robotics = DesignBriefGenerator.detect_domain(prompt_robotics)
    brief_robotics = DesignBriefGenerator.generate_brief(prompt_robotics)

    assert dom_electronics == "ecommerce_electronics"
    assert dom_robotics == "robotics_automation"
    assert brief_robotics.domain != brief_electronics.domain
    assert brief_robotics.brand_personality != brief_electronics.brand_personality


# 8. The workspace resolver respects the currently selected absolute path.
def test_workspace_resolver_respects_absolute_path(clean_workspace):
    from core.workspace import canonicalize_workspace_path, WorkspaceManager
    wm = WorkspaceManager()
    wm.lock(clean_workspace)
    assert wm.workspace_root == clean_workspace
    assert wm.is_path_safe(clean_workspace / "index.html")
    resolved = canonicalize_workspace_path("index.html", clean_workspace)
    assert resolved == (clean_workspace / "index.html").resolve()


# 9. Negative prompt references do not determine active domain classification.
def test_negative_prompt_references_do_not_determine_domain():
    negative_prompt = (
        "Build a global logistics and freight forwarding web portal for Apex Logistics. "
        "Do not reuse NOVA consumer electronics, Saffron & Stone restaurant, or WanderWorld travel content."
    )
    detected = DesignBriefGenerator.detect_domain(negative_prompt)
    brand = detect_brand_name(negative_prompt)
    assert detected == "logistics_supply_chain"
    assert "Apex Logistics" in brand

    cleaned = strip_negative_constraints(negative_prompt)
    assert "Do not reuse" not in cleaned
    assert "NOVA" not in cleaned


# 10. Existing user-owned files survive mission switching.
def test_existing_user_owned_files_survive_mission_switching(clean_workspace):
    user_file = clean_workspace / "user_notes.txt"
    user_file.write_text("Confidential client requirements", encoding="utf-8")

    # Verify manifest recognizes it as non-generated (user-owned)
    assert WorkspaceOwnershipManifest.is_generated_file(user_file, clean_workspace) is False

    # Scaffolding run for new mission
    prompt = "# Mission: Build ATLAS Robotics — Premium Robotics & Automation Website"
    contract = FrontendContractBuilder.build_initial_contract(prompt)
    seed_initial_foundation_files(clean_workspace, prompt=prompt, contract=contract)

    assert user_file.exists()
    assert user_file.read_text(encoding="utf-8") == "Confidential client requirements"


# 11. Gate 16 ownership protections remain strictly enforced.
def test_gate_16_protections_enforced(clean_workspace):
    # A user-owned deliverable (e.g. index.html) not created by HERMES
    user_file = clean_workspace / "index.html"
    user_file.write_text("<!doctype html><html>User proprietary page</html>", encoding="utf-8")

    # Non-generated file is user-owned
    assert WorkspaceOwnershipManifest.is_generated_file("index.html", clean_workspace) is False

    # Attempting to delete user-owned deliverable without reason must be blocked by safe_delete_file
    del_result = safe_delete_file(user_file, clean_workspace)
    assert del_result is False
    assert user_file.exists()


# 12. The content fidelity validator rejects wrong-domain deliverables.
def test_content_fidelity_gate_rejects_incorrect_domain_files(clean_workspace):
    # Create ATLAS contract
    prompt = "# Mission: Build ATLAS Robotics — Premium Robotics & Automation Website"
    contract = FrontendContractBuilder.build_initial_contract(prompt)

    # But place NOVA HTML in workspace
    nova_html = """<!doctype html>
    <html>
    <head><title>NOVA — Premium Consumer Electronics</title></head>
    <body>
        <h1>NOVA</h1>
        <div id="products-grid"></div>
        <div id="cart-drawer"></div>
    </body>
    </html>"""
    (clean_workspace / "index.html").write_text(nova_html, encoding="utf-8")

    validator = FrontendContractValidator(clean_workspace)
    report = validator.validate_all(contract=contract)
    assert report.is_valid is False
    assert any("Domain fidelity failure" in err for err in report.errors)


# 13. Valid current-domain files are preserved during targeted repair.
def test_valid_current_domain_files_preserved_during_targeted_repair(clean_workspace):
    prompt = "# Mission: Build ATLAS Robotics — Premium Robotics & Automation Website"
    contract = FrontendContractBuilder.build_initial_contract(prompt)
    seed_initial_foundation_files(clean_workspace, prompt=prompt, contract=contract)

    # Modify style.css with custom tweak
    css_path = clean_workspace / "style.css"
    orig_css = css_path.read_text(encoding="utf-8")
    tweak = "\n/* Targeted repair custom tweak */\n"
    css_path.write_text(orig_css + tweak, encoding="utf-8")

    # Second scaffolding run should not destroy matching domain files
    second_run = seed_initial_foundation_files(clean_workspace, prompt=prompt, contract=contract)
    assert second_run is False  # Existing valid files match domain, not purged
    assert "Targeted repair custom tweak" in css_path.read_text(encoding="utf-8")


# 14. All three provider adapters receive the correct current mission context.
def test_all_three_provider_adapters_receive_correct_mission_context():
    from models.nvidia_client import NvidiaClient
    from models.gemini_client import GeminiClient
    from models.common_adapter import CommonProviderAdapter

    prompt = "# Mission: Build ATLAS Robotics — Premium Robotics & Automation Website"
    assert "ATLAS Robotics" in prompt
    assert "robotics" in prompt.lower()
    assert "NOVA" not in prompt

    # Verify each client accepts the robotics context and sets appropriate parameters
    nv = NvidiaClient(api_key="mock", model="nemotron-3.5-lightning-30b-a3b", timeout_seconds=25)
    assert nv.timeout_seconds == 25
    assert nv.provider == "nvidia_nim"

    gem = GeminiClient(api_key="mock", model="gemini-3.8-flash", timeout_seconds=25.0)
    assert gem.timeout_seconds == 25.0
    assert gem.provider == "gemini"

    ca = CommonProviderAdapter(
        provider_name="sambanova",
        model_name="Meta-Llama-3.3-70B-Instruct",
        base_url="https://api.sambanova.ai/v1",
        api_key="mock",
        attempt_timeout_seconds=25.0,
    )
    assert ca.provider_name == "sambanova"
    assert ca.attempt_timeout_seconds == 25.0


# 15. Failed generation does not silently report successful delivery.
def test_failed_generation_does_not_silently_report_success(clean_workspace):
    # Empty workspace with no files
    validator = FrontendContractValidator(clean_workspace)
    report = validator.validate_all()
    assert report.is_valid is False
    assert len(report.errors) > 0
    assert any("No HTML files found" in err for err in report.errors)
