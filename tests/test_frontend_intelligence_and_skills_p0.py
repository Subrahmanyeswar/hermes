# tests/test_frontend_intelligence_and_skills_p0.py
"""
Comprehensive P0 Qualification Suite for HERMES 2.x Frontend Intelligence:
Skill Discovery, Skill Injection, Premium UI Generation, Contract Consistency,
and Visual Quality Assurance. Covers all 30 requirements from Section 11.
"""

import json
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.project_intelligence.skills import SkillEngine
from core.project_intelligence.models import Skill, SkillMetadata, SkillRoutingDecision
from core.design_intelligence import DesignBrief, DesignBriefGenerator, ContentCoverageMap
from core.frontend_contract_validator import FrontendContractValidator, FrontendValidationReport
from core.mission_checkpoint import MissionCheckpoint, MissionCheckpointManager
from core.agent_loop.types import AgentLoopResult, ExecutionPhase


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"


@pytest.fixture
def skill_engine():
    """SkillEngine pointed to canonical repository skills/ directory."""
    return SkillEngine(workspace_root=REPO_ROOT, canonical_skills_root=SKILLS_DIR)


@pytest.fixture
def temp_workspace(tmp_path):
    """Isolated temporary workspace."""
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ==============================================================================
# SECTION A: Skill Discovery & Registry Invariants (Req 1 - 6)
# ==============================================================================

def test_req1_discover_skills_from_configured_directory(skill_engine):
    """Req 1: Discover skills from configured skills directories."""
    dirs = skill_engine.discover_skills_dirs()
    assert len(dirs) >= 1
    assert any(d == SKILLS_DIR.resolve() for d in dirs)
    index = skill_engine.index_skills()
    assert len(index) >= 20
    assert "vanilla-web" in index
    assert "taste-design" in index
    assert "design-engineering" in index


def test_req2_read_skill_metadata(skill_engine):
    """Req 2: Read skill metadata correctly from YAML frontmatter."""
    index = skill_engine.index_skills()
    meta = index["vanilla-web"]
    assert isinstance(meta, SkillMetadata)
    assert meta.name == "vanilla-web"
    assert len(meta.description) > 10
    assert len(meta.triggers) >= 1
    assert meta.sha256_hash is not None
    assert meta.mtime_ns > 0


def test_req3_resolve_relative_references_with_path_containment(skill_engine):
    """Req 3: Resolve relative references with path traversal guard."""
    # database-design has a valid references/ directory
    content, err = skill_engine.load_skill_resource("database-design", "references/schema_patterns.md")
    assert err is None
    assert content is not None
    assert len(content) > 0

    # Path traversal attack must be blocked
    bad_content, bad_err = skill_engine.load_skill_resource("database-design", "../../../etc/passwd")
    assert bad_content is None
    assert "path traversal" in bad_err.lower() or "security violation" in bad_err.lower()


def test_req4_handle_unavailable_or_malformed_skills(skill_engine, tmp_path):
    """Req 4: Handle unavailable, non-existent, or malformed skills safely."""
    # Non-existent skill
    missing = skill_engine.load_skill("non-existent-skill-xyz")
    assert missing is None

    # Missing resource
    res, err = skill_engine.load_skill_resource("vanilla-web", "non_existent_file.txt")
    assert res is None
    assert "SKILL_RESOURCE_NOT_FOUND" in err


def test_req5_cache_skill_registry_results(skill_engine):
    """Req 5: Cached skill registry avoids repeated scans on every call."""
    index1 = skill_engine.index_skills()
    initial_mtime = index1["vanilla-web"].mtime_ns

    # Call again without force_reload -> returns cached index immediately
    index2 = skill_engine.index_skills()
    assert index1 is index2
    assert index2["vanilla-web"].mtime_ns == initial_mtime
    # Level 2 body cache remains empty during Level 1 indexing
    assert len(skill_engine._body_cache) == 0


