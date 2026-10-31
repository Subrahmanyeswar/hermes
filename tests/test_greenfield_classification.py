# tests/test_greenfield_classification.py
"""
Regression and Acceptance Test Suite for Greenfield Project Classification & Preflight.

Validates:
  1. All 8 distinct intent classification cases:
     - Case 1: Greenfield web application with adjectives ("Build a polished, fully functional, responsive web application called FocusFlow.")
     - Case 2: Greenfield from scratch with preservation clause ("Create a brand-new responsive web application called FocusFlow from scratch. Create index.html, style.css and main.js. No existing application is being modified.")
     - Case 3: Greenfield explicitly declaring empty workspace ("Develop a new website named FocusFlow in an empty workspace.")
     - Case 4: Greenfield dashboard ("Create a clean dashboard with HTML, CSS and JavaScript.")
     - Case 5: Modify existing website ("Modify my existing website.")
     - Case 6: Fix bug in existing application ("Fix the bug in the existing application.")
     - Case 7: Add feature to existing project ("Add a feature to the existing project.")
     - Case 8: Integrate component into current project ("Integrate a new chart into the current project.")
  2. Workspace preflight gating:
     - Greenfield requests succeed in an empty workspace (0 application files).
     - Modify/extend requests fail with actionable guidance when workspace is empty.
     - Modify/extend requests succeed when application files exist.
  3. Realistic complex prompt acceptance:
     - Full FocusFlow user request containing in-app CRUD instructions ('Users must be able to edit existing tasks')
       is classified as GREENFIELD_CREATE and passes preflight in an empty workspace.
  4. Backward compatibility:
     - MissionIntent.NEW_PROJECT == MissionIntent.GREENFIELD_CREATE
     - MissionIntent.CONTINUATION_OR_MODIFICATION == MissionIntent.EXISTING_PROJECT_MODIFY
"""

from pathlib import Path
import pytest

from core.agent_loop.preflight import (
    MissionIntent,
    classify_mission_intent,
    validate_workspace_preflight,
)


# ==============================================================================
# 1. INTENT CLASSIFICATION SPECIFICATION TESTS (8 CASES)
# ==============================================================================

def test_case_1_build_polished_responsive_web_app():
    prompt = "Build a polished, fully functional, responsive web application called FocusFlow."
    intent, reason = classify_mission_intent(prompt)
    assert intent == MissionIntent.GREENFIELD_CREATE
    assert intent == MissionIntent.NEW_PROJECT  # Alias compatibility


def test_case_2_create_brand_new_from_scratch_with_negative_clause():
    prompt = (
        "Create a brand-new responsive web application called FocusFlow from scratch. "
        "Create index.html, style.css and main.js. No existing application is being modified."
    )
    intent, reason = classify_mission_intent(prompt)
    assert intent == MissionIntent.GREENFIELD_CREATE
    assert intent == MissionIntent.NEW_PROJECT


def test_case_3_develop_new_website_in_empty_workspace():
    prompt = "Develop a new website named FocusFlow in an empty workspace."
    intent, reason = classify_mission_intent(prompt)
    assert intent == MissionIntent.GREENFIELD_CREATE


def test_case_4_create_clean_dashboard():
    prompt = "Create a clean dashboard with HTML, CSS and JavaScript."
    intent, reason = classify_mission_intent(prompt)
    assert intent == MissionIntent.GREENFIELD_CREATE


def test_case_5_modify_existing_website():
    prompt = "Modify my existing website."
    intent, reason = classify_mission_intent(prompt)
    assert intent == MissionIntent.EXISTING_PROJECT_MODIFY
    assert intent == MissionIntent.CONTINUATION_OR_MODIFICATION  # Alias compatibility


def test_case_6_fix_bug_in_existing_application():
    prompt = "Fix the bug in the existing application."
    intent, reason = classify_mission_intent(prompt)
    assert intent == MissionIntent.EXISTING_PROJECT_MODIFY


def test_case_7_add_feature_to_existing_project():
    prompt = "Add a feature to the existing project."
    intent, reason = classify_mission_intent(prompt)
    assert intent == MissionIntent.EXISTING_PROJECT_EXTEND


def test_case_8_integrate_new_chart_into_current_project():
    prompt = "Integrate a new chart into the current project."
    intent, reason = classify_mission_intent(prompt)
    assert intent == MissionIntent.EXISTING_PROJECT_EXTEND


# ==============================================================================
# 2. WORKSPACE PREFLIGHT GATING (EMPTY VS NON-EMPTY)
# ==============================================================================

def test_greenfield_accepted_in_empty_workspace(tmp_path: Path):
    """Greenfield requests MUST pass preflight even when workspace has 0 files."""
    empty_ws = tmp_path / "empty_focusflow_ws"
    empty_ws.mkdir()

    prompt = "Create a brand-new responsive web application called FocusFlow from scratch. Create index.html, style.css and main.js. No existing application is being modified."
    result = validate_workspace_preflight(prompt, empty_ws)

    assert result.allowed is True
    assert result.intent == MissionIntent.GREENFIELD_CREATE
    assert result.existing_app_files_count == 0
    assert result.failure_code is None


