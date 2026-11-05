# tests/test_p0_skill_alignment_and_shell_execution.py
"""
Focused Verification Suite for HERMES 2.x P0 Skill Alignment and Shell Execution Integration.
Covers all 15 explicit test requirements from prompt 10:
  1. All four mandatory UI skills are preserved during frontend routing.
  2. Vanilla-web is selected for vanilla projects.
  3. React frontend skill is selected for React projects.
  4. React specialists are selected only when relevant.
  5. Design-system cannot be displaced by optional skills or candidate limits.
  6. Backend/database skills are suppressed under explicit negative constraints.
  7. PowerShell guidance is selected for Windows PowerShell execution.
  8. Bash guidance is selected for genuine Bash execution.
  9. PowerShell and Bash commands are not mixed.
  10. package.json is inspected before choosing npm test.
  11. Native executable exit codes are preserved.
  12. Command failures receive accurate classifications.
  13. INJECTED and APPLIED skill states remain distinct.
  14. A generic passing validator does not falsely mark every skill APPLIED.
  15. Existing frontend skill and large-mission regression tests continue to pass.
"""

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_SKILLS_DIR = REPO_ROOT / "skills"

from core.project_intelligence.skills import SkillEngine
from core.frontend_contract_validator import FrontendContractValidator, FrontendValidationReport
from core.design_intelligence import DesignBriefGenerator
from tools.shell_tools import BashExecTool, _command_for_platform


@pytest.fixture
def skill_engine():
    """SkillEngine pointed to canonical repository skills/ directory."""
    engine = SkillEngine(
        workspace_root=REPO_ROOT,
        canonical_skills_root=CANONICAL_SKILLS_DIR,
    )
    engine.index_skills()
    return engine


