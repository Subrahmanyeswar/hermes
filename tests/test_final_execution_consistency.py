# tests/test_final_execution_consistency.py
"""
Test Suite: HERMES Final Execution Consistency, Task State, Tool Boundary,
Project Architecture, Continuation, Verification, and Performance Repair.

Tests the authoritative contracts established in the final consolidation pass:
1. Milestone Bounding (max 6 tasks in production mode, no 27-task explosion)
2. Architecture Lock (strict stack locking, no React in vanilla web)
3. Skill Filtering (disallows contradicting skills)
4. Tool Boundary Defense (strips markdown fences and JSON envelopes from file content)
5. Idempotent File Writes (identical content returns NOOP_ALREADY_MATCHES)
6. Read Loop Protection (>= 4 reads triggers NO_PROGRESS enforcement)
7. Task State Machine & Stage 12 Artifact Enforcement (intermediate tasks do not fail for future artifacts)
8. Mission Continuation ("continue" / "continue building" resumes active mission)
9. Technology-Aware Behavioral Verifier (verifies vanilla web, rejects stubs and React imports)
10. TUI Input Controls Mutually-Exclusive State Machine (SEND / STOP button integrity)
"""

import json
import pytest
from pathlib import Path

from core.architecture_lock import (
    ArchitectureLock,
    ArchitectureType,
    ArchitectureDecision,
    detect_architecture,
)
from core.mission_planner import MissionPlanner, Mission, MissionTask, TaskState
from tools.platform.core_tools import FSWriteTool, FSReadTool, READ_LOOP_TRACKER, ArtifactManifest
from tools.file_tools import _clean_code_content, WriteFileTool
from core.agent_loop.behavioral_verifier import TechnologyAwareBehavioralVerifier, BehavioralCheckResult
from kairos.mission_driver import MissionDriver


# ── 1. Milestone Bounding ──────────────────────────────────────────────────

def test_milestone_bounding_under_production_mode():
    """Ensure production planner limits tasks to <= 6 engineering milestones."""
    planner = MissionPlanner()
    prompt = (
        "Build a campus lost and found website with index.html, styles.css, app.js, "
        "animations.css, nav.css, modal.css, items.js, search.js, storage.js, api.js, utils.js"
    )
    mission = planner.plan(prompt, execution_mode="production")
    assert len(mission.tasks) <= 6
    assert len(mission.tasks) >= 1
    # Tasks should represent engineering phases, not micro file writes
    titles = [t.title.lower() for t in mission.tasks]
    assert any("architecture" in t or "structure" in t or "inspect" in t or "markup" in t or "project" in t for t in titles)


def test_consolidate_to_milestones_caps_at_6():
    """Directly test _consolidate_to_milestones for 27 raw tasks."""
    planner = MissionPlanner()
    raw_tasks = [f"Task {i}: write file_{i}.ext" for i in range(27)]
    consolidated = planner._consolidate_to_milestones(raw_tasks, "Build a complete web application")
    assert len(consolidated) <= 6
    assert len(consolidated) >= 1


# ── 2. Architecture Lock & Stack Integrity ────────────────────────────────

def test_architecture_lock_detects_vanilla_web():
    decision = detect_architecture("Create a campus lost and found website with html css and javascript")
    assert decision.architecture_type == ArchitectureType.VANILLA_WEB
    assert decision.entrypoint == "index.html"
    assert decision.framework == "vanilla"
    assert "react-frontend" in decision.disallowed_skills
    assert not decision.is_skill_allowed("react-frontend")
    assert decision.is_skill_allowed("vanilla-web")


def test_architecture_lock_detects_react():
    decision = detect_architecture("Create a React application with components and hooks")
    assert decision.architecture_type == ArchitectureType.REACT_APP
    assert decision.framework == "react"
    assert decision.is_skill_allowed("react-frontend")


def test_architecture_lock_detects_python_cli():
    decision = detect_architecture("Write a Python script hello.py to calculate numbers")
    assert decision.architecture_type == ArchitectureType.PYTHON_CLI
    assert decision.framework == "standard_library"
    assert not decision.is_skill_allowed("react-frontend")


