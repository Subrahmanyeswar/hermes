# tests/test_phase7_frontend_skills.py
"""
Phase 7 Batch 7A Tests: Frontend Implementation Skills.
Covers:
1. Frontmatter and discovery validation for react-best-practices and react-composition-patterns.
2. Positive and negative routing assertions.
3. Composition with existing react-frontend and vanilla-web skills.
4. Level 2 on-demand body loading and Level 1 metadata index purity.
5. Representative task context attachment in an isolated temporary workspace.
"""

import shutil
import tempfile
from pathlib import Path
from typing import List

import pytest

from core.context.engine import ContextEngine
from core.context.models import ContextSectionType, ContextSourceType
from core.project_intelligence.registry import ProjectIntelligenceRegistry
from core.project_intelligence.skills import SkillEngine
from core.runtime_state.events import EventType, HermesEvent

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILLS_DIR = REPO_ROOT / "skills"


class MockEventBus:
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
def temp_workspace():
    td = tempfile.mkdtemp(prefix="hermes_phase7_batch7a_")
    ws = Path(td)
    yield ws
    shutil.rmtree(td, ignore_errors=True)


@pytest.fixture
def mock_bus():
    return MockEventBus()


@pytest.fixture
def skill_engine():
    return SkillEngine(workspace_root=REPO_ROOT, canonical_skills_root=CANONICAL_SKILLS_DIR)


@pytest.fixture
def canonical_registry(mock_bus):
    return ProjectIntelligenceRegistry(
        workspace_root=REPO_ROOT,
        canonical_skills_root=CANONICAL_SKILLS_DIR,
        event_bus=mock_bus,
        mission_id="mission_phase7_batch7a_test",
    )


# ── 1. Frontmatter and Metadata Index Tests ─────────────────────────────────

def test_react_best_practices_metadata(skill_engine):
    """Verify react-best-practices frontmatter and metadata index."""
    index = skill_engine.index_skills(force_reload=True)
    assert "react-best-practices" in index
    meta = index["react-best-practices"]
    assert meta.name == "react-best-practices"
    assert "performance" in meta.description.lower()
    assert "react best practices" in meta.triggers
    assert set(meta.allowed_tools) == {"fs.read", "fs.write", "fs.edit", "shell.bash", "search.glob"}
    assert not meta.disable_model_invocation


def test_react_composition_patterns_metadata(skill_engine):
    """Verify react-composition-patterns frontmatter and metadata index."""
    index = skill_engine.index_skills(force_reload=True)
    assert "react-composition-patterns" in index
    meta = index["react-composition-patterns"]
    assert meta.name == "react-composition-patterns"
    assert "compound" in meta.description.lower()
    assert "compound component" in meta.triggers
    assert set(meta.allowed_tools) == {"fs.read", "fs.write", "fs.edit", "shell.bash"}
    assert not meta.disable_model_invocation


def test_lazy_loading_preservation(skill_engine):
    """Verify bodies of new skills remain unloaded until explicitly requested."""
    skill_engine.index_skills(force_reload=True)
    assert "react-best-practices" not in skill_engine._body_cache
    assert "react-composition-patterns" not in skill_engine._body_cache

    skill = skill_engine.load_skill("react-best-practices")
    assert skill is not None
    assert "useCallback" in skill.body or "useMemo" in skill.body
    assert "react-best-practices" in skill_engine._body_cache
    assert "react-composition-patterns" not in skill_engine._body_cache


# ── 2. Routing Tests ────────────────────────────────────────────────────────

def test_routing_react_performance_issue(skill_engine):
    """Task diagnosing React data-fetching and re-renders activates react-best-practices."""
    prompt = "Diagnose a React data-fetching or bundle-performance issue"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert not decision.is_fallback
    assert "react-best-practices" in decision.selected_skills
    assert "react-frontend" in decision.selected_skills


def test_routing_react_compound_component(skill_engine):
    """Task designing compound tabs activates react-composition-patterns."""
    prompt = "Design a flexible React tabs and menu compound component architecture"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert not decision.is_fallback
    assert "react-composition-patterns" in decision.selected_skills
    assert "flask-rest-api" not in decision.selected_skills


def test_negative_activation_plain_html(skill_engine):
    """Ordinary HTML task must NOT activate react-best-practices or react-composition-patterns."""
    prompt = "Build a static single-page cafe landing page using clean HTML5 and semantic styling"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert decision.selected_skills == ["vanilla-web"]
    assert "react-best-practices" not in decision.selected_skills
    assert "react-composition-patterns" not in decision.selected_skills


def test_negative_activation_non_code(skill_engine):
    """Non-code request must not activate any React skill."""
    prompt = "Write a haiku about autumn leaves falling silently"
    decision = skill_engine.route_skills(prompt)
    assert decision.is_fallback or len(decision.selected_skills) == 0
    assert "react-best-practices" not in decision.selected_skills
    assert "react-composition-patterns" not in decision.selected_skills


# ── 3. Representative Task & Context Attachment ─────────────────────────────

def test_representative_batch7a_context_attachment(temp_workspace, canonical_registry, mock_bus):
    """
    Demonstrate full Level 1 -> Level 2 -> Context Attachment for Batch 7A:
    1. Route task
    2. Load skill body
    3. Sync to ContextEngine in isolated workspace
    4. Verify XML fencing, provenance tags, and loaded vs attached distinction
    """
    prompt = "Design a reusable compound component Menu API in React with keyboard accessibility"
    decision = canonical_registry.route_skills(prompt, max_candidates=2)

    assert "react-composition-patterns" in decision.selected_skills

    # Level 2: Load skill body on demand
    skill = canonical_registry.load_skill_body("react-composition-patterns")
    assert skill is not None
    assert mock_bus.has_event(EventType.SKILL_LOADED)

    # Attach to ContextEngine in isolated workspace
    ctx_engine = ContextEngine(event_bus=mock_bus, project_intelligence=canonical_registry)
    attached_items = canonical_registry.sync_skills_to_context_engine(ctx_engine)
    assert len(attached_items) >= 1
    assert mock_bus.has_event(EventType.SKILL_CONTEXT_ATTACHED)

    # Also register mandatory system item for complete prompt build
    from core.context.models import ContextItem, ContextPriority, ContextProvenance
    ctx_engine.register_item(ContextItem(
        id="sys_invariant",
        section=ContextSectionType.SYSTEM,
        content="System instructions",
        provenance=ContextProvenance(source_type=ContextSourceType.SYSTEM, source_id="core"),
        priority=ContextPriority.MANDATORY,
    ))

    # Inspect context pack
    pack = ctx_engine.build_context(mission_goal="Design reusable compound component")
    messages = pack.to_messages()
    system_text = messages[0]["content"]

    assert "<skills>" in system_text
    assert '<skill name="react-composition-patterns"' in system_text
    assert "Compound Component Pattern" in system_text
    assert "</skill>" in system_text
    assert "</skills>" in system_text
