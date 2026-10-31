# tests/test_write_file_preflight_and_planner_hotfix.py
"""
Focused regression suite for HERMES Hotfix:
1. write_file execution, verification, nested directories, paths with spaces, and failure handling.
2. New-project vs continuation preflight classification, empty workspace acceptance, and target path mismatch.
3. GoalDecomposer deduplication, cycle repair, and bounded dependency management.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from core.workspace import WorkspaceManager, WorkspaceBoundaryError
from tools.file_tools import WriteFileTool, ReadFileTool
from tools.platform.core_tools import FSWriteTool, FSReadTool
from core.agent_loop.preflight import (
    MissionIntent,
    PreflightResult,
    classify_mission_intent,
    extract_specified_target_workspace,
    validate_workspace_preflight,
)
from core.planning.decomposer import (
    DependencyCycleError,
    GoalDecomposer,
)
from core.runtime_state.models import RequirementState, RequirementCategory, RequirementPriority, RequirementStatus


# ==============================================================================
# PHASE 2 — WRITE_FILE EXECUTION & VERIFICATION TESTS
# ==============================================================================

def test_write_file_standard_execution(tmp_path):
    """Verify write_file creates file with exact content and returns success."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    tool = WriteFileTool()
    res = tool.execute({"path": "app.js", "content": "console.log('hello');", "mode": "create", "_workspace": wm})

    assert res.success is True
    assert res.exit_code == 0
    target_file = tmp_path / "app.js"
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "console.log('hello');"


def test_write_file_nested_directories(tmp_path):
    """Verify write_file automatically creates nested parent directories."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    tool = WriteFileTool()
    res = tool.execute({"path": "assets/models/rocket.json", "content": '{"type": "rocket"}', "mode": "create", "_workspace": wm})

    assert res.success is True
    target_file = tmp_path / "assets" / "models" / "rocket.json"
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == '{"type": "rocket"}'


def test_write_file_path_with_spaces(tmp_path):
    """Verify write_file operates correctly when workspace or file path contains spaces."""
    ws_with_spaces = tmp_path / "rocket hermes test"
    ws_with_spaces.mkdir()

    wm = WorkspaceManager()
    wm.lock(str(ws_with_spaces))

    tool = WriteFileTool()
    res = tool.execute({"path": "deep nested/test file.txt", "content": "space path content", "mode": "create", "_workspace": wm})

    assert res.success is True
    created = ws_with_spaces / "deep nested" / "test file.txt"
    assert created.exists()
    assert created.read_text(encoding="utf-8") == "space path content"


def test_write_file_security_rejection_outside_workspace(tmp_path):
    """Verify paths attempting to escape workspace boundary are rejected safely."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    tool = WriteFileTool()
    res = tool.execute({"path": "../../outside.txt", "content": "forbidden", "mode": "create", "_workspace": wm})

    assert res.success is False
    assert res.exit_code == 126
    assert "SECURITY" in (res.error or "")


def test_fs_write_platform_tool_verification(tmp_path):
    """Verify platform FSWriteTool verifies actual disk state after atomic write."""
    ws_dir = tmp_path / "platform_ws"
    ws_dir.mkdir()

    wm = WorkspaceManager()
    wm.lock(str(ws_dir))

    tool = FSWriteTool()
    res = tool.execute({"path": "index.html", "content": "<h1>AETHER ORBITAL</h1>", "_workspace": wm})

    assert res.success is True
    written = ws_dir / "index.html"
    assert written.exists()
    assert "AETHER ORBITAL" in written.read_text(encoding="utf-8")


# ==============================================================================
# PHASE 3 — PREFLIGHT & INTENT CLASSIFICATION TESTS
# ==============================================================================

def test_1_new_project_in_empty_workspace_accepted(tmp_path):
    """An explicit new project request in an empty workspace is accepted."""
    empty_ws = tmp_path / "empty_rocket_ws"
    empty_ws.mkdir()

    prompt = "Build a complete, visually exceptional website for AETHER ORBITAL featuring an interactive 3D rocket."
    res = validate_workspace_preflight(prompt, empty_ws)

    assert res.allowed is True
    assert res.intent == MissionIntent.NEW_PROJECT
    assert res.failure_code is None


def test_2_continuation_of_existing_project_with_files_accepted(tmp_path):
    """A continuation mission with existing application files is accepted."""
    active_ws = tmp_path / "car_ws"
    active_ws.mkdir()
    (active_ws / "index.html").write_text("<html></html>", encoding="utf-8")
    (active_ws / "styles.css").write_text("body {}", encoding="utf-8")

    prompt = "Continue improving the existing AURELION website in the active workspace. Fix the dialog and form."
    res = validate_workspace_preflight(prompt, active_ws)

    assert res.allowed is True
    assert res.intent == MissionIntent.CONTINUATION_OR_MODIFICATION
    assert res.existing_app_files_count == 2


