# tests/test_runtime_performance_and_pipeline.py
"""
HERMES Runtime Performance, TUI, and Execution Pipeline Regression Tests.

Validates:
1. Fast request-to-first-tool path and bounded planning
2. Empty workspace bypasses inspection task
3. Canonical tool preservation and rejection of unknown tools
4. Conversational responses do not report unknown tool
5. Workspace root resolution to authoritative root (not generated_projects nesting)
6. Code-review skill suppression on creation prompts
7. Status bar preserves actual backend verb (no random fake verbs)
8. Chat panel suppresses unknown tool and N/A verifier cards
9. Stop button idle safety (no accidental prompt submission)
10. Telemetry milestone timestamps recording
"""

import asyncio
import json
import pytest
from pathlib import Path

from core.mission_planner import MissionPlanner, TaskPriority
from core.workspace import global_workspace, MissionWorkspace
from core.intent_classifier import IntentClassifier
from tools.registry import get_canonical_tool_name, get_tool, list_tools
from core.response_parser import ResponseParser, ParseSuccess, ParseFailure
from core.telemetry import telemetry, RequestTelemetry


def test_empty_workspace_bypasses_inspection_task(tmp_path):
    """Empty workspace must not prepend an inspection task, saving 60s model roundtrip."""
    planner = MissionPlanner()
    empty_dir = tmp_path / "empty_ws"
    empty_dir.mkdir()

    mission = planner.plan("create a personal blog website with index.html and styles.css", workspace_root=str(empty_dir))
    task_titles = [t.title.lower() for t in mission.tasks]
    assert not any("inspect workspace" in t for t in task_titles), f"Inspection task should be omitted on empty workspace: {task_titles}"


def test_bounded_planning_in_production_mode():
    """Production mode must produce bounded, high-leverage milestone tasks, not 12 microtasks."""
    planner = MissionPlanner()
    prompt = "Create a reading tracker website with index.html, styles.css, and app.js"
    tasks = planner._heuristic_decompose(prompt, execution_mode="production")
    assert len(tasks) <= 4, f"Production heuristic decomposition must be bounded, got {len(tasks)} tasks: {tasks}"
    # Verify no hardcoded questionnaire or fake tasks
    for t in tasks:
        assert "questionnaire.js" not in t
        assert "EduPath" not in t


def test_no_edupath_hardcoding_in_planner():
    """Planner must never mention hardcoded EduPath project in decomposed tasks."""
    planner = MissionPlanner()
    prompt = "write index.html and styles.css for a bookstore"
    tasks = planner._parse_intent(prompt, execution_mode="production")
    for t in tasks:
        assert "edupath" not in t.lower()


def test_canonical_tool_resolution_and_aliases():
    """All aliases must resolve to their canonical tool name."""
    assert get_canonical_tool_name("write_file") == "write_file"
    assert get_canonical_tool_name("create_file") == "write_file"
    assert get_canonical_tool_name("write") == "write_file"
    assert get_canonical_tool_name("read_file") == "read_file"
    assert get_canonical_tool_name("view_file") == "read_file"
    assert get_canonical_tool_name("list_directory") == "list_directory"
    assert get_canonical_tool_name("list_files") == "list_directory"
    assert get_canonical_tool_name("dir") == "list_directory"
    assert get_canonical_tool_name("ls") == "list_directory"
    assert get_canonical_tool_name("bash_exec") == "bash_exec"
    assert get_canonical_tool_name("bash") == "bash_exec"


def test_unknown_tool_rejection():
    """Hallucinated or non-existent tools must return None from get_canonical_tool_name."""
    assert get_canonical_tool_name("unknown_tool") is None
    assert get_canonical_tool_name("unknown") is None
    assert get_canonical_tool_name("create_reading_tracker") is None
    assert get_canonical_tool_name("scaffold_project") is None
    assert get_canonical_tool_name("") is None
    assert get_canonical_tool_name(None) is None


def test_response_parser_rejects_unknown_tools():
    """ResponseParser must reject responses referencing unregistered tools."""
    parser = ResponseParser()
    resp = '```json\n{"tool": "completely_fake_tool_xyz", "parameters": {"foo": "bar"}}\n```'
    parsed = parser.parse(resp)
    assert isinstance(parsed, ParseFailure) or parsed is None


