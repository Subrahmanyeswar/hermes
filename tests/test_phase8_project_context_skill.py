# tests/test_phase8_project_context_skill.py
"""
Focused tests for Phase 8 Skill 3: project-context
Verifies:
1. Metadata parsing and valid frontmatter.
2. Permitted tools conformance with ToolCatalog.
3. Content quality (HERMES.md / AGENTS.md structure, truthfulness, distinction from auto-docs).
4. Router precision (Project context vs auto-docs distinction, workspace signals).
"""

from pathlib import Path
import pytest

from core.project_intelligence.skills import SkillEngine
from tools.platform.catalog import ToolCatalog


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def skill_engine(repo_root):
    skills_dir = repo_root / "skills"
    engine = SkillEngine(workspace_root=repo_root, canonical_skills_root=skills_dir)
    engine.index_skills()
    return engine


def test_project_context_metadata(skill_engine):
    """Verify metadata indexing and tool conformance for project-context."""
    index = skill_engine.index_skills()
    assert "project-context" in index, "project-context must be indexed"

    meta = index["project-context"]
    assert meta.name == "project-context"
    assert "context" in meta.description.lower()
    assert meta.priority >= 1
    assert len(meta.triggers) >= 4
    assert any("hermes.md" in t.lower() for t in meta.triggers)

    catalog = ToolCatalog()
    catalog.initialize()
    for tool_name in meta.allowed_tools:
        resolved = catalog.resolve_name(tool_name)
        assert catalog.get(resolved) is not None, f"Tool '{tool_name}' must exist in ToolCatalog"


def test_project_context_content(skill_engine):
    """Verify SKILL.md body contains HERMES.md/AGENTS.md guidance, anti-bloat rules, and negative boundaries."""
    skill = skill_engine.load_skill("project-context")
    assert skill is not None
    body = skill.body

    # File types
    assert "HERMES.md" in body
    assert "AGENTS.md" in body

    # Operational sections
    assert "Canonical Environment" in body or "Environment" in body
    assert "Guardrails" in body or "Prohibitions" in body

    # Distinction from auto-docs
    assert "auto-docs" in body.lower()
    assert "bloat" in body.lower()


def test_routing_selects_project_context(skill_engine):
    """Verify that task targeting repository context files selects project-context."""
    task = "Update HERMES.md and AGENTS.md with the canonical environment paths and rule hierarchy"
    decision = skill_engine.route_skills(task_text=task)

    assert "project-context" in decision.selected_skills


def test_routing_distinguishes_context_from_code_autodocs(skill_engine):
    """Verify that code docstring generation selects auto-docs without polluting project-context."""
    task = "Generate docstrings for all python functions and classes in the parser module"
    decision = skill_engine.route_skills(task_text=task)

    assert "auto-docs" in decision.selected_skills
    assert "project-context" not in decision.selected_skills


def test_routing_project_context_workspace_signal(skill_engine):
    """Verify workspace context signal boosts project-context."""
    task = "Synchronize repo guidelines with latest changes"
    ws_signals = {
        "files": ["HERMES.md", "core/main.py"],
    }
    decision = skill_engine.route_skills(task_text=task, workspace_signals=ws_signals)

    assert "project-context" in decision.selected_skills