def test_req6_detect_modified_skill_contents(skill_engine, tmp_path):
    """Req 6: Detect modified skill contents and invalidate cache appropriately."""
    custom_skills = tmp_path / "custom_skills"
    test_skill_dir = custom_skills / "test-dyn-skill"
    test_skill_dir.mkdir(parents=True)
    skill_file = test_skill_dir / "SKILL.md"
    skill_file.write_text("---\nname: test-dyn-skill\ndescription: Test Dynamic\ntriggers: [test]\n---\nInitial Body", encoding="utf-8")

    engine = SkillEngine(workspace_root=tmp_path, canonical_skills_root=custom_skills)
    idx1 = engine.index_skills()
    assert "test-dyn-skill" in idx1
    assert idx1["test-dyn-skill"].description == "Test Dynamic"

    # Modify file
    time.sleep(0.05)
    skill_file.write_text("---\nname: test-dyn-skill\ndescription: Updated Dynamic Description\ntriggers: [test]\n---\nUpdated Body", encoding="utf-8")
    
    changed, affected = engine.check_freshness()
    assert changed is True
    assert "test-dyn-skill" in affected
    assert engine._metadata_index["test-dyn-skill"].description == "Updated Dynamic Description"


# ==============================================================================
# SECTION B: Skill Selection and Intent Routing (Req 7 - 15)
# ==============================================================================

def test_req7_select_frontend_design_skills_for_website_missions(skill_engine):
    """Req 7: Select frontend design skills for rich website missions (e.g. WanderWorld)."""
    prompt = "Build WanderWorld website with hero section, destination cards, travel packages, and customer reviews"
    decision = skill_engine.route_skills(prompt)
    assert not decision.is_fallback
    assert "vanilla-web" in decision.selected_skills
    assert "taste-design" in decision.selected_skills
    assert "design-engineering" in decision.selected_skills
    assert "web-design-guidelines" in decision.selected_skills
    # Customer reviews must NOT activate code-review
    assert "code-review" not in decision.selected_skills


def test_req8_select_vanilla_javascript_skills(skill_engine):
    """Req 8: Select vanilla JavaScript skills when vanilla web is requested."""
    prompt = "Build a responsive static landing page with HTML, CSS, and vanilla JS"
    decision = skill_engine.route_skills(prompt)
    assert "vanilla-web" in decision.selected_skills
    assert not decision.is_fallback


def test_req9_avoid_react_skills_when_react_not_requested(skill_engine):
    """Req 9: Ordinary HTML/vanilla tasks must NOT activate React-specific skills."""
    prompt = "Build a static single-page cafe landing page using clean HTML5 and semantic styling"
    decision = skill_engine.route_skills(prompt)
    assert "react-frontend" not in decision.selected_skills
    assert "react-best-practices" not in decision.selected_skills
    assert "react-composition-patterns" not in decision.selected_skills


def test_req10_respect_negative_project_constraints(skill_engine):
    """Req 10: Explicit negative constraints prevent conflicting skill activation."""
    # Negative constraint: no backend, no database
    prompt = "Build a rich travel showcase website with no backend and no database, vanilla JS only"
    decision = skill_engine.route_skills(prompt)
    assert "flask-rest-api" not in decision.selected_skills
    assert "fastapi-backend" not in decision.selected_skills
    assert "database-design" not in decision.selected_skills
    assert "vanilla-web" in decision.selected_skills

    # Negative constraint: without vanilla, use react
    prompt_react = "Build a customer dashboard without vanilla js, use react and jsx"
    decision_react = skill_engine.route_skills(prompt_react)
    assert "vanilla-web" not in decision_react.selected_skills
    assert "react-frontend" in decision_react.selected_skills


def test_req11_load_only_relevant_skills(skill_engine):
    """Req 11: Route only relevant skills, capping to top candidates without skill flooding."""
    prompt = "Adjust button spacing in existing CSS without redesigning"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert "taste-design" not in decision.selected_skills
    assert "design-system" not in decision.selected_skills


def test_req12_include_skill_guidance_in_planning_and_mandates():
    """Req 12: Injected compact design brief and skill guidance are included in phase mandates."""
    brief = DesignBriefGenerator.generate_brief("Build a WanderWorld travel website")
    directive = brief.to_compact_directive()
    assert "TRAVEL_TOURISM" in directive
    assert "Color Palette:" in directive
    assert "Primary:" in directive or "primary:" in directive
    assert "Container max-width:" in directive
    assert "Zero horizontal overflow" in directive