def test_modify_rejected_in_empty_workspace(tmp_path: Path):
    """Modify existing app requests MUST fail preflight when workspace has 0 files."""
    empty_ws = tmp_path / "empty_mod_ws"
    empty_ws.mkdir()

    prompt = "Modify my existing website."
    result = validate_workspace_preflight(prompt, empty_ws)

    assert result.allowed is False
    assert result.intent == MissionIntent.EXISTING_PROJECT_MODIFY
    assert result.failure_code == "EMPTY_WORKSPACE_EXISTING_APPLICATION"
    assert "contains 0 existing application files" in (result.error or "")


def test_extend_rejected_in_empty_workspace(tmp_path: Path):
    """Extend existing project requests MUST fail preflight when workspace has 0 files."""
    empty_ws = tmp_path / "empty_ext_ws"
    empty_ws.mkdir()

    prompt = "Add a feature to the existing project."
    result = validate_workspace_preflight(prompt, empty_ws)

    assert result.allowed is False
    assert result.intent == MissionIntent.EXISTING_PROJECT_EXTEND
    assert result.failure_code == "EMPTY_WORKSPACE_EXISTING_APPLICATION"


def test_modify_accepted_in_non_empty_workspace(tmp_path: Path):
    """Modify requests MUST pass preflight when workspace contains target application files."""
    ws = tmp_path / "existing_app_ws"
    ws.mkdir()
    (ws / "index.html").write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
    (ws / "style.css").write_text("body { margin: 0; }", encoding="utf-8")

    prompt = "Modify my existing website."
    result = validate_workspace_preflight(prompt, ws)

    assert result.allowed is True
    assert result.intent == MissionIntent.EXISTING_PROJECT_MODIFY
    assert result.existing_app_files_count == 2
    assert result.failure_code is None


def test_extend_accepted_in_non_empty_workspace(tmp_path: Path):
    """Extend requests MUST pass preflight when workspace contains target application files."""
    ws = tmp_path / "existing_ext_ws"
    ws.mkdir()
    (ws / "index.html").write_text("<!DOCTYPE html><html></html>", encoding="utf-8")

    prompt = "Integrate a new chart into the current project."
    result = validate_workspace_preflight(prompt, ws)

    assert result.allowed is True
    assert result.intent == MissionIntent.EXISTING_PROJECT_EXTEND
    assert result.existing_app_files_count == 1
    assert result.failure_code is None


# ==============================================================================
# 3. REAL-WORLD COMPLEX PROMPT (IN-APP CRUD PHRASES)
# ==============================================================================

def test_full_focusflow_prompt_with_in_app_edit_existing_tasks(tmp_path: Path):
    """
    Ensure the actual FocusFlow prompt containing in-app feature specifications like
    'Users must be able to edit existing tasks' and 'Edit an existing task' is NOT
    misclassified as codebase modification and passes preflight in an empty workspace.
    """
    empty_ws = tmp_path / "testing_2_empty"
    empty_ws.mkdir()

    complex_prompt = """
# BUILD FOCUSFLOW — A COMPLETE STUDY AND PROJECT MANAGEMENT DASHBOARD

## Mission objective
Build a polished, fully functional, responsive web application called **FocusFlow**.
FocusFlow is a personal study and project management dashboard that helps users organize study tasks.

## 1. Project structure
Create an isolated project in the current HERMES workspace.
Create exactly these three application files:
- `index.html`
- `style.css`
- `main.js`

### Edit tasks
Users must be able to edit existing tasks.
Changes must immediately update the dashboard.

**Test 5 — Edit and delete**
- Edit an existing task.
- Verify the updated information.

Do not modify the existing rocket application or any other project.
"""
    intent, reason = classify_mission_intent(complex_prompt)
    assert intent == MissionIntent.GREENFIELD_CREATE

    result = validate_workspace_preflight(complex_prompt, empty_ws)
    assert result.allowed is True
    assert result.intent == MissionIntent.GREENFIELD_CREATE
    assert result.failure_code is None


# ==============================================================================
# 4. ENUM AND BACKWARD COMPATIBILITY
# ==============================================================================

def test_mission_intent_enum_backward_compatibility():
    assert MissionIntent.NEW_PROJECT == MissionIntent.GREENFIELD_CREATE
    assert MissionIntent.CONTINUATION_OR_MODIFICATION == MissionIntent.EXISTING_PROJECT_MODIFY
    assert MissionIntent("GREENFIELD_CREATE") == MissionIntent.GREENFIELD_CREATE
    assert MissionIntent("EXISTING_PROJECT_MODIFY") == MissionIntent.EXISTING_PROJECT_MODIFY
    assert MissionIntent("EXISTING_PROJECT_EXTEND") == MissionIntent.EXISTING_PROJECT_EXTEND
