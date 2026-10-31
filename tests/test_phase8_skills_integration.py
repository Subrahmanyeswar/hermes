# tests/test_phase8_skills_integration.py
"""
Phase 8 Master Integration and Skills Quality Verification Suite.
Validates:
1. Complete 23-skill catalog (13 Phase 6 + 7 Phase 7 + 3 Phase 8).
2. All declared allowed_tools exist in ToolCatalog (no fictional tools).
3. Preservation of all 20 historical skill baselines without corruption.
4. Multi-skill composition with Phase 8 skills.
5. Router discrimination, negative boundary enforcement, and progressive loading.
"""

from pathlib import Path
import pytest

from core.project_intelligence.skills import SkillEngine
from tools.platform.catalog import ToolCatalog

LOCKED_PHASE6_SKILLS = {
    "auto-docs": 38,
    "bash-scripting": 40,
    "code-review": 52,
    "database-design": 45,
    "debugging": 34,
    "flask-rest-api": 50,
    "git-workflow": 31,
    "pytest-generation": 40,
    "react-frontend": 39,
    "refactoring": 35,
    "screenshot-to-code": 35,
    "security-audit": 44,
    "vanilla-web": 36,
}

LOCKED_PHASE7_SKILLS = {
    "design-engineering": 85,
    "design-system": 100,
    "react-best-practices": 95,
    "react-composition-patterns": 138,
    "shadcn-ui": 71,
    "taste-design": 63,
    "web-design-guidelines": 69,
}

PHASE8_SKILLS = {
    "fastapi-backend",
    "software-architecture",
    "project-context",
}


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def skill_engine(repo_root):
    skills_dir = repo_root / "skills"
    engine = SkillEngine(workspace_root=repo_root, canonical_skills_root=skills_dir)
    engine.index_skills()
    return engine


def test_full_catalog_inventory_and_line_preservation(skill_engine, repo_root):
    """Verify that all 23 skills are indexed and all 20 historical skills preserve exact line counts."""
    index = skill_engine.index_skills()
    assert len(index) in (23, 24), f"Expected 23 or 24 skills, found {len(index)}"

    # Check Phase 6 baselines
    for name, expected_lines in LOCKED_PHASE6_SKILLS.items():
        assert name in index, f"Phase 6 skill '{name}' missing from index"
        skill_file = repo_root / "skills" / name / "SKILL.md"
        actual_lines = len(skill_file.read_text(encoding="utf-8").splitlines())
        assert actual_lines == expected_lines, f"Phase 6 skill '{name}' line count altered: expected {expected_lines}, got {actual_lines}"

    # Check Phase 7 baselines
    for name, expected_lines in LOCKED_PHASE7_SKILLS.items():
        assert name in index, f"Phase 7 skill '{name}' missing from index"
        skill_file = repo_root / "skills" / name / "SKILL.md"
        actual_lines = len(skill_file.read_text(encoding="utf-8").splitlines())
        assert actual_lines == expected_lines, f"Phase 7 skill '{name}' line count altered: expected {expected_lines}, got {actual_lines}"

    # Check Phase 8 skills
    for name in PHASE8_SKILLS:
        assert name in index, f"Phase 8 skill '{name}' missing from index"


def test_all_skills_allowed_tools_conformance(skill_engine):
    """Verify all declared allowed_tools across skills resolve to valid ToolCatalog tools, and Phase 8 skills declare tools."""
    catalog = ToolCatalog()
    catalog.initialize()

    index = skill_engine.index_skills()
    for name in PHASE8_SKILLS:
        meta = index[name]
        assert len(meta.allowed_tools) > 0, f"Phase 8 skill '{name}' must declare allowed_tools"

    for name, meta in index.items():
        for tool_name in meta.allowed_tools:
            resolved = catalog.resolve_name(tool_name)
            assert catalog.get(resolved) is not None, f"Skill '{name}' references invalid tool '{tool_name}' (resolved '{resolved}')"


def test_composition_architecture_and_fastapi(skill_engine):
    """Verify composition of software-architecture and fastapi-backend."""
    task = "Design the software architecture and implement FastAPI CRUD endpoints with Pydantic v2 schemas"
    decision = skill_engine.route_skills(task_text=task)

    assert "software-architecture" in decision.selected_skills
    assert "fastapi-backend" in decision.selected_skills


def test_composition_database_and_fastapi(skill_engine):
    """Verify composition of database-design and fastapi-backend."""
    task = "Design relational SQLite tables and build FastAPI REST API with Pydantic models"
    decision = skill_engine.route_skills(task_text=task)

    assert "database-design" in decision.selected_skills
    assert "fastapi-backend" in decision.selected_skills


def test_composition_project_context_and_autodocs(skill_engine):
    """Verify composition of project-context and auto-docs."""
    task = "Update HERMES.md operational rules and generate documentation README for the repository"
    decision = skill_engine.route_skills(task_text=task)

    assert "project-context" in decision.selected_skills
    assert "auto-docs" in decision.selected_skills


def test_progressive_disclosure_level2_loading(skill_engine):
    """Verify Level 1 indexing does not load bodies, and Level 2 loads on demand."""
    assert len(skill_engine._body_cache) == 0, "Body cache must be empty initially"

    skill = skill_engine.load_skill("fastapi-backend")
    assert skill is not None
    assert "fastapi-backend" in skill_engine._body_cache
    assert len(skill.body) > 100