@pytest.fixture
def temp_workspace():
    """Isolated temporary workspace directory."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td).resolve()
        yield ws


# ==============================================================================
# 1. Mandatory UI Foundation Bundle & Preservation
# ==============================================================================

def test_req1_all_four_mandatory_ui_skills_preserved_during_frontend_routing(skill_engine):
    """Req 1: Every UI-bearing mission preserves all four core UI skills."""
    prompt = "Build a modern travel agency website with destination cards and booking modal"
    decision = skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "taste-design" in decision.selected_skills
    assert "design-engineering" in decision.selected_skills
    assert "design-system" in decision.selected_skills
    assert "web-design-guidelines" in decision.selected_skills
    assert decision.candidate_scores["taste-design"] >= 0.30
    assert decision.candidate_scores["design-engineering"] >= 0.30
    assert decision.candidate_scores["design-system"] >= 0.30
    assert decision.candidate_scores["web-design-guidelines"] >= 0.30


# ==============================================================================
# 2. Technology-Specific Frontend Skill: Vanilla Web
# ==============================================================================

def test_req2_vanilla_web_selected_for_vanilla_projects(skill_engine):
    """Req 2: Vanilla web projects select vanilla-web and exclude React specialists."""
    prompt = "Build static travel website"
    decision = skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "vanilla-web" in decision.selected_skills
    assert "react-frontend" not in decision.selected_skills
    assert "react-best-practices" not in decision.selected_skills
    assert "react-composition-patterns" not in decision.selected_skills


# ==============================================================================
# 3. Technology-Specific Frontend Skill: React Frontend
# ==============================================================================

def test_req3_react_frontend_selected_for_react_projects(skill_engine):
    """Req 3: React applications select react-frontend and exclude vanilla-web."""
    prompt = "Build React application"
    decision = skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "react-frontend" in decision.selected_skills
    assert "vanilla-web" not in decision.selected_skills
    assert "taste-design" in decision.selected_skills
    assert "design-engineering" in decision.selected_skills
    assert "design-system" in decision.selected_skills
    assert "web-design-guidelines" in decision.selected_skills


# ==============================================================================
# 4. React Specialists Selected Only When Relevant
# ==============================================================================

def test_req4_react_specialists_selected_only_when_relevant(skill_engine):
    """Req 4: React specialists (composition, performance, shadcn) selected only when requested."""
    # A. Generic React prompt does NOT trigger composition or performance specialists
    prompt_generic = "Build React application for customer portal"
    decision_generic = skill_engine.route_skills(prompt_generic)
    assert "react-frontend" in decision_generic.selected_skills
    assert "react-composition-patterns" not in decision_generic.selected_skills
    assert "react-best-practices" not in decision_generic.selected_skills
    assert "shadcn-ui" not in decision_generic.selected_skills

    # B. Complex component task activates react-composition-patterns
    prompt_comp = "Build React dashboard with complex components"
    decision_comp = skill_engine.route_skills(prompt_comp)
    assert "react-frontend" in decision_comp.selected_skills
    assert "react-composition-patterns" in decision_comp.selected_skills

    # C. Performance / re-render diagnosis activates react-best-practices
    prompt_perf = "Diagnose a React data-fetching and re-renders performance bottleneck"
    decision_perf = skill_engine.route_skills(prompt_perf)
    assert "react-frontend" in decision_perf.selected_skills
    assert "react-best-practices" in decision_perf.selected_skills

    # D. Explicit shadcn/ui requirement activates shadcn-ui
    prompt_shadcn = "Build a modern dashboard using shadcn/ui components"
    decision_shadcn = skill_engine.route_skills(prompt_shadcn)
    assert "shadcn-ui" in decision_shadcn.selected_skills


# ==============================================================================
# 5. Design-System Cannot Be Displaced By Optional Skills
# ==============================================================================

def test_req5_design_system_cannot_be_displaced_by_optional_skills(skill_engine):
    """Req 5: design-system is never displaced by optional skills or max_candidates limit."""
    # Even when max_candidates=4 is passed, all 4 UI skills + primary tech are preserved
    prompt = "Build a modern travel agency website with destination cards, booking modal, and SQLite database"
    decision = skill_engine.route_skills(prompt, max_candidates=4)

    assert "design-system" in decision.selected_skills
    assert "taste-design" in decision.selected_skills
    assert "design-engineering" in decision.selected_skills
    assert "web-design-guidelines" in decision.selected_skills
    assert "vanilla-web" in decision.selected_skills


# ==============================================================================
# 6. Negative Constraints Suppress Backend & Database Skills
# ==============================================================================

def test_req6_backend_and_database_skills_suppressed_under_negative_constraints(skill_engine):
    """Req 6: Explicit negative constraints prevent backend and database skill activation."""
    prompt = "Build a rich travel showcase website with no backend and no database, vanilla JS only"
    decision = skill_engine.route_skills(prompt)

    assert "database-design" not in decision.selected_skills
    assert "flask-rest-api" not in decision.selected_skills
    assert "fastapi-backend" not in decision.selected_skills
    assert "vanilla-web" in decision.selected_skills
    assert "database-design" in decision.rejection_reasons
    assert "flask-rest-api" in decision.rejection_reasons


# ==============================================================================
# 7. Environment-Aware PowerShell Routing
# ==============================================================================

def test_req7_powershell_guidance_routed_for_windows_execution(skill_engine):
    """Req 7: Windows PowerShell execution activates powershell-scripting without requiring 'PowerShell' keyword."""
    prompt = "Fix npm command failures on Windows"
    decision = skill_engine.route_skills(prompt)

    assert "powershell-scripting" in decision.selected_skills
    assert "debugging" in decision.selected_skills
    assert "bash-scripting" not in decision.selected_skills


# ==============================================================================
# 8. Environment-Aware Bash Routing
# ==============================================================================

def test_req8_bash_guidance_routed_for_genuine_bash_execution(skill_engine):
    """Req 8: Genuine Linux/Bash script execution activates bash-scripting."""
    prompt = "Create Linux automation script"
    decision = skill_engine.route_skills(prompt)

    assert "bash-scripting" in decision.selected_skills
    assert "powershell-scripting" not in decision.selected_skills


# ==============================================================================
# 9. PowerShell and Bash Commands Not Mixed
# ==============================================================================

def test_req9_powershell_and_bash_commands_not_mixed(skill_engine):
    """Req 9: PowerShell and Bash execution skills and syntax are not mixed."""
    # A. Routing mutual exclusivity
    ps_decision = skill_engine.route_skills("Fix npm command failures on Windows")
    bash_decision = skill_engine.route_skills("Create Linux automation script")
    assert "bash-scripting" not in ps_decision.selected_skills
    assert "powershell-scripting" not in bash_decision.selected_skills

    # B. Shell tool command translation avoids mixing syntax
    translated_export = _command_for_platform("export NODE_ENV=production")
    if sys.platform == "win32":
        assert "set NODE_ENV=production" in translated_export
        assert "export" not in translated_export


# ==============================================================================
# 10. package.json Inspected Before Running npm test
# ==============================================================================

def test_req10_package_json_inspected_before_choosing_npm_test(temp_workspace):
    """Req 10: package.json is inspected before npm test; missing scripts fail cleanly with code 1."""
    tool = BashExecTool()

    # Case A: package.json does not exist
    res_no_pkg = tool.execute(BashExecTool.Input(command="npm test", working_dir=str(temp_workspace)))
    assert not res_no_pkg.success
    assert res_no_pkg.exit_code == 1
    assert res_no_pkg.details.get("classification") == "MISSING_PACKAGE_JSON"
    assert "package.json" in res_no_pkg.error

    # Case B: package.json exists but lacks 'test' script
    pkg_file = temp_workspace / "package.json"
    pkg_file.write_text(json.dumps({"name": "test-app", "scripts": {"build": "node build.js"}}), encoding="utf-8")
    res_no_test = tool.execute(BashExecTool.Input(command="npm test", working_dir=str(temp_workspace)))
    assert not res_no_test.success
    assert res_no_test.exit_code == 1
    assert res_no_test.details.get("classification") == "MISSING_TEST_SCRIPT"
    assert "no 'test' script is defined" in res_no_test.error


# ==============================================================================
# 11. Native Executable Exit Codes Preserved
# ==============================================================================

def test_req11_native_executable_exit_codes_preserved(temp_workspace):
    """Req 11: Native process exit codes (e.g. 42, 3) are preserved without artificial overrides."""
    tool = BashExecTool()
    script = temp_workspace / "exit_code_test.py"
    script.write_text("import sys; sys.exit(42)\n", encoding="utf-8")

    res = tool.execute(BashExecTool.Input(command=f"python {script.name}", working_dir=str(temp_workspace)))
    assert not res.success
    assert res.exit_code == 42
    assert res.details["exit_code"] == 42


# ==============================================================================
# 12. Command Failures Receive Accurate Classifications
# ==============================================================================

def test_req12_command_failures_receive_accurate_classifications(temp_workspace):
    """Req 12: Command failures receive accurate classifications in execution telemetry."""
    tool = BashExecTool()

    # Command not found classification
    res_not_found = tool.execute(BashExecTool.Input(command="non_existent_executable_binary_12345", working_dir=str(temp_workspace)))
    assert not res_not_found.success
    assert res_not_found.details["classification"] == "COMMAND_NOT_FOUND"

    # Security blocked classification
    res_blocked = tool.execute(BashExecTool.Input(command="sudo rm -rf /", working_dir=str(temp_workspace)))
    assert not res_blocked.success
    assert res_blocked.exit_code == 126


# ==============================================================================
# 13. INJECTED and APPLIED Skill States Remain Distinct
# ==============================================================================

def test_req13_injected_and_applied_skill_states_remain_distinct(temp_workspace):
    """Req 13: INJECTED and APPLIED skill states remain distinct; APPLIED requires implementation proof."""
    validator = FrontendContractValidator(temp_workspace)
    active_skills = ["taste-design", "design-system", "design-engineering", "web-design-guidelines", "vanilla-web"]

    # In empty workspace without implementation files, no skills can be APPLIED
    evidence = validator.evaluate_skill_application_evidence(
        workspace_root=temp_workspace,
        active_skills=active_skills,
        design_brief=None,
    )
    for sk in active_skills:
        assert evidence[sk]["applied"] is False, f"Skill {sk} should not be APPLIED in empty workspace"


# ==============================================================================
# 14. Generic Passing Validator Does Not Falsely Mark Every Skill APPLIED
# ==============================================================================

def test_req14_generic_passing_validator_does_not_falsely_mark_every_skill_applied(temp_workspace):
    """Req 14: A generic passing contract validator does NOT independently mark all frontend skills APPLIED."""
    # Create valid HTML/CSS/JS that lacks :root design tokens and has no DesignBrief
    html = temp_workspace / "index.html"
    html.write_text("<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width'><title>Test</title><link rel='stylesheet' href='style.css'></head><body><div id='root'></div><script src='app.js'></script></body></html>", encoding="utf-8")
    css = temp_workspace / "style.css"
    css.write_text("body { margin: 0; overflow-x: hidden; } @media (max-width: 768px) { body { font-size: 14px; } }", encoding="utf-8")
    js = temp_workspace / "app.js"
    js.write_text("document.getElementById('root').textContent = 'Hello';", encoding="utf-8")

    validator = FrontendContractValidator(temp_workspace)
    report = validator.validate_all()
    assert report.is_valid, "Contract validator should pass for consistent DOM IDs and CSS"

    # Evaluate skill evidence: taste-design and design-system must NOT be marked APPLIED
    evidence = validator.evaluate_skill_application_evidence(
        workspace_root=temp_workspace,
        active_skills=["taste-design", "design-system", "vanilla-web"],
        design_brief=None,  # No DesignBrief generated
        validation_report=report,
    )
    assert evidence["taste-design"]["applied"] is False  # Missing DesignBrief
    assert evidence["design-system"]["applied"] is False  # Missing :root design tokens
    assert evidence["vanilla-web"]["applied"] is True    # Native HTML/CSS/JS present


# ==============================================================================
# 15. Live Browser Verification Checks (Overflow, Components, Images)
# ==============================================================================

def test_req15_browser_level_visual_qa_checks(temp_workspace):
    """Req 15: Browser verification checks overflow, component styling, images, and modal behavior."""
    validator = FrontendContractValidator(temp_workspace)

    # Simulated browser evaluation with horizontal overflow defect
    overflow_data = {
        "has_horizontal_overflow": True,
        "console_errors": ["TypeError: Cannot read properties of undefined"],
        "broken_images": ["http://localhost:3000/broken.jpg"],
    }
    qa_result = validator.verify_browser_visual_qa(temp_workspace, browser_eval_data=overflow_data)

    assert qa_result["passed"] is False
    assert qa_result["checks"]["no_horizontal_overflow"] is False
    assert qa_result["checks"]["zero_console_errors"] is False
    assert qa_result["checks"]["images_loaded"] is False
    assert qa_result["visual_qa_status"] == "FAIL"
    assert qa_result["functional_qa_status"] == "FAIL"


# ==============================================================================
# 16. Mandatory UI Foundation On Simple Websites Without Landing Page Exception
# ==============================================================================

def test_req16_mandatory_ui_bundle_applied_on_simple_websites(skill_engine):
    """Req 16: Simple website missions receive the full mandatory UI foundation bundle."""
    prompt = "Build a static single-page cafe landing page using clean HTML5 and semantic styling"
    decision = skill_engine.route_skills(prompt)

    assert not decision.is_fallback
    assert "taste-design" in decision.selected_skills
    assert "design-engineering" in decision.selected_skills
    assert "design-system" in decision.selected_skills
    assert "web-design-guidelines" in decision.selected_skills
    assert "vanilla-web" in decision.selected_skills


# ==============================================================================
# 17. Negative Technology Constraints: No Vanilla Does Not Force React
# ==============================================================================

def test_req17_negative_constraint_no_vanilla_does_not_force_react(skill_engine):
    """Req 17: Respect has_no_vanilla; never force vanilla-web or introduce React automatically."""
    prompt = "Create a modern website user interface with no vanilla javascript, pure HTML and CSS only"
    decision = skill_engine.route_skills(prompt)

    assert "vanilla-web" not in decision.selected_skills
    assert "react-frontend" not in decision.selected_skills
    assert "taste-design" in decision.selected_skills
    assert "design-engineering" in decision.selected_skills
    assert "design-system" in decision.selected_skills
    assert "web-design-guidelines" in decision.selected_skills


# ==============================================================================
# 18. Genuine Browser QA: NOT_RUN When Evidence Unavailable
# ==============================================================================

def test_req18_browser_qa_not_run_when_evidence_unavailable(temp_workspace):
    """Req 18: In verify_browser_visual_qa(), when actual browser evidence is unavailable, mark checks NOT_RUN."""
    # Place static files in workspace without any acceptance evidence
    (temp_workspace / "index.html").write_text("<header><h1>Title</h1></header>", encoding="utf-8")
    (temp_workspace / "style.css").write_text("body { overflow-x: hidden; }", encoding="utf-8")

    validator = FrontendContractValidator(temp_workspace)
    qa_result = validator.verify_browser_visual_qa(temp_workspace, browser_eval_data=None)

    assert qa_result["passed"] is False
    assert qa_result["visual_qa_status"] == "NOT_RUN"
    assert qa_result["functional_qa_status"] == "NOT_RUN"
    assert qa_result["checks"]["no_horizontal_overflow"] == "NOT_RUN"
    assert qa_result["checks"]["zero_console_errors"] == "NOT_RUN"
    assert qa_result["checks"]["images_loaded"] == "NOT_RUN"
    assert qa_result["checks"]["rendered_component_styling"] == "NOT_RUN"
    assert "Browser evidence unavailable" in qa_result["issues"][0]


# ==============================================================================
# 19. Genuine Browser QA: Evaluates acceptance_evidence.json Correctly
# ==============================================================================

def test_req19_browser_qa_evaluates_acceptance_evidence_file(temp_workspace):
    """Req 19: Browser QA loads acceptance_evidence.json and performs full evaluations."""
    hermes_dir = temp_workspace / ".hermes"
    hermes_dir.mkdir(parents=True, exist_ok=True)

    # Valid acceptance evidence with 0 errors, no overflow, images loaded
    valid_payload = {
        "passed": True,
        "has_horizontal_overflow": False,
        "console_errors": [],
        "broken_images": [],
        "components_styled": True,
        "navigation_valid": True,
        "modal_valid": True,
        "form_controls_valid": True,
        "card_layout_responsive": True,
        "images": [{"src": "hero.jpg", "naturalWidth": 1200, "complete": True}],
    }
    (hermes_dir / "acceptance_evidence.json").write_text(json.dumps(valid_payload), encoding="utf-8")

    validator = FrontendContractValidator(temp_workspace)
    qa_result = validator.verify_browser_visual_qa(temp_workspace)

    assert qa_result["passed"] is True
    assert qa_result["visual_qa_status"] == "PASS"
    assert qa_result["functional_qa_status"] == "PASS"
    assert qa_result["checks"]["no_horizontal_overflow"] is True
    assert qa_result["checks"]["zero_console_errors"] is True
    assert qa_result["checks"]["images_loaded"] is True
    assert len(qa_result["issues"]) == 0


# ==============================================================================
# 20. Correct npm Preflight for Nested Projects (--prefix variations)
# ==============================================================================

def test_req20_nested_npm_preflight_prefix_handling(temp_workspace):
    """Req 20: Extend npm preflight to correctly resolve package locations for --prefix variations."""
    tool = BashExecTool()
    frontend_dir = temp_workspace / "frontend"
    frontend_dir.mkdir(parents=True, exist_ok=True)

    # A. Missing package.json in nested dir
    res1 = tool.execute(BashExecTool.Input(
        command="npm --prefix frontend test",
        working_dir=str(temp_workspace),
    ))
    assert not res1.success
    assert res1.details["classification"] == "MISSING_PACKAGE_JSON"
    assert "frontend" in res1.details["effective_dir"]

    # B. Missing 'test' script in nested package.json
    (frontend_dir / "package.json").write_text(json.dumps({"name": "client", "scripts": {"build": "vite build"}}), encoding="utf-8")
    res2 = tool.execute(BashExecTool.Input(
        command="npm --prefix frontend test",
        working_dir=str(temp_workspace),
    ))
    assert not res2.success
    assert res2.details["classification"] == "MISSING_TEST_SCRIPT"

    # C. Missing custom run script in nested package.json with --prefix=dir
    res3 = tool.execute(BashExecTool.Input(
        command="npm --prefix=frontend run lint",
        working_dir=str(temp_workspace),
    ))
    assert not res3.success
    assert res3.details["classification"] == "MISSING_NPM_SCRIPT"

    # D. Prefix at end of command (npm test --prefix frontend)
    res4 = tool.execute(BashExecTool.Input(
        command="npm test --prefix frontend",
        working_dir=str(temp_workspace),
    ))
    assert not res4.success
    assert res4.details["classification"] == "MISSING_TEST_SCRIPT"


# ==============================================================================
# 21. Accurate Shell Tracking: cmd.exe vs PowerShell
# ==============================================================================

def test_req21_accurate_shell_tracking_cmd_vs_powershell(temp_workspace):
    """Req 21: Do not claim PowerShell is used when running via cmd.exe."""
    tool = BashExecTool()

    # Standard command on Windows runs via cmd.exe
    res_cmd = tool.execute(BashExecTool.Input(
        command="echo hello",
        working_dir=str(temp_workspace),
    ))
    if sys.platform == "win32":
        assert res_cmd.details["shell_used"] == "cmd.exe"

    # Explicit PowerShell cmdlet command translates and identifies powershell
    res_ps = tool.execute(BashExecTool.Input(
        command="Get-ChildItem",
        working_dir=str(temp_workspace),
    ))
    if sys.platform == "win32":
        assert res_ps.details["shell_used"] == "powershell"