def test_3_continuation_requiring_missing_files_rejected(tmp_path):
    """A continuation mission targeting an empty workspace produces actionable rejection."""
    empty_ws = tmp_path / "empty_ws"
    empty_ws.mkdir()

    prompt = "Continue improving the existing AURELION website in the active workspace. Fix vehicle dialogs."
    res = validate_workspace_preflight(prompt, empty_ws)

    assert res.allowed is False
    assert res.intent == MissionIntent.CONTINUATION_OR_MODIFICATION
    assert res.failure_code == "EMPTY_WORKSPACE_EXISTING_APPLICATION"
    assert "contains 0 existing application files" in (res.error or "")


def test_4_explicit_target_path_mismatch_rejected(tmp_path):
    """If the prompt explicitly specifies a target workspace that differs from the active workspace, reject before execution."""
    active_ws = tmp_path / "rocket hermes test"
    active_ws.mkdir()
    intended_ws = tmp_path / "hermes_rocket_3d_test"

    prompt = (
        f"# AETHER ORBITAL\n"
        f"**Target workspace:** `{intended_ws}`\n"
        f"This is a new project. Build an interactive 3D rocket website."
    )
    res = validate_workspace_preflight(prompt, active_ws)

    assert res.allowed is False
    assert res.failure_code == "WORKSPACE_TARGET_MISMATCH"
    assert "Target workspace mismatch" in (res.error or "")
    assert str(intended_ws.resolve()) in (res.error or "")


def test_5_new_project_mentioning_preservation_classified_as_new(tmp_path):
    """A new-project prompt that mentions preserving unrelated projects is correctly classified as NEW_PROJECT."""
    empty_ws = tmp_path / "clean_ws"
    empty_ws.mkdir()

    prompt = (
        "This is a new project. Do not overwrite or modify the existing AURELION website or the HERMES source repository.\n"
        "Build a complete, visually exceptional aerospace website featuring an interactive 3D rocket."
    )
    intent, reason = classify_mission_intent(prompt)
    assert intent == MissionIntent.NEW_PROJECT

    res = validate_workspace_preflight(prompt, empty_ws)
    assert res.allowed is True
    assert res.failure_code is None


def test_6_workspace_files_unchanged_when_mission_rejected(tmp_path):
    """Verify existing workspace files are untouched when preflight rejects a mission."""
    ws = tmp_path / "ws_preserved"
    ws.mkdir()
    marker = ws / "important.txt"
    marker.write_text("do not touch", encoding="utf-8")
    before_stat = marker.stat()

    # Trigger mismatch rejection
    prompt = "**Target workspace:** `C:\\some\\other\\path`\nContinue work."
    res = validate_workspace_preflight(prompt, ws)
    assert res.allowed is False

    # Marker file must be untouched
    assert marker.exists()
    assert marker.read_text(encoding="utf-8") == "do not touch"
    assert marker.stat().st_mtime == before_stat.st_mtime


# ==============================================================================
# PHASE 4 — PLANNER DEDUPLICATION, CYCLE HANDLING & BOUNDED RECOVERY TESTS
# ==============================================================================

def test_planner_deduplicates_synonym_requirements():
    """Verify that synonyms (asset/image, style/css, modal/dialog) do NOT produce duplicate requirements."""
    prompt = (
        "Build a modern website with local photographic assets and image files, "
        "visual style and css styling, and an interactive modal dialog."
    )
    reqs, checks = GoalDecomposer.decompose("g_test", prompt)

    # Titles should be unique
    titles = [r.title for r in reqs.values()]
    assert len(titles) == len(set(titles)), f"Duplicate requirement titles found: {titles}"

    # Only one media asset requirement
    asset_reqs = [r for r in reqs.values() if "media" in r.title.lower() or "asset" in r.title.lower()]
    assert len(asset_reqs) == 1

    # Only one visual styling requirement
    style_reqs = [r for r in reqs.values() if "styling" in r.title.lower() or "css" in r.title.lower()]
    assert len(style_reqs) == 1

    # Only one modal dialog requirement
    dialog_reqs = [r for r in reqs.values() if "modal" in r.title.lower() or "dialog" in r.title.lower()]
    assert len(dialog_reqs) == 1