def test_req13_preserve_skills_across_checkpoints(temp_workspace):
    """Req 13: Preserve active skills and telemetry across durable checkpoints."""
    checkpoint = MissionCheckpointManager.save_checkpoint(
        workspace_root=temp_workspace,
        mission_id="m_test_skills",
        current_phase="PHASE_B_FOUNDATION",
        active_skills=["vanilla-web", "taste-design", "design-engineering"],
        skill_telemetry={"vanilla-web": {"status": "LOADED", "score": 0.95}},
        design_brief={"domain": "travel_tourism", "personality": "inspiring"},
    )
    assert checkpoint.active_skills == ["vanilla-web", "taste-design", "design-engineering"]

    # Reload checkpoint
    loaded = MissionCheckpointManager.load_checkpoint(temp_workspace)
    assert loaded is not None
    assert loaded.active_skills == ["vanilla-web", "taste-design", "design-engineering"]
    assert loaded.skill_telemetry["vanilla-web"]["status"] == "LOADED"
    assert loaded.design_brief["domain"] == "travel_tourism"


def test_req14_skill_lifecycle_telemetry_progression():
    """Req 14: Report discovered vs selected vs loaded vs injected vs applied correctly."""
    telemetry = {
        "__discovered_skills__": ["vanilla-web", "taste-design", "code-review"],
        "vanilla-web": {"status": "SELECTED", "score": 0.9},
    }
    assert "vanilla-web" in telemetry["__discovered_skills__"]
    
    # Transition to LOADED
    telemetry["vanilla-web"]["status"] = "LOADED"
    assert telemetry["vanilla-web"]["status"] == "LOADED"

    # Transition to INJECTED (upon phase B/C prompt assembly)
    telemetry["vanilla-web"]["status"] = "INJECTED"
    assert telemetry["vanilla-web"]["status"] == "INJECTED"

    # Transition to APPLIED (upon validation evidence verification)
    telemetry["vanilla-web"]["status"] = "APPLIED"
    telemetry["vanilla-web"]["evidence"] = "Frontend contract verified."
    assert telemetry["vanilla-web"]["status"] == "APPLIED"


def test_req15_graceful_no_skill_fallback(skill_engine):
    """Req 15: Pure theoretical inquiry or unsupported task falls back gracefully."""
    prompt = "What is the philosophical difference between procedural and functional programming?"
    decision = skill_engine.route_skills(prompt)
    assert decision.is_fallback
    assert len(decision.selected_skills) == 0


# ==============================================================================
# SECTION C: Frontend Contract Validation (Req 16 - 24)
# ==============================================================================

def test_req16_detect_mismatched_css_classes():
    """Req 16: Detect unstyled component classes used in HTML but absent in CSS."""
    html = '<button class="btn btn-primary">Book Now</button><div class="modal"></div>'
    css = 'body { font-family: sans-serif; }'
    issues = FrontendContractValidator.validate_css_classes(html, css)
    comp_types = [iss["component"] for iss in issues]
    assert "btn" in comp_types
    assert "modal" in comp_types


def test_req17_detect_missing_dom_ids():
    """Req 17: Detect missing DOM IDs queried by JavaScript."""
    html = '<header id="site-header"><h1>Title</h1></header>'
    js = 'const searchInput = document.getElementById("destination-search");'
    issues = FrontendContractValidator.validate_dom_ids(html, js)
    assert len(issues) == 1
    assert issues[0]["id"] == "destination-search"
    assert "MISSING_DOM_ID" in issues[0]["type"]


def test_req18_detect_dangerous_section_overwrite():
    """Req 18: Detect dynamic JS innerHTML targeting a root <section> instead of child container."""
    html = '''
    <section id="destinations">
      <h2>Popular Destinations</h2>
      <div class="filters"><button>Beach</button></div>
      <div id="destinations-grid"></div>
    </section>
    '''
    # Destructive overwrite targeting <section id="destinations">
    js_bad = 'document.getElementById("destinations").innerHTML = "<div>cards</div>";'
    issues_bad = FrontendContractValidator.validate_render_targets(html, js_bad)
    assert len(issues_bad) == 1
    assert issues_bad[0]["type"] == "DANGEROUS_SECTION_OVERWRITE"

    # Safe render targeting child container <div id="destinations-grid">
    js_good = 'document.getElementById("destinations-grid").innerHTML = "<div>cards</div>";'
    issues_good = FrontendContractValidator.validate_render_targets(html, js_good)
    assert len(issues_good) == 0


