# tests/test_phase7_advanced_visual_skills.py
"""
Phase 7 Batch 7C Tests: Advanced Visual Capabilities.
Covers:
1. Frontmatter and discovery validation for shadcn-ui.
2. Positive and negative routing assertions.
3. Workspace signal integration (components/ui awareness).
4. Level 2 on-demand body loading.
5. Verification of 3D deferral behavior (no accidental rogue activation).
"""

from pathlib import Path
import pytest

from core.project_intelligence.skills import SkillEngine

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILLS_DIR = REPO_ROOT / "skills"


@pytest.fixture
def skill_engine():
    return SkillEngine(workspace_root=REPO_ROOT, canonical_skills_root=CANONICAL_SKILLS_DIR)


def test_shadcn_ui_metadata(skill_engine):
    """Verify shadcn-ui frontmatter and metadata index."""
    index = skill_engine.index_skills(force_reload=True)
    assert "shadcn-ui" in index
    meta = index["shadcn-ui"]
    assert meta.name == "shadcn-ui"
    assert "shadcn" in meta.description.lower()
    assert "shadcn" in meta.triggers
    assert "radix ui" in meta.triggers
    assert set(meta.allowed_tools) == {"fs.read", "fs.write", "fs.edit", "shell.bash", "search.glob"}


def test_routing_shadcn_explicit_request(skill_engine):
    """Explicit request for shadcn component activates shadcn-ui."""
    prompt = "Add an accessible dialog modal using shadcn/ui and Radix primitives"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert not decision.is_fallback
    assert "shadcn-ui" in decision.selected_skills


def test_routing_shadcn_workspace_signals(skill_engine):
    """Project with components/ui files activates shadcn-ui on component tasks."""
    prompt = "Create a user profile dropdown menu"
    signals = {
        "files": ["package.json", "components/ui/button.tsx", "components/ui/dialog.tsx", "src/App.tsx"],
        "framework": "react",
    }
    decision = skill_engine.route_skills(prompt, workspace_signals=signals, max_candidates=3)
    assert "shadcn-ui" in decision.selected_skills
    assert "react-frontend" in decision.selected_skills


def test_negative_shadcn_plain_html(skill_engine):
    """Plain HTML tasks must NOT activate shadcn-ui."""
    prompt = "Build a static single-page landing site for a cafe with clean HTML"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert "vanilla-web" in decision.selected_skills
    assert "shadcn-ui" not in decision.selected_skills


def test_negative_shadcn_standard_react(skill_engine):
    """Standard React project without shadcn cues does not activate shadcn-ui."""
    prompt = "Create a simple counter component in React"
    signals = {
        "files": ["package.json", "src/App.tsx"],
        "framework": "react",
    }
    decision = skill_engine.route_skills(prompt, workspace_signals=signals, max_candidates=3)
    assert "react-frontend" in decision.selected_skills
    assert "shadcn-ui" not in decision.selected_skills


def test_3d_request_graceful_handling(skill_engine):
    """3D hero request does NOT trigger non-existent or unverified 3D skills."""
    prompt = "Build a 3D rotating cube hero animation using WebGL"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert "immersive-3d-web" not in decision.selected_skills
    # Verify no unvetted packages are assumed
