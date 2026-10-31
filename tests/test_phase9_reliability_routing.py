"""
Test Phase 9: Reliability Skill Routing, Precision, and Disambiguation.

Validates:
1. Exact positive routing for reliability skills:
   - security-audit
   - powershell-scripting
   - bash-scripting
   - git-workflow
   - debugging
   - code-review
   - pytest-generation
2. Rejection of pure conceptual, definitional, or informational queries:
   - "Explain what a code review is"
   - "What is the difference between git rebase and git merge?"
   - "What does a security audit mean?"
   - "How does PowerShell handle object pipelines compared to bash text streams?"
   - "What is property-based testing in Python?"
   - "Why is debugging hard?"
3. Precision cross-platform disambiguation (powershell-scripting vs bash-scripting).
"""

from pathlib import Path
import pytest
from core.project_intelligence.skills import SkillEngine

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILLS_DIR = REPO_ROOT / "skills"


@pytest.fixture
def skill_engine():
    return SkillEngine(
        workspace_root=REPO_ROOT,
        canonical_skills_root=CANONICAL_SKILLS_DIR,
    )


class TestPhase9ReliabilityPositiveRouting:
    def test_security_audit_positive(self, skill_engine):
        prompt = "Audit this repository for security vulnerabilities and dangerous patterns"
        decision = skill_engine.route_skills(prompt)
        assert "security-audit" in decision.selected_skills
        assert "web-design-guidelines" not in decision.selected_skills

    def test_powershell_scripting_positive(self, skill_engine):
        prompt = "Write a powershell script to automate the Windows build and test sequence"
        decision = skill_engine.route_skills(prompt)
        assert "powershell-scripting" in decision.selected_skills
        assert "bash-scripting" not in decision.selected_skills

    def test_bash_scripting_positive(self, skill_engine):
        prompt = "Write a bash deployment script for our Linux servers"
        decision = skill_engine.route_skills(prompt)
        assert "bash-scripting" in decision.selected_skills
        assert "powershell-scripting" not in decision.selected_skills

    def test_git_workflow_positive(self, skill_engine):
        prompt = "Set up a git pre-commit hook and branching workflow"
        decision = skill_engine.route_skills(prompt)
        assert "git-workflow" in decision.selected_skills

    def test_debugging_positive(self, skill_engine):
        prompt = "Debug this failing test and isolate the root cause"
        decision = skill_engine.route_skills(prompt)
        assert "debugging" in decision.selected_skills

    def test_code_review_positive(self, skill_engine):
        prompt = "Review this PR for code quality and maintainability"
        decision = skill_engine.route_skills(prompt)
        assert "code-review" in decision.selected_skills

    def test_pytest_generation_positive(self, skill_engine):
        prompt = "Generate a comprehensive test suite for this module"
        decision = skill_engine.route_skills(prompt)
        assert "pytest-generation" in decision.selected_skills


class TestPhase9ConceptualNegativeRouting:
    """Verifies that purely conceptual, definitional, or explanatory prompts do not activate operational skills."""

    @pytest.mark.parametrize(
        "prompt,forbidden_skill",
        [
            ("Explain what a code review is", "code-review"),
            ("What is the difference between git rebase and git merge?", "git-workflow"),
            ("What does a security audit mean?", "security-audit"),
            ("How does PowerShell handle object pipelines compared to bash text streams?", "powershell-scripting"),
            ("How does PowerShell handle object pipelines compared to bash text streams?", "bash-scripting"),
            ("What is property-based testing in Python?", "pytest-generation"),
            ("Why is debugging hard?", "debugging"),
        ],
    )
    def test_conceptual_prompts_suppressed(self, skill_engine, prompt, forbidden_skill):
        decision = skill_engine.route_skills(prompt)
        assert forbidden_skill not in decision.selected_skills, (
            f"Skill '{forbidden_skill}' was falsely matched for conceptual prompt: '{prompt}'"
        )
        # For these conceptual questions without workspace files, no operational skills should trigger
        assert len(decision.selected_skills) == 0, (
            f"Expected empty match for conceptual prompt '{prompt}', got: {decision.selected_skills}"
        )


class TestPhase9Disambiguation:
    def test_powershell_vs_bash_disambiguation(self, skill_engine):
        ps_prompt = "Write a PowerShell script to automate deployment"
        bash_prompt = "Write a Bash script to automate deployment"

        ps_decision = skill_engine.route_skills(ps_prompt)
        bash_decision = skill_engine.route_skills(bash_prompt)

        assert "powershell-scripting" in ps_decision.selected_skills
        assert "bash-scripting" not in ps_decision.selected_skills

        assert "bash-scripting" in bash_decision.selected_skills
        assert "powershell-scripting" not in bash_decision.selected_skills