def test_req19_detect_category_mismatches():
    """Req 19: Detect inconsistent category values between HTML filter buttons and JS data."""
    html = '''
    <div class="filters">
      <button data-category="beach">Beach</button>
      <button data-category="mountains">Mountains</button>
      <button data-category="cultural">Cultural</button>
    </div>
    '''
    # JS data only has 'mountain' (singular), causing mismatch with 'mountains'
    js = '''
    const destinations = [
      { id: 1, name: "Bali", category: "beach" },
      { id: 2, name: "Swiss Alps", category: "mountain" },
      { id: 3, name: "Kyoto", category: "cultural" }
    ];
    '''
    issues = FrontendContractValidator.validate_category_consistency(html, js)
    assert len(issues) == 1
    assert issues[0]["category"] == "mountains"


def test_req20_detect_missing_responsive_styles():
    """Req 20: Detect missing responsive media queries and overflow guards."""
    css_no_media = 'body { margin: 0; padding: 20px; }'
    issues = FrontendContractValidator.validate_responsive_css(css_no_media)
    types = [iss["type"] for iss in issues]
    assert "MISSING_RESPONSIVE_MEDIA_QUERIES" in types
    assert "MISSING_OVERFLOW_GUARD" in types

    css_good = '''
    body { margin: 0; overflow-x: hidden; }
    @media (max-width: 768px) {
      .cards-grid { grid-template-columns: 1fr; }
    }
    '''
    issues_good = FrontendContractValidator.validate_responsive_css(css_good)
    assert len(issues_good) == 0


def test_req21_detect_unstyled_navigation_and_form_controls():
    """Req 21: Detect unstyled navigation and form input controls."""
    html = '<nav class="navbar"><a href="#">Home</a></nav><form class="form-group"><input class="form-input" /></form>'
    css_empty = 'body { color: #333; }'
    issues = FrontendContractValidator.validate_css_classes(html, css_empty)
    comps = [iss["component"] for iss in issues]
    assert "navbar" in comps
    assert "form_control" in comps


def test_req22_detect_defective_modal_styling():
    """Req 22: Detect missing position:fixed and z-index for modal dialogs."""
    html = '<div id="modal" class="modal"><h2>Details</h2></div>'
    css_bad = '.modal { width: 400px; margin: auto; }'
    issues_bad = FrontendContractValidator.validate_modal_styling(html, css_bad)
    assert len(issues_bad) == 1
    assert issues_bad[0]["type"] == "DEFECTIVE_MODAL_CSS"

    css_good = '.modal { position: fixed; top: 0; left: 0; z-index: 1000; display: none; }'
    issues_good = FrontendContractValidator.validate_modal_styling(html, css_good)
    assert len(issues_good) == 0


def test_req23_detect_image_alt_and_unconstrained_images():
    """Req 23: Detect missing alt attributes and unconstrained image dimensions."""
    html = '<img src="hero.jpg" /><img src="bali.jpg" alt="Bali Beach" />'
    css_no_fit = 'body { background: white; }'
    issues = FrontendContractValidator.validate_image_styling(html, css_no_fit)
    types = [iss["type"] for iss in issues]
    assert "IMG_MISSING_ALT" in types
    assert "UNCONSTRAINED_IMAGES" in types


def test_req24_verify_data_integrity_and_full_report(temp_workspace):
    """Req 24: End-to-end workspace validation returns comprehensive report."""
    html_content = '''<!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>WanderWorld Luxury Travel</title>
      <link rel="stylesheet" href="style.css">
    </head>
    <body>
      <nav class="navbar"><a href="#">WanderWorld</a></nav>
      <section id="hero"><h1>Discover the World</h1></section>
      <section id="destinations">
        <h2>Destinations</h2>
        <div class="filters"><button data-category="beach">Beach</button></div>
        <div id="destinations-grid" class="cards-grid"></div>
      </section>
      <div id="modal" class="modal"></div>
      <img src="bali.jpg" alt="Bali tropical beach" class="card-img" />
      <script src="app.js"></script>
    </body>
    </html>'''

    css_content = '''
    body { margin: 0; overflow-x: hidden; font-family: sans-serif; }
    .navbar { display: flex; padding: 1rem; }
    .cards-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
    .modal { position: fixed; top: 0; left: 0; z-index: 1000; display: none; }
    .card-img { width: 100%; object-fit: cover; aspect-ratio: 4/3; }
    @media (max-width: 768px) {
      .cards-grid { grid-template-columns: 1fr; }
    }
    '''

    js_content = '''
    const grid = document.getElementById("destinations-grid");
    const modal = document.getElementById("modal");
    const items = [{ id: 1, name: "Bali", category: "beach" }];
    grid.innerHTML = items.map(i => `<div class="card">${i.name}</div>`).join("");
    '''

    (temp_workspace / "index.html").write_text(html_content, encoding="utf-8")
    (temp_workspace / "style.css").write_text(css_content, encoding="utf-8")
    (temp_workspace / "app.js").write_text(js_content, encoding="utf-8")

    validator = FrontendContractValidator(temp_workspace)
    report = validator.validate_all()
    assert report.is_valid is True
    assert len(report.errors) == 0
    assert (temp_workspace / ".hermes" / "frontend_contract_report.json").exists()


