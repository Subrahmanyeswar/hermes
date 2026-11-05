# tests/test_p0_phase3_contract_first_code_generation.py
"""
Deterministic Verification Suite for HERMES 2.x Phase 3:
Shared Implementation Contracts, Cross-File Consistency, Design Intelligence,
Authoritative Entrypoints, Skill Evidence Ledgers, and Work-Package Gating.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from core.frontend_contract import (
    FrontendImplementationContract,
    FrontendContractBuilder,
    ArchitectureContract,
    ComponentContract,
    DomAndStateContract,
    CssContract,
    JavaScriptContract,
    AssetContractItem,
)
from core.skill_evidence_ledger import (
    SkillEvidenceLedger,
    SkillEvidenceRecord,
    SkillLifecycleStage,
    SkillApplicationStatus,
    SkillVerificationStatus,
)
from core.frontend_contract_validator import (
    FrontendContractValidator,
    FrontendValidationReport,
)
from core.work_package_gate import (
    WorkPackageGater,
    WorkPackageGateResult,
)
from core.design_intelligence import DesignBrief


# ==============================================================================
# 1. CONTRACT CREATION
# ==============================================================================

def test_01_contract_creation():
    """Verify that FrontendContractBuilder constructs an authoritative contract with all required domains."""
    contract = FrontendContractBuilder.build_initial_contract(
        task="Create WanderWorld travel agency website with holiday packages and booking",
        mission_id="m_wanderworld_test",
    )

    assert contract.app_name == "WanderWorld"
    assert contract.version == 1
    assert contract.architecture.entrypoint == "index.html"
    assert contract.architecture.authoritative_script == "app.js"
    assert contract.architecture.authoritative_style == "style.css"

    # Check structural components
    comp_ids = {c.id for c in contract.components}
    assert "navbar" in comp_ids
    assert "hero" in comp_ids
    assert "destinations" in comp_ids
    assert "packages" in comp_ids
    assert "booking-modal" in comp_ids

    # Check DOM and state
    assert "destinations-grid" in contract.dom_and_state.dynamic_ids
    assert "navbar" in contract.dom_and_state.required_static_ids

    # Check CSS tokens and layout
    assert "--primary-color" in contract.css.design_tokens
    assert len(contract.css.design_tokens) >= 5

    # Check hash is non-empty
    assert len(contract.contract_hash) == 16


# ==============================================================================
# 2. CONTRACT PERSISTENCE
# ==============================================================================

def test_02_contract_persistence(tmp_path):
    """Verify that the contract persists to .hermes/frontend_contract.json and loads identically."""
    contract = FrontendContractBuilder.build_initial_contract("Test App", mission_id="m_persist_1")
    save_path = contract.save_to_workspace(tmp_path)

    assert save_path.exists()
    assert save_path.name == "frontend_contract.json"
    assert save_path.parent.name == ".hermes"

    loaded = FrontendImplementationContract.load_from_workspace(tmp_path)
    assert loaded is not None
    assert loaded.app_name == contract.app_name
    assert loaded.contract_hash == contract.contract_hash
    assert loaded.architecture.authoritative_script == contract.architecture.authoritative_script


# ==============================================================================
# 3. CONTRACT VERSION CONSISTENCY ACROSS PHASES
# ==============================================================================

def test_03_contract_version_consistency_across_phases():
    """Verify that intentional updates increment contract version and update SHA-256 fingerprint."""
    contract = FrontendContractBuilder.build_initial_contract("Version App", mission_id="m_ver_1")
    v1 = contract.version
    h1 = contract.contract_hash

    # Reconcile from HTML adding new elements
    html_sample = '<div id="new-feature-container" class="feature-card"><script src="app.js"></script></div>'
    reconciled = FrontendContractBuilder.reconcile_from_html(contract, html_sample)

    assert reconciled.version == v1 + 1
    assert reconciled.contract_hash != h1
    assert "new-feature-container" in reconciled.dom_and_state.required_static_ids


# ==============================================================================
# 4. ENTRYPOINT DECLARATION
# ==============================================================================

def test_04_entrypoint_declaration():
    """Verify single authoritative entrypoint contract specification."""
    contract = FrontendContractBuilder.build_initial_contract("Entry App")
    assert contract.architecture.authoritative_script == "app.js"
    assert contract.javascript.authoritative_entrypoint == "app.js"
    directive = contract.to_compact_directive()
    assert "Authoritative Script Entrypoint: 'app.js'" in directive


# ==============================================================================
# 5. DUPLICATE COMPETING ENTRYPOINTS
# ==============================================================================

def test_05_duplicate_competing_entrypoints(tmp_path):
    """Verify that unlinked competing scripts (e.g. main.js when app.js is linked) are flagged as orphans."""
    (tmp_path / "index.html").write_text(
        '<!DOCTYPE html><html><body><script src="app.js"></script></body></html>',
        encoding="utf-8"
    )
    (tmp_path / "app.js").write_text('console.log("App running");', encoding="utf-8")
    (tmp_path / "main.js").write_text('console.log("Conflicting orphan");', encoding="utf-8")

    issues = FrontendContractValidator.validate_entrypoint_integrity(tmp_path)
    orphan_issues = [i for i in issues if i["type"] == "ORPHAN_COMPETING_ENTRYPOINT"]

    assert len(orphan_issues) >= 1
    assert orphan_issues[0]["file"] == "main.js"


# ==============================================================================
# 6. INTENTIONAL MULTIPLE MODULES
# ==============================================================================

def test_06_intentional_multiple_modules(tmp_path):
    """Verify that secondary ES modules imported by the authoritative script are preserved without error."""
    (tmp_path / "index.html").write_text(
        '<!DOCTYPE html><html><body><script type="module" src="app.js"></script></body></html>',
        encoding="utf-8"
    )
    (tmp_path / "app.js").write_text(
        'import { fetchDestinations } from "./api.js";\nfetchDestinations();',
        encoding="utf-8"
    )
    (tmp_path / "api.js").write_text(
        'export function fetchDestinations() { return []; }',
        encoding="utf-8"
    )

    issues = FrontendContractValidator.validate_entrypoint_integrity(tmp_path)
    orphan_issues = [i for i in issues if i["type"] == "ORPHAN_COMPETING_ENTRYPOINT"]
    assert len(orphan_issues) == 0


# ==============================================================================
# 7. MISSING STATIC DOM ID
# ==============================================================================

def test_07_missing_static_dom_id():
    """Verify that JavaScript querying an ID absent from HTML is detected as MISSING_DOM_ID."""
    html_text = '<div id="navbar"></div><div id="hero"></div>'
    js_text = 'const search = document.getElementById("search-input");'

    issues = FrontendContractValidator.validate_dom_ids(html_text, js_text)
    assert len(issues) == 1
    assert issues[0]["type"] == "MISSING_DOM_ID"
    assert issues[0]["id"] == "search-input"


# ==============================================================================
# 8. MISSING STATIC CLASS SELECTOR
# ==============================================================================

def test_08_missing_static_class_selector():
    """Verify that JavaScript querying an unknown class selector absent from HTML and CSS is detected."""
    html_text = '<div class="navbar"><button class="btn">Click</button></div>'
    css_text = '.navbar { display: flex; } .btn { color: blue; }'
    js_text = 'const overlay = document.querySelector(".unknown-booking-overlay");'

    issues = FrontendContractValidator.validate_js_selector_contracts(html_text, js_text, css_text)
    assert len(issues) == 1
    assert issues[0]["type"] == "UNKNOWN_JS_CLASS_SELECTOR"
    assert issues[0]["class_name"] == "unknown-booking-overlay"


# ==============================================================================
# 9. LEGITIMATE DYNAMICALLY RENDERED CLASS
# ==============================================================================

def test_09_legitimate_dynamically_rendered_class():
    """Verify that dynamic classes declared in contract or created dynamically in JS are NOT rejected."""
    contract = FrontendContractBuilder.build_initial_contract("Dynamic Test")
    contract.dom_and_state.dynamic_classes.append("destination-card-filtered")

    html_text = '<div id="destinations-grid"></div>'
    css_text = '.destination-card-filtered { opacity: 0.5; }'
    js_text = 'document.querySelector(".destination-card-filtered");'

    issues = FrontendContractValidator.validate_js_selector_contracts(
        html_text, js_text, css_text, contract=contract
    )
    assert len(issues) == 0


# ==============================================================================
# 10. OPTIONAL DOM SELECTOR
# ==============================================================================

def test_10_optional_dom_selector():
    """Verify that optional selectors declared in the contract are not flagged if omitted from HTML."""
    contract = FrontendContractBuilder.build_initial_contract("Optional Test")
    contract.dom_and_state.optional_selectors = ["#theme-toggle", ".dark-mode"]

    html_text = '<div id="navbar"></div>'
    js_text = 'const toggle = document.getElementById("theme-toggle");'

    issues = FrontendContractValidator.validate_dom_ids(html_text, js_text, contract=contract)
    assert len(issues) == 0


# ==============================================================================
# 11. MISSING FORM ELEMENT
# ==============================================================================

def test_11_missing_form_element():
    """Verify that JavaScript querying form inputs absent from the HTML form is detected."""
    html_text = '<form id="booking-form"><input name="user_name" /><input name="user_email" /></form>'
    js_text = 'const dest = form.elements["destination_package_id"].value;'

    issues = FrontendContractValidator.validate_form_elements(html_text, js_text)
    assert len(issues) == 1
    assert issues[0]["type"] == "MISSING_FORM_ELEMENT"
    assert issues[0]["field_name"] == "destination_package_id"


# ==============================================================================
# 12. MISSING RENDER CONTAINER (DANGEROUS SECTION OVERWRITE)
# ==============================================================================

def test_12_missing_render_container_dangerous_overwrite():
    """Verify that dynamic JS overwriting a root <section> element instead of child container is rejected."""
    html_text = '<section id="destinations"><h2>Explore</h2><div class="filters"></div></section>'
    js_text = 'document.getElementById("destinations").innerHTML = "<div>Card</div>";'

    issues = FrontendContractValidator.validate_render_targets(html_text, js_text)
    assert len(issues) == 1
    assert issues[0]["type"] == "DANGEROUS_SECTION_OVERWRITE"
    assert issues[0]["target_id"] == "destinations"


# ==============================================================================
# 13. MISSING CSS LAYOUT RULES
# ==============================================================================

def test_13_missing_css_layout_rules():
    """Verify that components lacking structural CSS layout rules (display: flex/grid) are detected."""
    html_text = '<nav class="navbar"><a href="#">Home</a></nav>'
    css_text = '.navbar { color: black; font-size: 14px; }'

    issues = FrontendContractValidator.validate_structural_css_coverage(html_text, css_text)
    nav_issues = [i for i in issues if i["type"] == "MISSING_NAV_LAYOUT"]
    assert len(nav_issues) == 1


# ==============================================================================
# 14. COMPONENT STYLING COVERAGE
# ==============================================================================

def test_14_component_styling_coverage():
    """Verify that critical HTML components (cards, navbar, modals, buttons) have CSS rules."""
    html_text = '<div class="destination-card"></div><div class="modal"></div>'
    css_text = '.destination-card { padding: 10px; }'

    issues = FrontendContractValidator.validate_css_classes(html_text, css_text)
    modal_issues = [i for i in issues if i["component"] == "modal"]
    assert len(modal_issues) == 1


# ==============================================================================
# 15. RESPONSIVE CONTRACT COVERAGE
# ==============================================================================

def test_15_responsive_contract_coverage():
    """Verify responsive CSS detection: @media queries and overflow protection."""
    css_with_resp = """
    :root { --p: blue; }
    body { overflow-x: hidden; }
    @media (max-width: 768px) {
        .grid { grid-template-columns: 1fr; }
    }
    """
    issues = FrontendContractValidator.validate_responsive_css(css_with_resp)
    assert len(issues) == 0

    css_without_resp = "body { margin: 0; } .grid { display: grid; }"
    issues_missing = FrontendContractValidator.validate_responsive_css(css_without_resp)
    assert len(issues_missing) >= 1


# ==============================================================================
# 16. DESIGN BRIEF PROPAGATION
# ==============================================================================

def test_16_design_brief_propagation(tmp_path):
    """Verify DesignBrief creation, persistence, and compact directive rendering."""
    brief = DesignBrief(
        domain="travel_tourism",
        purpose="Luxury holiday booking",
        target_audience="High-end travellers",
        brand_personality="Elegant, cinematic, refined",
        visual_direction="Editorial photography with subtle golden accents",
        color_palette={"primary": "#1e3a8a", "accent": "#d97706"},
    )
    p_json, p_md = brief.persist_artifacts(tmp_path)
    assert p_json.exists()
    assert (tmp_path / ".hermes" / "design_brief.json").exists()

    directive = brief.to_compact_directive()
    assert "DESIGN BRIEF" in directive
    assert "Elegant, cinematic, refined" in directive


# ==============================================================================
# 17. MANDATORY SKILLS INJECTED INTO APPLICABLE CODE PHASES
# ==============================================================================

def test_17_mandatory_skills_injected_into_applicable_code_phases():
    """Verify that SkillEvidenceLedger tracks injection events across phases."""
    ledger = SkillEvidenceLedger(mission_id="m_inject_test")
    ledger.record_injected("taste-design", turn_id="turn_1", phase="PHASE_B_FOUNDATION", instruction_ids=["I1"])
    ledger.record_injected("design-system", turn_id="turn_2", phase="PHASE_C_MAIN_IMPLEMENTATION", instruction_ids=["I2"])

    assert ledger.records["taste-design"].current_stage == SkillLifecycleStage.INJECTED
    assert len(ledger.records["taste-design"].injection_events) == 1
    assert "turn_1" in ledger.records["taste-design"].associated_turns


# ==============================================================================
# 18. SKILL LIFECYCLE EVENT EVIDENCE
# ==============================================================================

def test_18_skill_lifecycle_event_evidence():
    """Verify full progression: DISCOVERED -> SELECTED -> LOADED -> INJECTED -> APPLIED -> VERIFIED."""
    ledger = SkillEvidenceLedger(mission_id="m_lifecycle_test")
    s = "design-system"

    ledger.record_discovered(s, source_path="skills/design-system/SKILL.md", version="2.0.0")
    assert ledger.records[s].current_stage == SkillLifecycleStage.DISCOVERED

    ledger.record_selected(s, reason="Mandatory frontend bundle")
    assert ledger.records[s].current_stage == SkillLifecycleStage.SELECTED

    ledger.record_loaded(s, source_path="skills/design-system/SKILL.md", content="--primary-color: #000;")
    assert ledger.records[s].current_stage == SkillLifecycleStage.LOADED

    ledger.record_injected(s, turn_id="turn_1", phase="PHASE_B_FOUNDATION")
    assert ledger.records[s].current_stage == SkillLifecycleStage.INJECTED


# ==============================================================================
# 19. SKILL-SPECIFIC APPLIED EVIDENCE
# ==============================================================================

def test_19_skill_specific_applied_evidence(tmp_path):
    """Verify physical evidence evaluation for all mandatory skills."""
    # Scaffold compliant workspace files
    (tmp_path / "index.html").write_text("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>WanderWorld</title>
        <link rel="stylesheet" href="style.css">
    </head>
    <body>
        <header><nav class="navbar"></nav></header>
        <main>
            <section class="hero"><h1>WanderWorld</h1></section>
            <section class="grid cards-grid">
                <div class="card destination-card"><img src="bali.jpg" alt="Bali Beach"></div>
            </section>
        </main>
        <footer></footer>
        <script src="app.js"></script>
    </body>
    </html>
    """, encoding="utf-8")

    (tmp_path / "style.css").write_text("""
    :root {
        --primary-color: #2563eb;
        --bg-color: #ffffff;
        --text-color: #111827;
    }
    body { font-family: sans-serif; color: var(--text-color); background: var(--bg-color); overflow-x: hidden; }
    .hero { min-height: 50vh; background: var(--primary-color); padding: 2rem; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; }
    .card { padding: 1rem; border-radius: 8px; }
    button:focus-visible, a:focus-visible { outline: 2px solid var(--primary-color); }
    @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
    """, encoding="utf-8")

    (tmp_path / "app.js").write_text('console.log("App ready");', encoding="utf-8")

    brief = DesignBrief(
        domain="travel", purpose="Travel site", target_audience="Travelers",
        brand_personality="cinematic, modern", visual_direction="editorial"
    )
    brief.persist_artifacts(tmp_path)

    ledger = SkillEvidenceLedger(mission_id="m_evidence_test")
    for sk in ["taste-design", "design-system", "design-engineering", "web-design-guidelines", "vanilla-web"]:
        ledger.get_or_create(sk)

    results = ledger.evaluate_physical_evidence(tmp_path, design_brief=brief)

    assert results["taste-design"]["applied_status"] == "APPLIED"
    assert results["design-system"]["applied_status"] == "APPLIED"
    assert results["design-engineering"]["applied_status"] == "APPLIED"
    assert results["web-design-guidelines"]["applied_status"] == "APPLIED"
    assert results["vanilla-web"]["applied_status"] == "APPLIED"