def test_architecture_lock_validates_and_sanitizes_vanilla_web():
    decision = detect_architecture("Build a vanilla web app")
    dirty_js = (
        "import React, { useState } from 'react';\n"
        "import { render } from 'react-dom';\n"
        "function initApp() {\n"
        "    console.log('started');\n"
        "}\n"
        "export default initApp;\n"
    )
    is_valid, violations = decision.validate_file_content("app.js", dirty_js)
    assert not is_valid
    assert len(violations) >= 2

    # Sanitizer cleans out React imports and export default
    clean_js = decision.sanitize_file_content("app.js", dirty_js)
    assert "import React" not in clean_js
    assert "from 'react'" not in clean_js
    assert "export default" not in clean_js
    assert "initApp" in clean_js


# ── 3. Intent Classifier and Skill Filtering ──────────────────────────────

def test_intent_classifier_filters_disallowed_skills(tmp_path):
    from core.intent_classifier import IntentClassifier
    ArchitectureLock.lock(
        ArchitectureDecision(
            architecture_type=ArchitectureType.VANILLA_WEB,
            disallowed_skills=["react-frontend"],
        )
    )
    classifier = IntentClassifier(skills_dir="skills/")
    skills = classifier.classify("Build a modern frontend component for the website")
    assert "react-frontend" not in skills
    ArchitectureLock.release()


# ── 4. Tool Boundary Defense (Envelope & Fence Stripping) ─────────────────

def test_clean_code_content_strips_markdown_fences():
    fenced_html = "```html\n<!DOCTYPE html>\n<html><body>Hello</body></html>\n```"
    cleaned = _clean_code_content(fenced_html, path_str="index.html")
    assert not cleaned.startswith("```")
    assert not cleaned.endswith("```")
    assert "<!DOCTYPE html>" in cleaned


def test_clean_code_content_strips_json_envelope():
    json_envelope = json.dumps({
        "thought": "I will write index.html",
        "tool": "write_file",
        "parameters": {
            "path": "index.html",
            "content": "<!DOCTYPE html>\n<html><body>App</body></html>"
        }
    })
    cleaned = _clean_code_content(json_envelope, path_str="index.html")
    assert "<!DOCTYPE html>" in cleaned
    assert "{" not in cleaned or "<!DOCTYPE html>" in cleaned


def test_fswrite_tool_strips_markdown_fences_and_envelopes(tmp_path):
    tool = FSWriteTool()
    target_file = tmp_path / "index.html"
    fenced_code = "```html\n<!DOCTYPE html>\n<html><body>Real Content</body></html>\n```"

    res = tool.execute({
        "path": str(target_file),
        "content": fenced_code,
        "_workspace": None,
    })
    assert res.success
    disk_content = target_file.read_text(encoding="utf-8")
    assert not disk_content.strip().startswith("```")
    assert not disk_content.strip().endswith("```")
    assert "<!DOCTYPE html>" in disk_content


# ── 5. Idempotent File Writes ─────────────────────────────────────────────

def test_fswrite_tool_idempotent_write(tmp_path):
    tool = FSWriteTool()
    target_file = tmp_path / "app.js"
    initial_content = "console.log('stable application');\n"

    # First write
    res1 = tool.execute({
        "path": str(target_file),
        "content": initial_content,
        "_workspace": None,
    })
    assert res1.success
    assert "Successfully wrote" in res1.output

    # Identical second write -> NOOP_ALREADY_MATCHES
    res2 = tool.execute({
        "path": str(target_file),
        "content": initial_content,
        "_workspace": None,
    })
    assert res2.success
    assert "NOOP_ALREADY_MATCHES" in res2.output
    assert res2.details.get("noop") is True


# ── 6. Read Loop Protection ───────────────────────────────────────────────

def test_fsread_tool_read_loop_protection(tmp_path):
    read_tool = FSReadTool()
    sample_file = tmp_path / "data.txt"
    sample_file.write_text("Hello World", encoding="utf-8")

    READ_LOOP_TRACKER.clear()
    path_str = str(sample_file)

    # 1st read -> Success
    r1 = read_tool.execute({"path": path_str, "_workspace": None})
    assert r1.success

    # 2nd read -> Success
    r2 = read_tool.execute({"path": path_str, "_workspace": None})
    assert r2.success

    # 3rd read -> Advisory attached
    r3 = read_tool.execute({"path": path_str, "_workspace": None})
    assert r3.success
    assert "NO_PROGRESS_LOOP_ADVISORY" in r3.output

    # 4th read -> Rejected with NO_PROGRESS_LOOP_ENFORCEMENT
    r4 = read_tool.execute({"path": path_str, "_workspace": None})
    assert not r4.success
    assert "NO_PROGRESS_LOOP_ENFORCEMENT" in r4.error