def test_planner_word_boundary_avoids_false_car_and_auth_matches():
    """Verify that substring 'carefully' does not trigger 'car', and 'authoritative' does not trigger 'auth'."""
    prompt = (
        "Build a carefully art-directed orbital space mission overview. "
        "Provide an authoritative terminal walkthrough with zero regressions."
    )
    reqs, checks = GoalDecomposer.decompose("g_test", prompt)

    # Must NOT contain automotive concept
    assert not any("vehicle" in r.title.lower() or "car" in r.title.lower() for r in reqs.values())

    # Must NOT contain authentication requirement
    assert not any("authentication" in r.title.lower() for r in reqs.values())


def test_planner_preserves_independent_tasks_and_dependencies():
    """Verify genuine independent requirements (responsive, form, website, 3d) remain distinct and properly ordered."""
    prompt = (
        "Build a responsive web application with a contact form, visual styling, "
        "interactive 3D graphics with Three.js, and browser qualification."
    )
    reqs, checks = GoalDecomposer.decompose("g_test", prompt)

    req_ids = set(reqs.keys())
    assert "req.responsive" in req_ids
    assert "req.form" in req_ids
    assert "req.website" in req_ids
    assert "req.3d_graphics" in req_ids
    assert "req.verification" in req_ids

    # Verification must depend on functional tasks
    verif = reqs["req.verification"]
    assert "req.website" in verif.dependencies
    assert "req.3d_graphics" in verif.dependencies


def test_planner_cycle_detection_and_safe_repair():
    """Verify that dependency cycles are detected and automatically broken without infinite looping."""
    req_a = RequirementState(requirement_id="req_a", goal_id="g1", title="A", dependencies=["req_c"])
    req_b = RequirementState(requirement_id="req_b", goal_id="g1", title="B", dependencies=["req_a"])
    req_c = RequirementState(requirement_id="req_c", goal_id="g1", title="C", dependencies=["req_b"])

    reqs = {"req_a": req_a, "req_b": req_b, "req_c": req_c}

    # Direct validation raises cycle error
    with pytest.raises(DependencyCycleError):
        GoalDecomposer.validate_dependencies(reqs)

    # break_cycles repairs the graph
    GoalDecomposer.break_cycles(reqs)

    # Now validation passes cleanly
    GoalDecomposer.validate_dependencies(reqs)


# ==============================================================================
# PHASE 5 — DIRECTORY READ SAFETY & ENTRYPOINT PRIORITIZATION TESTS
# ==============================================================================

def test_read_file_on_directory_returns_actionable_error(tmp_path):
    """Calling read_file on a directory returns actionable guidance and PATH_IS_DIRECTORY error code."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    sub_dir = tmp_path / "src"
    sub_dir.mkdir()

    # Test file_tools ReadFileTool
    tool = ReadFileTool()
    res = tool.execute({"path": "src"})
    assert res.success is False
    assert res.exit_code == 1
    assert "directory" in res.error.lower()
    assert res.details.get("code") == "PATH_IS_DIRECTORY"

    # Test platform FSReadTool
    fs_read = FSReadTool()
    res_platform = fs_read.execute({"path": "src", "_workspace": wm})
    assert res_platform.success is False
    assert res_platform.exit_code == 1
    assert "directory" in res_platform.error.lower()
    assert res_platform.details.get("code") == "PATH_IS_DIRECTORY"


def test_write_and_read_roundtrip_with_space_workspace(tmp_path):
    """Verify write_file writes exact content and read_file reads exact content in path with spaces."""
    ws_dir = tmp_path / "rocket hermes test space"
    ws_dir.mkdir()
    wm = WorkspaceManager()
    wm.lock(str(ws_dir))

    w_tool = WriteFileTool()
    test_content = "import * as THREE from 'three';\nconsole.log('3D Rocket Scene');"
    w_res = w_tool.execute({"path": "js/main.js", "content": test_content, "mode": "create", "_workspace": wm})
    assert w_res.success is True
    assert (ws_dir / "js" / "main.js").exists()

    r_tool = ReadFileTool()
    r_res = r_tool.execute({"path": "js/main.js", "_workspace": wm})
    assert r_res.success is True
    assert r_res.output == test_content


def test_write_file_execution_never_raises_nameerror(tmp_path):
    """Verify write_file execution path does not raise NameError for Path or any other symbol."""
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))

    w_tool = WriteFileTool()
    # Execute with various modes and parameters
    try:
        r1 = w_tool.execute({"path": "test1.py", "content": "x = 1\n", "mode": "create", "_workspace": wm})
        assert r1.success is True
        r2 = w_tool.execute({"path": "test1.py", "content": "x = 1\n", "mode": "overwrite", "_workspace": wm})
        assert r2.success is True
        assert "UNCHANGED" in r2.output
    except NameError as ne:
        pytest.fail(f"WriteFileTool raised NameError: {ne}")