# ==============================================================================
# 20. MISSING DESIGN TOKENS
# ==============================================================================

def test_20_missing_design_tokens():
    """Verify that CSS lacking :root tokens is detected."""
    css_no_tokens = "body { color: black; background: white; }"
    issues = FrontendContractValidator.validate_design_system_tokens(css_no_tokens)

    assert len(issues) == 1
    assert issues[0]["type"] == "MISSING_ROOT_TOKENS"


# ==============================================================================
# 21. FUNCTIONAL INTERACTION CONTRACT (REAL HANDLERS VS CONSOLE.LOG)
# ==============================================================================

def test_21_functional_interaction_contract():
    """Verify that fake event handlers executing only console.log() are rejected."""
    fake_js = """
    document.getElementById("search-input").addEventListener("input", (e) => {
        console.log("Search query:", e.target.value);
    });
    """
    issues = FrontendContractValidator.validate_functional_interactions(fake_js)
    assert len(issues) == 1
    assert issues[0]["type"] == "CONSOLE_LOG_SUBSTITUTE_FEATURE"


# ==============================================================================
# 22. FAKE NPM TEST SCRIPT REJECTION
# ==============================================================================

def test_22_fake_npm_test_script_rejection(tmp_path):
    """Verify that package.json scripts with dummy exit 0 are rejected as test evidence."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "fake-test-project",
        "scripts": {"test": 'echo "No tests required" && exit 0'}
    }), encoding="utf-8")

    issues = FrontendContractValidator.validate_test_script_integrity(tmp_path)
    assert len(issues) == 1
    assert issues[0]["type"] == "FAKE_TEST_SCRIPT_REJECTED"


# ==============================================================================
# 23. EMPTY CONTENT GRID DETECTION
# ==============================================================================

def test_23_empty_content_grid_detection():
    """Verify that empty content grid containers without static cards or JS population are flagged."""
    html_text = '<div id="destinations-grid"></div>'
    js_text = 'console.log("Hello world");'

    issues = FrontendContractValidator.validate_empty_content_grids(html_text, js_text)
    assert len(issues) == 1
    assert issues[0]["type"] == "EMPTY_CONTENT_GRID"
    assert issues[0]["container_id"] == "destinations-grid"


# ==============================================================================
# 24. PROVIDER FAILOVER PRESERVING FRONTEND CONTRACT CONTEXT
# ==============================================================================

@pytest.mark.asyncio
async def test_24_provider_failover_preserving_frontend_contract_context():
    """Verify that Orchestrator/AgentLoop failover preserves contract, brief, and ledger."""
    from core.agent_loop.loop import AgentLoop
    from core.orchestrator import Orchestrator

    orch = Orchestrator()
    loop = AgentLoop.__new__(AgentLoop)
    loop.orchestrator = orch
    loop._mission_id = "m_failover_context_test"
    loop._active_skill_names = ["taste-design", "design-system"]

    contract = FrontendContractBuilder.build_initial_contract("Preserve Test", mission_id="m_failover_context_test")
    brief = DesignBrief(domain="travel", purpose="Travel site", target_audience="Guests", brand_personality="Modern", visual_direction="Clean")
    ledger = SkillEvidenceLedger(mission_id="m_failover_context_test")

    loop._frontend_contract = contract
    loop._design_brief = brief
    loop._skill_evidence_ledger = ledger

    # Failover transition to Tier 2
    loop.set_active_model_state(tier=2, provider="mistral", model="codestral-latest", reason="failover_test")

    assert loop.active_tier == 2
    assert loop._frontend_contract is contract
    assert loop._design_brief is brief
    assert loop._skill_evidence_ledger is ledger


# ==============================================================================
# 25. LARGE-MISSION RECOVERY PRESERVING CONTRACT AND BRIEF
# ==============================================================================

def test_25_large_mission_recovery_preserving_contract_and_brief(tmp_path):
    """Verify that checkpoint resume safely restores contract and ledger from .hermes/."""
    contract = FrontendContractBuilder.build_initial_contract("Recovery Test", mission_id="m_recovery_1")
    contract.save_to_workspace(tmp_path)

    ledger = SkillEvidenceLedger(mission_id="m_recovery_1")
    ledger.record_discovered("design-system")
    ledger.save_to_workspace(tmp_path)

    loaded_contract = FrontendImplementationContract.load_from_workspace(tmp_path)
    loaded_ledger = SkillEvidenceLedger.load_from_workspace(tmp_path)

    assert loaded_contract is not None
    assert loaded_contract.app_name == "Recovery Test"
    assert loaded_ledger is not None
    assert "design-system" in loaded_ledger.records


# ==============================================================================
# 26. WORK-PACKAGE GATING LIFECYCLE
# ==============================================================================

def test_26_work_package_gating_lifecycle(tmp_path):
    """Verify WorkPackageGater gating criteria across all execution phases."""
    # Empty workspace fails Foundation Gate
    res_f = WorkPackageGater.evaluate_foundation_gate(tmp_path)
    assert res_f.passed is False
    assert len(res_f.missing_criteria) >= 2

    # Provide foundation files
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><head><link rel='stylesheet' href='style.css'></head><body><nav></nav><section class='hero'></section></body></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text(":root { --p: blue; } body { color: var(--p); }", encoding="utf-8")
    brief = DesignBrief(domain="t", purpose="p", target_audience="a", brand_personality="bp", visual_direction="vd")
    brief.persist_artifacts(tmp_path)
    contract = FrontendContractBuilder.build_initial_contract("Gate Test", mission_id="m_gate")
    contract.save_to_workspace(tmp_path)

    res_f2 = WorkPackageGater.evaluate_foundation_gate(tmp_path, contract=contract, design_brief=brief)
    assert res_f2.passed is True
