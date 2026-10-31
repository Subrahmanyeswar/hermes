# tests/test_phase8_fastapi_skill.py
"""
Focused tests for Phase 8 Skill 1: fastapi-backend
Verifies:
1. Metadata parsing and valid frontmatter.
2. Permitted tools conformance with ToolCatalog.
3. Content quality (lifespan, Pydantic v2, APIRouter, negative boundaries).
4. Router precision (FastAPI selection, Flask discrimination, workspace signals).
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


def test_fastapi_metadata_conformance(skill_engine):
    """Verify that fastapi-backend metadata parses properly and has correct fields."""
    index = skill_engine.index_skills()
    assert "fastapi-backend" in index, "fastapi-backend must be indexed"

    meta = index["fastapi-backend"]
    assert meta.name == "fastapi-backend"
    assert "FastAPI" in meta.description or "fastapi" in meta.description.lower()
    assert meta.priority >= 1
    assert len(meta.triggers) >= 3
    assert any("fastapi" in t for t in meta.triggers)

    # Tool conformance
    catalog = ToolCatalog()
    catalog.initialize()
    for tool_name in meta.allowed_tools:
        resolved = catalog.resolve_name(tool_name)
        assert catalog.get(resolved) is not None, f"Tool '{tool_name}' must exist in ToolCatalog"


def test_fastapi_skill_content(skill_engine):
    """Verify SKILL.md body adheres to Phase 8 quality standards and invariants."""
    skill = skill_engine.load_skill("fastapi-backend")
    assert skill is not None
    body = skill.body

    # Lifespan
    assert "lifespan" in body.lower()
    assert "@asynccontextmanager" in body

    # Pydantic v2
    assert "model_dump" in body
    assert "ConfigDict" in body
    assert "Field" in body

    # Router & negative boundaries
    assert "APIRouter" in body
    assert "negative boundaries" in body.lower() or "anti-patterns" in body.lower()
    assert "flask" in body.lower()


def test_routing_selects_fastapi_over_flask(skill_engine):
    """Ensure explicit FastAPI prompt routes to fastapi-backend and not flask-rest-api."""
    task = "Build a high performance async FastAPI backend with Pydantic v2 schemas and modular routers"
    decision = skill_engine.route_skills(task_text=task)

    assert "fastapi-backend" in decision.selected_skills
    assert "flask-rest-api" not in decision.selected_skills


def test_routing_selects_flask_over_fastapi(skill_engine):
    """Ensure explicit Flask prompt routes to flask-rest-api and not fastapi-backend."""
    task = "Implement a Flask REST API with blueprint routing and request context"
    decision = skill_engine.route_skills(task_text=task)

    assert "flask-rest-api" in decision.selected_skills
    assert "fastapi-backend" not in decision.selected_skills


def test_routing_fastapi_workspace_signal(skill_engine):
    """Ensure workspace containing FastAPI main.py and generic API intent routes to fastapi-backend."""
    task = "Add new CRUD endpoints for user registration and profile management"
    ws_signals = {
        "files": ["main.py", "routers/users.py"],
        "framework": "fastapi",
    }
    decision = skill_engine.route_skills(task_text=task, workspace_signals=ws_signals)

    assert "fastapi-backend" in decision.selected_skills
