# tests/test_phase6_skill_registry_routing.py
"""
Comprehensive Phase 6 Test Suite: Skill Registry, Intelligent Routing & Progressive Context Loading.

Covers:
1. Routing Scenarios A through J:
   - Scenario A: Vanilla web landing page -> vanilla-web
   - Scenario B: Python traceback ZeroDivisionError -> debugging
   - Scenario C: Flask REST API code review / security -> code-review / security-audit / flask-rest-api
   - Scenario D: Normalized PostgreSQL schema -> database-design
   - Scenario E: Multi-skill composition -> vanilla-web + flask-rest-api + database-design
   - Scenario F: Haiku about rain (no match) -> fallback (empty list, is_fallback=True)
   - Scenario G: Ambiguous performance request -> deterministic bounded selection, no thrashing
   - Scenario H: Workspace signal conflict resolution -> vanilla-web over react-frontend when index.html present
   - Scenario I: Changed / invalid skill frontmatter -> SKILL_LOAD_FAILED event, graceful exclusion
   - Scenario J: Continuation and restart -> state store persistence and restoration of active skills

2. Progressive Loading & Isolation Verification (Tests 1 through 10):
   - Test 1: Metadata index only (body is None on discovery)
   - Test 2: Body lazy load (loaded only on explicit request or selection)
   - Test 3: Unselected skills remain unloaded (11 of 13 unloaded)
   - Test 4: References lazy load (resources loaded on demand only)
   - Test 5: Helper scripts discovered without execution
   - Test 6: Loaded vs attached event distinction (SKILL_LOADED -> SKILL_CONTEXT_ATTACHED)
   - Test 7: Context prompt inspection (XML fencing, provenance tags, unselected excluded)
   - Test 8: Load error event emission (SKILL_LOAD_FAILED with error payload)
   - Test 9: Multi-skill attachment (distinct fences for multiple selected skills)
   - Test 10: State durability (active_skills and fingerprints serialized and restored)
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from core.context.engine import ContextEngine
from core.context.models import ContextSectionType, ContextSourceType
from core.project_intelligence.models import SkillRoutingDecision
from core.project_intelligence.registry import ProjectIntelligenceRegistry
from core.project_intelligence.skills import SkillEngine
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionState
from core.runtime_state.reducer import StateReducer
from core.runtime_state.store import StateStore


# Canonical repository root and skills directory
REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILLS_DIR = REPO_ROOT / "skills"


class MockEventBus:
    """In-memory event bus for testing canonical state events."""

    def __init__(self):
        self.events: List[HermesEvent] = []

    def publish(self, event: HermesEvent):
        self.events.append(event)

    def publish_nowait(self, event: HermesEvent):
        self.events.append(event)

    def has_event(self, event_type: EventType) -> bool:
        return any(e.event_type == event_type for e in self.events)

    def get_events(self, event_type: EventType) -> List[HermesEvent]:
        return [e for e in self.events if e.event_type == event_type]


@pytest.fixture
def mock_bus():
    return MockEventBus()


@pytest.fixture
def temp_workspace():
    """Isolated temporary workspace."""
    temp_dir = tempfile.mkdtemp(prefix="hermes_phase6_test_")
    ws_path = Path(temp_dir)
    yield ws_path
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def canonical_skill_engine():
    """SkillEngine pointed to canonical repository skills/ directory."""
    return SkillEngine(
        workspace_root=REPO_ROOT,
        canonical_skills_root=CANONICAL_SKILLS_DIR,
    )


@pytest.fixture
def canonical_registry(mock_bus):
    """ProjectIntelligenceRegistry configured with canonical repository skills."""
    return ProjectIntelligenceRegistry(
        workspace_root=REPO_ROOT,
        canonical_skills_root=CANONICAL_SKILLS_DIR,
        event_bus=mock_bus,
        mission_id="mission_phase6_test",
    )


# ══════════════════════════════════════════════════════════════════════════════
# Section 4: Routing Scenarios (Scenarios A through J)
# ══════════════════════════════════════════════════════════════════════════════


def test_scenario_a_vanilla_web(canonical_skill_engine):
    """Scenario A: Build a responsive static landing page with HTML, CSS, and vanilla JS."""
    prompt = "Build a responsive static landing page with HTML, CSS, and vanilla JS"
    decision = canonical_skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert decision.selected_skills == ["vanilla-web"]
    assert "react-frontend" not in decision.selected_skills
    assert "screenshot-to-code" not in decision.selected_skills
    assert decision.candidate_scores.get("vanilla-web", 0) > 0.3


def test_screenshot_to_code_positive_when_screenshot_supplied(canonical_skill_engine):
    """Positive test: screenshot-to-code activates when a screenshot or mockup is explicitly supplied."""
    prompt = "Recreate this dashboard UI from the supplied screenshot"
    decision = canonical_skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "screenshot-to-code" in decision.selected_skills
    assert decision.candidate_scores.get("screenshot-to-code", 0) >= 0.5


def test_screenshot_to_code_negative_on_plain_html_task(canonical_skill_engine):
    """Negative test: screenshot-to-code does NOT activate on general HTML/CSS tasks without visual references."""
    prompt = "Create a basic HTML5 form for user registration with CSS styling"
    decision = canonical_skill_engine.route_skills(prompt)

    assert "screenshot-to-code" not in decision.selected_skills
    assert decision.candidate_scores.get("screenshot-to-code", 0) < 0.30


def test_react_component_in_react_workspace(canonical_skill_engine):
    """React component in a React workspace routes to react-frontend, suppressing vanilla-web."""
    prompt = "Create a reusable NavigationHeader component"
    signals = {
        "files": ["package.json", "src/App.tsx", "src/index.tsx"],
        "framework": "react",
    }
    decision = canonical_skill_engine.route_skills(prompt, workspace_signals=signals)

    assert "react-frontend" in decision.selected_skills
    assert "vanilla-web" not in decision.selected_skills


def test_auto_docs_routing(canonical_skill_engine):
    """Generate API documentation and README routes to auto-docs."""
    prompt = "Generate comprehensive README and API docstrings from our codebase"
    decision = canonical_skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "auto-docs" in decision.selected_skills


def test_bash_scripting_routing(canonical_skill_engine):
    """Automation shell script prompt routes to bash-scripting."""
    prompt = "Write a bash automation script with trap cleanup for backup files"
    decision = canonical_skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "bash-scripting" in decision.selected_skills


def test_git_workflow_routing(canonical_skill_engine):
    """Git commit and branch prompt routes to git-workflow."""
    prompt = "Create a feature branch and stage atomic commit for version control"
    decision = canonical_skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "git-workflow" in decision.selected_skills


def test_scenario_b_python_traceback(canonical_skill_engine):
    """Scenario B: Fix this ZeroDivisionError in app/calculator.py."""
    prompt = "Fix this ZeroDivisionError in app/calculator.py: line 42 in divide: return a / b"
    decision = canonical_skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "debugging" in decision.selected_skills
    assert decision.candidate_scores.get("debugging", 0) > 0.3


def test_scenario_c_api_review(canonical_skill_engine):
    """Scenario C: Review the security and structure of this Flask REST endpoint."""
    prompt = "Review the security and structure of this Flask REST endpoint"
    decision = canonical_skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    # Expect code-review and/or security-audit and/or flask-rest-api
    selected = set(decision.selected_skills)
    assert bool(selected.intersection({"code-review", "security-audit", "flask-rest-api"}))


def test_scenario_d_database_design(canonical_skill_engine):
    """Scenario D: Design a normalized PostgreSQL schema for a multi-tenant SaaS application."""
    prompt = "Design a normalized PostgreSQL schema for a multi-tenant SaaS application"
    decision = canonical_skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "database-design" in decision.selected_skills
    assert decision.candidate_scores.get("database-design", 0) > 0.3


def test_scenario_e_multi_skill_composition(canonical_skill_engine):
    """Scenario E: Multi-skill composition - vanilla web + API + relational database."""
    prompt = "Build a vanilla website that submits data to a small API and persists it in a relational database"
    decision = canonical_skill_engine.route_skills(prompt, max_candidates=3)

    assert not decision.is_fallback
    selected = set(decision.selected_skills)
    assert "vanilla-web" in selected
    assert "flask-rest-api" in selected
    assert "database-design" in selected
    assert len(decision.selected_skills) >= 2


def test_scenario_f_no_match_fallback(canonical_skill_engine):
    """Scenario F: Irrelevant prompt (haiku) results in clean fallback with no skills selected."""
    prompt = "Write a haiku about the spring rain in Kyoto"
    decision = canonical_skill_engine.route_skills(prompt)

    assert decision.is_fallback
    assert len(decision.selected_skills) == 0
    assert "No skill met the relevance threshold" in decision.decision_rationale


def test_scenario_g_ambiguous_task(canonical_skill_engine):
    """Scenario G: Ambiguous performance task yields bounded deterministic selection without thrashing."""
    prompt = "Help me optimize my application performance"
    decision_1 = canonical_skill_engine.route_skills(prompt, max_candidates=2)
    decision_2 = canonical_skill_engine.route_skills(prompt, max_candidates=2)

    assert decision_1.selected_skills == decision_2.selected_skills
    assert len(decision_1.selected_skills) <= 2


def test_scenario_h_workspace_signal_conflict_resolution(canonical_skill_engine):
    """Scenario H: Generic component prompt in vanilla workspace resolves to vanilla-web, not react."""
    prompt = "Create a new modal component for user profile details"
    signals = {
        "files": ["index.html", "style.css", "app.js"],
        "framework": "vanilla",
    }
    decision = canonical_skill_engine.route_skills(prompt, workspace_signals=signals)

    assert "vanilla-web" in decision.selected_skills
    assert "react-frontend" not in decision.selected_skills
    assert "react-frontend" in decision.rejection_reasons


def test_scenario_i_changed_or_invalid_skill(temp_workspace, mock_bus):
    """Scenario I: Corrupted skill frontmatter surfaces SKILL_LOAD_FAILED and does not crash."""
    bad_skill_dir = temp_workspace / ".hermes" / "skills" / "broken_skill"
    bad_skill_dir.mkdir(parents=True)
    (bad_skill_dir / "SKILL.md").write_text(
        "---\nname: [broken-yaml: unclosed delimiter\n---\nBody",
        encoding="utf-8",
    )

    reg = ProjectIntelligenceRegistry(
        workspace_root=temp_workspace,
        event_bus=mock_bus,
        mission_id="m_broken",
    )
    reg.discover()

    # Attempt to load broken skill
    skill = reg.load_skill_body("broken_skill")
    assert skill is None

    # Verify SKILL_LOAD_FAILED event was emitted
    failed_events = mock_bus.get_events(EventType.SKILL_LOAD_FAILED)
    assert len(failed_events) >= 1
    assert failed_events[0].payload.get("name") == "broken_skill"


def test_scenario_j_continuation_and_restart(canonical_registry, mock_bus):
    """Scenario J: Mission continuation preserves active skills and recovers state safely."""
    prompt = "Build a responsive static landing page with HTML, CSS, and vanilla JS"
    routing = canonical_registry.route_skills(prompt)
    assert "vanilla-web" in routing.selected_skills

    # Load active skill
    skill = canonical_registry.load_skill_body("vanilla-web")
    assert skill is not None

    # Initialize StateStore and process events
    store = StateStore(mission_id=canonical_registry.mission_id)
    reducer = StateReducer()

    for ev in mock_bus.events:
        store._state = reducer.reduce(store._state, ev)

    snapshot = store.get_snapshot()
    assert "vanilla-web" in snapshot.mission.active_skills

    # Simulate restart by restoring into a fresh registry instance
    fresh_bus = MockEventBus()
    recovered_reg = ProjectIntelligenceRegistry(
        workspace_root=REPO_ROOT,
        canonical_skills_root=CANONICAL_SKILLS_DIR,
        event_bus=fresh_bus,
        mission_id=canonical_registry.mission_id,
    )
    recovered_reg.discover()
    restored_skills = recovered_reg.restore_skills(snapshot.mission.active_skills)

    assert len(restored_skills) == len(snapshot.mission.active_skills)
    restored_names = [s.metadata.name for s in restored_skills]
    assert "vanilla-web" in restored_names
    vanilla_skill = next(s for s in restored_skills if s.metadata.name == "vanilla-web")
    assert vanilla_skill.metadata.sha256_hash == skill.metadata.sha256_hash


# ══════════════════════════════════════════════════════════════════════════════
# Section 5: Progressive Loading & Isolation Verification (Tests 1 through 10)
# ══════════════════════════════════════════════════════════════════════════════


def test_progressive_1_metadata_index_only(canonical_skill_engine):
    """Test 1: Metadata index only. Discovery indexes skills without loading bodies."""
    index = canonical_skill_engine.index_skills()
    assert len(index) >= 13

    # Ensure body cache is completely empty at Level 1
    assert len(canonical_skill_engine._body_cache) == 0

    # Ensure metadata objects do not hold body contents
    for name, meta in index.items():
        assert meta.name == name
        assert meta.description != ""
        assert isinstance(meta.triggers, list)
        assert not hasattr(meta, "body")


def test_progressive_2_body_lazy_load(canonical_skill_engine):
    """Test 2: SKILL.md body is loaded ONLY when explicitly loaded."""
    canonical_skill_engine.index_skills()
    assert "vanilla-web" not in canonical_skill_engine._body_cache

    skill = canonical_skill_engine.load_skill("vanilla-web")
    assert skill is not None
    assert skill.body != ""
    assert "vanilla-web" in canonical_skill_engine._body_cache


def test_progressive_3_unselected_skills_unloaded(canonical_skill_engine):
    """Test 3: For a task selecting 2 skills, verify remaining 11 bodies are NOT loaded."""
    canonical_skill_engine.index_skills()
    prompt = "Create a REST API with Flask and a PostgreSQL database"
    decision = canonical_skill_engine.route_skills(prompt, max_candidates=2)

    assert len(decision.selected_skills) == 2
    for s_name in decision.selected_skills:
        canonical_skill_engine.load_skill(s_name)

    # Exactly 2 skills loaded into body cache
    assert len(canonical_skill_engine._body_cache) == 2

    # Exactly 11 skills remain unloaded
    all_skill_names = set(canonical_skill_engine._metadata_index.keys())
    unselected = all_skill_names - set(decision.selected_skills)
    assert len(unselected) == len(all_skill_names) - len(decision.selected_skills)
    for unselected_name in unselected:
        assert unselected_name not in canonical_skill_engine._body_cache


def test_progressive_4_references_lazy_load(canonical_skill_engine):
    """Test 4: Supporting resource files are loaded ONLY on demand via Level 3 call."""
    canonical_skill_engine.index_skills()
    canonical_skill_engine.load_skill("vanilla-web")

    # Body loaded, but resources not pre-loaded into active memory
    content, err = canonical_skill_engine.load_skill_resource("vanilla-web", "references/guidelines.md")
    # If the file exists it returns content, if not it safely returns (None, err) without crash
    if content:
        assert isinstance(content, str)
    else:
        assert err is not None


def test_progressive_5_helper_script_discovery_no_execution(temp_workspace):
    """Test 5: Helper scripts (.sh, .py) are discovered as file paths without being executed."""
    skill_dir = temp_workspace / ".hermes" / "skills" / "scripted_skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)

    marker_file = temp_workspace / "EXECUTED_MARKER.txt"
    evil_script = (
        f"import pathlib\npathlib.Path('{marker_file.as_posix()}').write_text('PWNED')\n"
    )
    (scripts_dir / "helper.py").write_text(evil_script, encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scripted-skill\ndescription: Skill with scripts\n---\nBody\n",
        encoding="utf-8",
    )

    engine = SkillEngine(workspace_root=temp_workspace)
    helpers = engine.get_skill_helpers("scripted-skill")

    assert len(helpers) == 1
    assert helpers[0].name == "helper.py"
    # Verify script was NOT executed during discovery
    assert not marker_file.exists()


def test_progressive_6_loaded_vs_attached_distinction(canonical_registry, mock_bus):
    """Test 6: Loaded != Attached. SKILL_LOADED occurs first, SKILL_CONTEXT_ATTACHED on context sync."""
    canonical_registry.discover()
    canonical_registry.load_skill_body("vanilla-web")

    # SKILL_LOADED emitted, but not yet attached to context engine
    assert mock_bus.has_event(EventType.SKILL_LOADED)
    assert not mock_bus.has_event(EventType.SKILL_CONTEXT_ATTACHED)

    # Now attach to context engine
    ctx_engine = ContextEngine(event_bus=mock_bus, project_intelligence=canonical_registry)
    canonical_registry.sync_skills_to_context_engine(ctx_engine)

    assert mock_bus.has_event(EventType.SKILL_CONTEXT_ATTACHED)

    loaded_events = mock_bus.get_events(EventType.SKILL_LOADED)
    attached_events = mock_bus.get_events(EventType.SKILL_CONTEXT_ATTACHED)
    assert len(loaded_events) >= 1
    assert len(attached_events) >= 1


def test_progressive_7_context_prompt_inspection(canonical_registry, mock_bus):
    """Test 7: Direct inspection of assembled context pack messages confirms fencing and isolation."""
    canonical_registry.discover()
    canonical_registry.load_skill_body("vanilla-web")

    ctx_engine = ContextEngine(event_bus=mock_bus, project_intelligence=canonical_registry)
    canonical_registry.sync_skills_to_context_engine(ctx_engine)

    # Also register mandatory system and goal items
    from core.context.models import ContextItem, ContextPriority, ContextProvenance
    ctx_engine.register_item(ContextItem(
        id="sys_invariant",
        section=ContextSectionType.SYSTEM,
        content="System instructions",
        provenance=ContextProvenance(source_type=ContextSourceType.SYSTEM, source_id="core"),
        priority=ContextPriority.MANDATORY,
    ))
    ctx_engine.register_item(ContextItem(
        id="goal_primary",
        section=ContextSectionType.CURRENT_GOAL,
        content="Build vanilla site",
        provenance=ContextProvenance(source_type=ContextSourceType.USER, source_id="m1"),
        priority=ContextPriority.MANDATORY,
    ))

    pack = ctx_engine.build_context(mission_goal="Build vanilla site")
    messages = pack.to_messages()
    system_content = messages[0]["content"]

    # Fencing and tagging assertion
    assert "<skills>" in system_content
    assert '<skill name="vanilla-web"' in system_content
    assert "</skill>" in system_content
    assert "</skills>" in system_content

    # Unselected skills must NOT appear
    assert "react-frontend" not in system_content
    assert "database-design" not in system_content


def test_progressive_8_load_error_event_emission(canonical_registry, mock_bus):
    """Test 8: Trigger load failure and assert SKILL_LOAD_FAILED event emitted with details."""
    canonical_registry.discover()
    res = canonical_registry.load_skill_body("non_existent_skill_xyz")
    assert res is None

    failed_events = mock_bus.get_events(EventType.SKILL_LOAD_FAILED)
    assert len(failed_events) >= 1
    payload = failed_events[0].payload
    assert payload.get("name") == "non_existent_skill_xyz"
    assert "error" in payload
    assert payload.get("reason") == "file_missing_or_invalid"


def test_progressive_9_multi_skill_attachment(canonical_registry, mock_bus):
    """Test 9: Multi-skill composition attaches all selected skills with distinct fences."""
    canonical_registry.discover()
    canonical_registry.load_skill_body("vanilla-web")
    canonical_registry.load_skill_body("database-design")

    ctx_engine = ContextEngine(event_bus=mock_bus, project_intelligence=canonical_registry)
    canonical_registry.sync_skills_to_context_engine(ctx_engine)

    from core.context.models import ContextItem, ContextPriority, ContextProvenance
    ctx_engine.register_item(ContextItem(
        id="sys",
        section=ContextSectionType.SYSTEM,
        content="Sys",
        provenance=ContextProvenance(source_type=ContextSourceType.SYSTEM, source_id="sys"),
        priority=ContextPriority.MANDATORY,
    ))
    ctx_engine.register_item(ContextItem(
        id="goal",
        section=ContextSectionType.CURRENT_GOAL,
        content="Goal",
        provenance=ContextProvenance(source_type=ContextSourceType.USER, source_id="goal"),
        priority=ContextPriority.MANDATORY,
    ))

    pack = ctx_engine.build_context(mission_goal="Goal")
    system_content = pack.to_messages()[0]["content"]

    assert '<skill name="vanilla-web"' in system_content
    assert '<skill name="database-design"' in system_content
    assert system_content.count("<skill name=") == 2


def test_progressive_10_state_durability(canonical_registry, mock_bus):
    """Test 10: State store snapshot and reducer serialize active skills and fingerprints."""
    canonical_registry.discover()
    routing = canonical_registry.route_skills("Build a database schema for users")
    assert "database-design" in routing.selected_skills

    skill = canonical_registry.load_skill_body("database-design")
    assert skill is not None

    store = StateStore(mission_id=canonical_registry.mission_id)
    reducer = StateReducer()

    for ev in mock_bus.events:
        store._state = reducer.reduce(store._state, ev)

    snapshot = store.get_snapshot()
    assert "database-design" in snapshot.mission.active_skills

    # Check serializer to_dict and from_dict
    state_dict = snapshot.to_dict()
    assert "database-design" in state_dict.get("active_skills", [])
    assert "database-design" in state_dict.get("mission", {}).get("active_skills", [])

    from core.persistence.serializer import deserialize_runtime_state
    restored_state = deserialize_runtime_state(state_dict)
    assert "database-design" in restored_state.active_skills
    assert "database-design" in restored_state.mission.active_skills