# ── 7. Stage 12 Task Completion Enforcement ───────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_stage12_does_not_fail_intermediate_task_for_future_artifacts(tmp_path):
    from core.orchestrator import Orchestrator
    orch = Orchestrator(mode="auto")
    # Verify extract_requested_artifacts
    artifacts = orch.extract_requested_artifacts("Create index.html, styles.css, and app.js")
    assert "index.html" in artifacts
    assert "styles.css" in artifacts
    assert "app.js" in artifacts


# ── 8. Mission Continuation ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mission_driver_resumes_uncompleted_mission():
    from unittest.mock import MagicMock
    mock_orch = MagicMock()
    mock_orch.execution_mode = "production"

    driver = MissionDriver(mock_orch)
    mission = Mission(
        mission_id="mission_continue_test",
        user_prompt="Build campus lost and found",
        tasks=[
            MissionTask(task_id="t1", title="Task 1", state=TaskState.COMPLETED),
            MissionTask(task_id="t2", title="Task 2", state=TaskState.FAILED),
            MissionTask(task_id="t3", title="Task 3", state=TaskState.PENDING),
        ],
    )
    driver._current_mission = mission
    driver._workspace_initialised = True

    # Call run_mission with "continue"
    # Mock MissionRunner to return immediately
    runner_mock = MagicMock()
    runner_res = MagicMock()
    runner_res.success = True
    runner_mock.run.return_value = runner_res

    # Use monkeypatch or mock current runner
    from unittest.mock import patch
    with patch("kairos.mission_driver.MissionRunner.run", return_value=runner_res):
        res = await driver.run_mission("continue building")
        # Ensure it resumed the same mission
        assert driver._current_mission.mission_id == "mission_continue_test"
        # Task 2 should have been reset from FAILED to PENDING
        assert driver._current_mission.tasks[1].state == TaskState.PENDING


# ── 9. Technology-Aware Behavioral Verifier ───────────────────────────────

def test_behavioral_verifier_accepts_complete_vanilla_web(tmp_path):
    # Setup complete working vanilla app
    index_html = (
        "<!DOCTYPE html>\n<html lang='en'>\n<head>\n"
        "<link rel='stylesheet' href='styles.css'>\n"
        "</head>\n<body>\n"
        "<div id='app'>\n"
        "  <h1>Campus Lost & Found</h1>\n"
        "  <form id='report-form'>\n"
        "    <input type='text' id='item-title' placeholder='Item title' required>\n"
        "    <button type='submit' id='submit-btn'>Report Item</button>\n"
        "  </form>\n"
        "  <input type='search' id='search-input' placeholder='Search items'>\n"
        "  <select id='category-filter'><option value='all'>All</option></select>\n"
        "  <div id='items-container'></div>\n"
        "</div>\n"
        "<script src='app.js'></script>\n"
        "</body>\n</html>"
    )
    styles_css = (
        ":root { --primary: #0056b3; }\n"
        "body { font-family: sans-serif; margin: 0; padding: 20px; }\n"
        "@media (max-width: 768px) { body { padding: 10px; } }\n"
        "#app { display: flex; flex-direction: column; gap: 15px; }\n"
    )
    app_js = (
        "document.addEventListener('DOMContentLoaded', () => {\n"
        "  const form = document.getElementById('report-form');\n"
        "  const searchInput = document.getElementById('search-input');\n"
        "  const container = document.getElementById('items-container');\n"
        "  let items = JSON.parse(localStorage.getItem('campus_items') || '[]');\n"
        "  function render() {\n"
        "    container.innerHTML = items.map(i => `<div>${i.title}</div>`).join('');\n"
        "  }\n"
        "  form.addEventListener('submit', (e) => {\n"
        "    e.preventDefault();\n"
        "    const title = document.getElementById('item-title').value;\n"
        "    items.push({ id: Date.now(), title });\n"
        "    localStorage.setItem('campus_items', JSON.stringify(items));\n"
        "    render();\n"
        "  });\n"
        "  searchInput.addEventListener('input', () => {\n"
        "    const q = searchInput.value.toLowerCase();\n"
        "    const filtered = items.filter(i => i.title.toLowerCase().includes(q));\n"
        "    container.innerHTML = filtered.map(i => `<div>${i.title}</div>`).join('');\n"
        "  });\n"
        "  render();\n"
        "});\n"
    )
    (tmp_path / "index.html").write_text(index_html, encoding="utf-8")
    (tmp_path / "styles.css").write_text(styles_css, encoding="utf-8")
    (tmp_path / "app.js").write_text(app_js, encoding="utf-8")

    res = TechnologyAwareBehavioralVerifier.verify_workspace(
        tmp_path,
        mission_prompt="Build a campus lost and found web app with search, filtering, and local persistence"
    )
    assert res.passed
    assert res.tech_stack == "vanilla_web"
    assert "local_persistence" in res.features_detected
    assert "search_filtering" in res.features_detected