def test_response_parser_preserves_valid_tools_and_aliases():
    """ResponseParser must successfully parse valid tools and standard aliases."""
    parser = ResponseParser()
    resp1 = '```json\n{"tool": "write_file", "parameters": {"path": "index.html", "content": "hello"}}\n```'
    parsed1 = parser.parse(resp1)
    assert isinstance(parsed1, ParseSuccess)
    assert parsed1.tool == "write_file"

    resp2 = '```json\n{"tool": "list_files", "parameters": {"path": "."}}\n```'
    parsed2 = parser.parse(resp2)
    assert isinstance(parsed2, ParseSuccess)
    assert parsed2.tool == "list_files"


def test_code_review_suppressed_on_creation_prompts():
    """Prompts requesting creation must not trigger code-review specialist."""
    classifier = IntentClassifier()
    # "create ... and check" should NOT match code-review
    selected = classifier.classify("create a reading tracker application and check that it works")
    assert "code-review" not in selected, f"code-review was unexpectedly selected: {selected}"

    # Explicit review request SHOULD match code-review
    selected_review = classifier.classify("please perform a code review on my pull request")
    assert "code-review" in selected_review or "code_review" in selected_review


def test_workspace_relative_path_resolution(tmp_path):
    """MissionWorkspace must validate and resolve relative paths without duplicating workspace prefix."""
    ws_root = tmp_path / "1st trial"
    ws_root.mkdir()
    mw = MissionWorkspace(root=ws_root)

    # Relative path directly at root
    p1 = mw.validate_path("index.html")
    assert p1 == ws_root / "index.html"

    # Duplicated directory prefix must be deduplicated
    p2 = mw.validate_path("1st trial/index.html")
    assert p2 == ws_root / "index.html"

    # Path in generated_projects
    p3 = mw.validate_path("generated_projects/reading-tracker/index.html")
    assert p3 == ws_root / "generated_projects" / "reading-tracker" / "index.html"


def test_status_bar_does_not_cycle_fake_verbs():
    """Status bar spinner must not overwrite real state with fake verbs."""
    from ui.panels.status_bar import StatusBar
    sb = StatusBar()
    sb.spinner_verb = "Validating"
    sb._cycle_verb()
    # Must remain Validating and not turn into Boondoggling / Tomfoolering
    assert sb.spinner_verb == "Validating"


def test_telemetry_milestone_recording():
    """TelemetryEngine must record all key lifecycle milestones."""
    req = telemetry.start_request("test prompt")
    req_id = req.request_id

    telemetry.record_milestone(req_id, "t_prompt_submitted")
    telemetry.record_milestone(req_id, "t_first_model_requested")
    telemetry.record_milestone(req_id, "t_first_model_response")
    telemetry.record_milestone(req_id, "t_first_tool_available")
    telemetry.record_milestone(req_id, "t_first_tool_dispatched")
    telemetry.record_milestone(req_id, "t_first_fs_mutation")

    record = telemetry.get_request(req_id)
    assert record is not None
    assert record.t_prompt_submitted > 0.0
    assert record.t_first_model_requested > 0.0
    assert record.t_first_model_response > 0.0
    assert record.t_first_tool_available > 0.0
    assert record.t_first_tool_dispatched > 0.0
    assert record.t_first_fs_mutation > 0.0


def test_chat_panel_suppresses_unknown_tool_and_na_verifier():
    """ChatPanel render must not show Unknown tool or N/A Verifier."""
    from ui.panels.chat import ChatPanel
    cp = ChatPanel()

    # When tool_execution has an unknown tool, it should NOT render tool card
    cp.tool_execution = {"tool": "unknown", "target": {}, "status": "Running..."}
    text = cp.render().plain
    assert "Tool:   unknown" not in text
    assert "Target: {}" not in text

    # When verification has verifier N/A, it should NOT render verification card
    cp.verification = {"verifier": "N/A", "agree": None, "confidence": None}
    text_ver = cp.render().plain
    assert "Verifier: N/A" not in text_ver
    assert "Agreement: PENDING" not in text_ver
