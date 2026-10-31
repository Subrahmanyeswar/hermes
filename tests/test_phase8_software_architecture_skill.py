# tests/test_phase8_software_architecture_skill.py
"""
Focused tests for Phase 8 Skill 2: software-architecture
Verifies:
1. Metadata parsing and valid frontmatter.
2. Permitted tools conformance with ToolCatalog.
3. Content quality (C4 model tiers, ADR format, dependency rules, negative boundaries).
4. Router precision (Architecture vs Refactoring distinction, workspace signals).
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


def test_software_architecture_metadata(skill_engine):
    """Verify metadata indexing and tool conformance for software-architecture."""
    index = skill_engine.index_skills()
    assert "software-architecture" in index, "software-architecture must be indexed"

    meta = index["software-architecture"]
    assert meta.name == "software-architecture"
    assert "architecture" in meta.description.lower()
    assert meta.priority >= 1
    assert len(meta.triggers) >= 4
    assert any("c4" in t.lower() for t in meta.triggers)

    catalog = ToolCatalog()
    catalog.initialize()
    for tool_name in meta.allowed_tools:
        resolved = catalog.resolve_name(tool_name)
        assert catalog.get(resolved) is not None, f"Tool '{tool_name}' must exist in ToolCatalog"


def test_software_architecture_content(skill_engine):
    """Verify SKILL.md body contains C4 model tiers, ADR template, and negative boundaries."""
    skill = skill_engine.load_skill("software-architecture")
    assert skill is not None
    body = skill.body

    # C4 Model tiers
    assert "System Context" in body
    assert "Container" in body
    assert "Component" in body

    # ADR Standard
    assert "Architecture Decision Record" in body or "ADR" in body
    assert "Status" in body
    assert "Consequences" in body

    # Invariants & Negative boundaries
    assert "Unidirectional Dependency Flow" in body or "unidirectional" in body.lower()
    assert "microservices" in body.lower()
    assert "refactoring" in body.lower()


def test_routing_selects_software_architecture_for_system_design(skill_engine):
    """Verify that high-level system decomposition and C4 documentation routes to software-architecture."""
    task = "Design the software architecture and C4 component diagrams for the new telemetry subsystem"
    decision = skill_engine.route_skills(task_text=task)

    assert "software-architecture" in decision.selected_skills


def test_routing_distinguishes_architecture_from_code_refactoring(skill_engine):
    """Verify that local method refactoring selects refactoring without polluting software-architecture."""
    task = "Refactor this helper function to simplify loop nesting, extract function, and clean up dead code"
    decision = skill_engine.route_skills(task_text=task)

    assert "refactoring" in decision.selected_skills
    assert "software-architecture" not in decision.selected_skills