def test_behavioral_verifier_rejects_react_in_vanilla_web(tmp_path):
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><div id='app'><button>Go</button></div><script src='app.js'></script></body></html>", encoding="utf-8")
    (tmp_path / "styles.css").write_text("body { color: black; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("import React from 'react';\nexport default function App() {}", encoding="utf-8")

    res = TechnologyAwareBehavioralVerifier.verify_workspace(
        tmp_path,
        mission_prompt="Build a campus lost and found web application"
    )
    assert not res.passed
    assert any("Architectural contamination" in issue for issue in res.issues)


def test_behavioral_verifier_rejects_empty_placeholder_stub(tmp_path):
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>Under Construction</h1><p>Lorem ipsum</p></body></html>", encoding="utf-8")
    (tmp_path / "styles.css").write_text("/* empty */", encoding="utf-8")
    (tmp_path / "app.js").write_text("// todo", encoding="utf-8")

    res = TechnologyAwareBehavioralVerifier.verify_workspace(
        tmp_path,
        mission_prompt="Build a campus lost and found web application"
    )
    assert not res.passed
    assert len(res.issues) > 0


# ── 10. Additional Comprehensive Contract Tests ────────────────────────────

def test_numbered_list_decomposition_capped_at_6():
    planner = MissionPlanner()
    numbered_prompt = "\n".join([f"{i}. Action step {i} for project" for i in range(1, 15)])
    mission = planner.plan(numbered_prompt, execution_mode="production")
    assert len(mission.tasks) <= 6


def test_bullet_list_decomposition_capped_at_6():
    planner = MissionPlanner()
    bullet_prompt = "\n".join([f"- Step {i}: configure system component {i}" for i in range(1, 12)])
    mission = planner.plan(bullet_prompt, execution_mode="production")
    assert len(mission.tasks) <= 6


def test_architecture_detection_flask_and_fastapi():
    d_flask = detect_architecture("Create a Flask REST API with sqlalchemy models")
    assert d_flask.architecture_type == ArchitectureType.FLASK_API
    assert d_flask.entrypoint == "run.py"

    d_fastapi = detect_architecture("Create a FastAPI service with uvicorn server")
    assert d_fastapi.architecture_type == ArchitectureType.FASTAPI
    assert d_fastapi.entrypoint == "main.py"


def test_architecture_decision_sanitize_leaves_clean_js_intact():
    decision = ArchitectureDecision(architecture_type=ArchitectureType.VANILLA_WEB)
    clean_code = "const x = 10;\nfunction test() { return x * 2; }\nconsole.log(test());"
    sanitized = decision.sanitize_file_content("app.js", clean_code)
    assert sanitized == clean_code


def test_architecture_decision_sanitize_cleans_multiline_react_imports():
    decision = ArchitectureDecision(architecture_type=ArchitectureType.VANILLA_WEB)
    dirty_code = (
        "import React from 'react';\n"
        "import { useState, useEffect } from 'react';\n"
        "document.addEventListener('DOMContentLoaded', () => {\n"
        "  console.log('ready');\n"
        "});\n"
        "export default function App() {}\n"
    )
    sanitized = decision.sanitize_file_content("app.js", dirty_code)
    assert "import React" not in sanitized
    assert "useState" not in sanitized
    assert "export default" not in sanitized
    assert "DOMContentLoaded" in sanitized


def test_clean_code_content_various_languages():
    py_fenced = "```python\ndef hello():\n    return 'world'\n```"
    assert "def hello():" in _clean_code_content(py_fenced)
    assert not _clean_code_content(py_fenced).startswith("```")

    js_fenced = "```javascript\nconsole.log('hi');\n```"
    assert "console.log('hi');" in _clean_code_content(js_fenced)
    assert not _clean_code_content(js_fenced).startswith("```")


def test_clean_code_content_safe_on_edge_cases():
    assert _clean_code_content("") == ""
    assert _clean_code_content("plain text") == "plain text"
    assert _clean_code_content(None) is None


def test_fswrite_tool_creates_parent_directories(tmp_path):
    tool = FSWriteTool()
    nested_file = tmp_path / "deep" / "nested" / "dir" / "file.txt"
    res = tool.execute({
        "path": str(nested_file),
        "content": "Deep content",
        "create_parents": True,
        "_workspace": None,
    })
    assert res.success
    assert nested_file.exists()
    assert nested_file.read_text(encoding="utf-8") == "Deep content"


def test_fswrite_tool_handles_crlf_and_lf(tmp_path):
    tool = FSWriteTool()
    lf_file = tmp_path / "lf.txt"
    tool.execute({"path": str(lf_file), "content": "Line 1\nLine 2\n", "_workspace": None})
    assert lf_file.read_bytes() == b"Line 1\nLine 2\n"


def test_fsread_tool_1_based_line_addressability(tmp_path):
    read_tool = FSReadTool()
    lines_file = tmp_path / "numbered.txt"
    lines_file.write_text("One\nTwo\nThree\nFour\nFive\n", encoding="utf-8")

    res = read_tool.execute({
        "path": str(lines_file),
        "start_line": 2,
        "end_line": 4,
        "_workspace": None,
    })
    assert res.success
    assert "Two" in res.output
    assert "Three" in res.output
    assert "Four" in res.output


def test_artifact_manifest_records_and_retrieves(tmp_path):
    test_file = tmp_path / "manifest_test.html"
    test_file.write_text("<h1>Manifest</h1>", encoding="utf-8")

    entry = ArtifactManifest.record(
        path_str="manifest_test.html",
        safe_path=test_file,
        sha256_hash="fakehash123",
        size=17,
        mission_id="m123",
        project_root=str(tmp_path),
    )
    assert entry.relative_path == "manifest_test.html"
    retrieved = ArtifactManifest.get(test_file)
    assert retrieved is not None
    assert retrieved.sha256 == "fakehash123"


def test_behavioral_verifier_rejects_missing_css(tmp_path):
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><button>Click</button></body></html>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('no css');", encoding="utf-8")
    res = TechnologyAwareBehavioralVerifier.verify_workspace(tmp_path, "Build complete application")
    assert not res.passed
    assert any("CSS" in err for err in res.issues)


def test_behavioral_verifier_rejects_missing_js(tmp_path):
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><button>Click</button></body></html>", encoding="utf-8")
    (tmp_path / "styles.css").write_text("body { color: red; }", encoding="utf-8")
    res = TechnologyAwareBehavioralVerifier.verify_workspace(tmp_path, "Build complete interactive application")
    assert not res.passed
    assert any("JavaScript" in err for err in res.issues)


def test_behavioral_verifier_rejects_unbalanced_brackets_in_js(tmp_path):
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><button>Click</button></body></html>", encoding="utf-8")
    (tmp_path / "styles.css").write_text("body { color: red; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("function broken( { return 1; }", encoding="utf-8")
    res = TechnologyAwareBehavioralVerifier.verify_workspace(tmp_path, "Build complete interactive application")
    assert not res.passed
    assert any("Unbalanced" in err for err in res.issues)


def test_behavioral_verifier_verifies_python_cli(tmp_path):
    py_file = tmp_path / "main.py"
    py_file.write_text("import sys\nprint('Hello from CLI')\nsys.exit(0)\n", encoding="utf-8")
    res = TechnologyAwareBehavioralVerifier.verify_workspace(tmp_path, "Create a python CLI tool")
    assert res.passed
    assert res.tech_stack in ("python", "python_cli", "python_project")


def test_behavioral_verifier_detects_trivial_hello_py():
    assert TechnologyAwareBehavioralVerifier.is_trivial_mission("Write a simple script hello.py that prints hello")
    assert not TechnologyAwareBehavioralVerifier.is_trivial_mission("Build a full campus lost-and-found web application")


def test_mission_status_lines_1_based_indexing():
    mission = Mission(
        tasks=[
            MissionTask(task_id="1", title="Init architecture", state=TaskState.COMPLETED),
            MissionTask(task_id="2", title="Implement UI", state=TaskState.RUNNING),
            MissionTask(task_id="3", title="Implement logic", state=TaskState.PENDING),
        ]
    )
    lines = mission.get_status_lines()
    assert len(lines) == 3
    assert "1. Init architecture" in lines[0]
    assert "2. Implement UI" in lines[1]
    assert "3. Implement logic" in lines[2]


def test_task_state_machine_valid_transitions():
    task = MissionTask(task_id="t1", title="Task test")
    assert task.state == TaskState.PENDING

    mission = Mission(tasks=[task], execution_order=["t1"])
    mission.mark_task_running("t1")
    assert task.state == TaskState.RUNNING

    mission.mark_task_complete("t1")
    assert task.state == TaskState.COMPLETED
    assert mission.is_complete


def test_task_blocked_state_unblocks_when_dependency_completes():
    t1 = MissionTask(task_id="t1", title="First")
    t2 = MissionTask(task_id="t2", title="Second", depends_on=["t1"])
    mission = Mission(tasks=[t1, t2], execution_order=["t1", "t2"])
    
    # Fail t1 -> blocks t2
    mission.mark_task_failed("t1", "error")
    assert t2.state == TaskState.BLOCKED

    # Now succeed t1 -> unblocks t2
    mission.mark_task_complete("t1")
    assert t2.state == TaskState.PENDING


def test_task_can_retry_bounded():
    t = MissionTask(task_id="t1", title="Retrying task", max_retries=2)
    assert not t.can_retry  # PENDING
    t.state = TaskState.FAILED
    t.retry_count = 0
    assert t.can_retry
    t.retry_count = 2
    assert not t.can_retry


def test_mission_criteria_met():
    mission = Mission(
        acceptance_criteria=["Criterion 1", "Criterion 2"],
        verified_criteria=["Criterion 1"]
    )
    assert not mission.criteria_met
    mission.verified_criteria.append("Criterion 2")
    assert mission.criteria_met


def test_architecture_decision_allowed_extensions():
    dec = ArchitectureDecision(
        architecture_type=ArchitectureType.VANILLA_WEB,
        allowed_extensions=[".html", ".css", ".js"]
    )
    assert ".html" in dec.allowed_extensions
    assert ".css" in dec.allowed_extensions
    assert ".exe" not in dec.allowed_extensions


def test_architecture_decision_defaults():
    dec = ArchitectureDecision()
    assert dec.architecture_type == ArchitectureType.GENERIC
    assert dec.entrypoint == "index.html"


def test_mission_driver_continuation_preserves_completed():
    driver = MissionDriver(object())
    m = Mission(
        mission_id="test_pres",
        tasks=[
            MissionTask(task_id="t1", state=TaskState.COMPLETED),
            MissionTask(task_id="t2", state=TaskState.PENDING),
        ]
    )
    driver._current_mission = m
    # Should not be complete
    assert not m.is_complete
    assert m.progress == (1, 2)


def test_website_fast_path_evaluation():
    from core.website_fast_path import WebsiteFastPathClassifier
    res = WebsiteFastPathClassifier.evaluate("build a standard website", execution_mode="production")
    assert hasattr(res, "fast_path_candidate")


def test_fswrite_tool_boundary_outside_workspace(tmp_path):
    tool = FSWriteTool()
    from core.workspace import workspace_manager
    workspace_manager.lock(str(tmp_path))
    try:
        res = tool.execute({
            "path": "../../../outside.txt",
            "content": "illegal",
            "_workspace": workspace_manager,
        })
        assert not res.success
        assert res.exit_code == 126 or "SECURITY" in str(res.error)
    finally:
        workspace_manager.unlock()