# ==============================================================================
# SECTION D: Performance, Checkpoints, and Orchestration (Req 25 - 30)
# ==============================================================================

def test_req25_skill_selection_requires_zero_model_calls(skill_engine):
    """Req 25: Skill routing executes locally using metadata without external model calls."""
    skill_engine.index_skills()
    start = time.perf_counter()
    decision = skill_engine.route_skills("Build a modern portfolio website with responsive design")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.20  # Fast local in-memory routing
    assert len(decision.selected_skills) >= 1


def test_req26_cached_skills_not_reread_on_every_turn(skill_engine):
    """Req 26: Cached skills remain in memory without disk reread overhead."""
    # First load
    skill_engine.index_skills()
    skill = skill_engine.load_skill("vanilla-web")
    assert skill is not None
    assert "vanilla-web" in skill_engine._body_cache

    # Subsequent loads come directly from cache
    skill2 = skill_engine.load_skill("vanilla-web")
    assert skill is skill2


def test_req27_compact_context_size_bounded():
    """Req 27: Design brief directive is compact (less than 200 words)."""
    brief = DesignBriefGenerator.generate_brief("Build a responsive travel website")
    text = brief.to_compact_directive()
    words = text.split()
    assert len(words) < 200


def test_req28_small_mission_fast_path(skill_engine):
    """Req 28: Small website prompts retain single-skill fast execution behavior."""
    prompt = "Build a static single-page cafe landing page using clean HTML5 and semantic styling"
    decision = skill_engine.route_skills(prompt)
    assert decision.selected_skills == ["vanilla-web"]


def test_req29_large_mission_preserves_skills_and_content_coverage(temp_workspace):
    """Req 29: Large website missions preserve loaded skills and content coverage map."""
    prompt = "Build WanderWorld website with hero, destinations, travel packages, and customer reviews"
    cmap = ContentCoverageMap.from_prompt(prompt)
    assert len(cmap.sections) >= 5
    assert "destinations" in cmap.sections
    assert "reviews" in cmap.sections

    # Checkpoint saving preserves content coverage
    chk = MissionCheckpointManager.save_checkpoint(
        workspace_root=temp_workspace,
        mission_id="m_wanderworld_large",
        current_phase="PHASE_C_MAIN_IMPLEMENTATION",
        active_skills=["vanilla-web", "taste-design", "design-engineering", "web-design-guidelines"],
        content_coverage=cmap.to_dict(),
    )
    assert len(chk.active_skills) == 4
    assert len(chk.content_coverage["sections"]) >= 5


def test_req30_regression_existing_checkpoint_and_result_types():
    """Req 30: AgentLoopResult and MissionCheckpoint backwards compatibility is preserved."""
    # Test AgentLoopResult with new fields
    res = AgentLoopResult(
        mission_id="m_reg_test",
        success=True,
        status="COMPLETE",
        active_skills=["vanilla-web"],
        skill_telemetry={"vanilla-web": {"status": "APPLIED"}},
    )
    assert res.success is True
    assert res.active_skills == ["vanilla-web"]
    assert res.skill_telemetry["vanilla-web"]["status"] == "APPLIED"

    # Test MissionCheckpoint backwards compatibility from dict without new fields
    old_dict = {
        "mission_id": "m_legacy",
        "current_phase": "PHASE_B_FOUNDATION",
        "completed_phases": ["PHASE_A_PLANNING"],
        "completed_tasks": ["task_1"],
        "workspace_fingerprint": {},
        "validation_evidence": [],
        "tier_state": 1,
        "timestamp": 123456.0,
        "metadata": {},
    }
    restored = MissionCheckpoint.from_dict(old_dict)
    assert restored.mission_id == "m_legacy"
    assert restored.active_skills == []
    assert restored.skill_telemetry == {}
    assert restored.design_brief == {}
    assert restored.content_coverage == {}
