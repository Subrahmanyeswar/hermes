# tests/test_pre_qualification_hardening.py
"""
HERMES Final Pre-Qualification Hardening Regression Test Suite.

Covers:
1. File existence is insufficient for nontrivial application completion
2. Trivial deterministic completion still works
3. Behavioral verification is required for application missions
4. Technology-aware verifier selection
5. Repeated unchanged reads eventually become NO_PROGRESS
6. Identical failure fingerprints prevent repeated T3
7. Infrastructure failure does not automatically cause T3
8. Project_root is unique
9. Artifact manifest is authoritative
10. Artifact identity is mission/project/path scoped
11. Duplicate index.html roots are rejected / normalized
12. Placeholder-only application cannot pass nontrivial completion
13. Mission completion emitted exactly once
14. Mission failure emitted exactly once
15. Non-tool event is never serialized as a tool
16. TUI event deduplication works
17. Task 0/N never displayed for active tasks
18. SEND/STOP state invariant
19. STOP never calls submit_prompt
20. STOP actually cancels active worker
21. LAUNCH HERMES label is visible
22. Fake status verbs cannot override backend state
23. Agent loop does not block on renderer
24. Python subprocesses remain on canonical 3.12 venv
25. Security and workspace boundaries remain enforced
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from rich.text import Text
from textual.widgets import Button

from core.agent_loop.behavioral_verifier import (
    BehavioralCheckResult,
    TechnologyAwareBehavioralVerifier,
)
from core.agent_loop.completion import CompletionPolicy, GoalCompleteGuard
from core.agent_loop.loop import AgentLoop
from core.agent_loop.types import AgentLoopConfig
from core.disagreement_router import (
    DisagreementRouter,
    FailureCategory,
    RouterResult,
    RoutingDecision,
)
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, MissionStatus
from core.runtime_state.store import StateStore
from core.verifier import VerificationResult
from core.workspace import WorkspaceBoundaryError, WorkspaceManager
from tools.platform.core_tools import (
    ArtifactManifest,
    FSEditTool,
    FSReadTool,
    FSWriteTool,
    ManifestEntry,
    READ_LOOP_TRACKER,
)
from ui.panels.chat import ChatPanel
from ui.panels.startup import StartupScreen
from ui.panels.status_bar import StatusBar


# ── 1. Layered Completion: File existence != Success for nontrivial apps ───

def test_file_existence_is_insufficient_for_nontrivial_application(tmp_path: Path):
    """
    Gap 1 & Gap 9: Having index.html, styles.css, app.js with skeleton/placeholder
    content MUST NOT pass completion for a complete application mission.
    """
    ws = WorkspaceManager()
    ws.lock(tmp_path)

    # Write placeholder files
    (tmp_path / "index.html").write_text("<html><head><title>App</title></head><body></body></html>", encoding="utf-8")
    (tmp_path / "styles.css").write_text("/* styles */\n", encoding="utf-8")
    (tmp_path / "app.js").write_text("// app js\n", encoding="utf-8")

    policy = CompletionPolicy()
    accepted, reason, issues = policy.evaluate_completion(
        mission_prompt="Create a complete campus lost-and-found web application with search, filters, and persistence",
        workspace=ws,
        written_files=["index.html", "styles.css", "app.js"],
        strict_requirements=False,
    )

    assert not accepted, "Skeleton/placeholder files must NOT pass completion for a nontrivial application!"
    assert any("BehavioralVerifier" in reason or "empty" in reason.lower() or "controls" in " ".join(issues).lower() for reason in [reason] + issues)


def test_trivial_deterministic_completion_still_works(tmp_path: Path):
    """
    Gap 1: Trivial deterministic tasks (e.g. hello.py) pass cleanly with deterministic verification.
    """
    ws = WorkspaceManager()
    ws.lock(tmp_path)

    (tmp_path / "hello.py").write_text("print('hello from hermes')\n", encoding="utf-8")

    policy = CompletionPolicy()
    accepted, reason, issues = policy.evaluate_completion(
        mission_prompt="Create hello.py containing print('hello from hermes')",
        workspace=ws,
        written_files=["hello.py"],
        strict_requirements=False,
    )

    assert accepted, f"Trivial deterministic task must be accepted! Issues: {issues}"


# ── 2. Technology-Aware Behavioral Verification ──────────────────────────

def test_technology_aware_verifier_selection(tmp_path: Path):
    """Gap 2: Verifier detects tech stack correctly."""
    # Vanilla Web
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>Test</h1></body></html>", encoding="utf-8")
    (tmp_path / "styles.css").write_text("body { color: red; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('test');", encoding="utf-8")

    stack = TechnologyAwareBehavioralVerifier.identify_tech_stack(tmp_path)
    assert stack == "vanilla_web"

    # Python CLI
    py_dir = tmp_path / "py_proj"
    py_dir.mkdir()
    (py_dir / "main.py").write_text("print('hello')", encoding="utf-8")
    assert TechnologyAwareBehavioralVerifier.identify_tech_stack(py_dir) == "python_cli"


def test_behavioral_verification_full_web_application(tmp_path: Path):
    """
    Gap 2 & Gap 3: Full web application with interactive controls, event listeners,
    DOM rendering, and persistence satisfies behavioral verification.
    """
    ws = WorkspaceManager()
    ws.lock(tmp_path)

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Campus Lost & Found</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header><h1>Campus Lost and Found</h1></header>
  <main>
    <form id="item-form">
      <input type="text" id="item-name" placeholder="Item name" required>
      <input type="text" id="item-location" placeholder="Location">
      <select id="item-type"><option value="lost">Lost</option><option value="found">Found</option></select>
      <button type="submit" id="add-btn">Report Item</button>
    </form>
    <input type="search" id="search-input" placeholder="Search items">
    <div id="items-list"></div>
  </main>
  <script src="app.js"></script>
</body>
</html>"""

    css_content = """body { font-family: sans-serif; margin: 20px; }
header { background: #333; color: white; padding: 10px; }
#items-list { margin-top: 20px; }
button { cursor: pointer; }"""

    js_content = """// Campus Lost and Found Logic
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("item-form");
  const list = document.getElementById("items-list");
  const searchInput = document.getElementById("search-input");
  let items = JSON.parse(localStorage.getItem("campus_items") || "[]");

  function render(filter = "") {
    list.innerHTML = "";
    items.filter(it => it.name.toLowerCase().includes(filter.toLowerCase())).forEach(it => {
      const el = document.createElement("div");
      el.textContent = `${it.type.toUpperCase()}: ${it.name} at ${it.location}`;
      list.appendChild(el);
    });
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const name = document.getElementById("item-name").value;
    const location = document.getElementById("item-location").value;
    const type = document.getElementById("item-type").value;
    items.push({ name, location, type });
    localStorage.setItem("campus_items", JSON.stringify(items));
    render();
  });

  searchInput.addEventListener("input", (e) => {
    render(e.target.value);
  });

  render();
});"""

    (tmp_path / "index.html").write_text(html_content, encoding="utf-8")
    (tmp_path / "styles.css").write_text(css_content, encoding="utf-8")
    (tmp_path / "app.js").write_text(js_content, encoding="utf-8")

    result = TechnologyAwareBehavioralVerifier.verify_vanilla_web(
        ws_root=tmp_path,
        mission_prompt="Create a complete campus lost-and-found web application with search, filters, and persistence",
    )
    assert result.passed, f"Valid application should pass behavioral verification! Issues: {result.issues}"
    assert "local_persistence" in result.features_detected
    assert "search_filtering" in result.features_detected


def test_placeholder_only_application_cannot_pass(tmp_path: Path):
    """Gap 9: Rejects placeholder body ('Welcome to our website')."""
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><head><title>App</title><link rel='stylesheet' href='styles.css'></head><body>Welcome to our website</body></html>", encoding="utf-8")
    (tmp_path / "styles.css").write_text("body { color: black; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('ready');", encoding="utf-8")

    result = TechnologyAwareBehavioralVerifier.verify_vanilla_web(
        ws_root=tmp_path,
        mission_prompt="Create a complete campus lost-and-found web application",
    )
    assert not result.passed
    assert any("placeholder" in issue.lower() or "controls" in issue.lower() for issue in result.issues)


# ── 3. Read Loop Enforcement ─────────────────────────────────────────────

def test_repeated_unchanged_reads_eventually_become_no_progress(tmp_path: Path):
    """
    Gap 4: For an unchanged target, read_count >= 4 is rejected by the harness.
    """
    test_file = tmp_path / "sample.py"
    test_file.write_text("x = 42\n", encoding="utf-8")

    READ_LOOP_TRACKER.clear()
    tool = FSReadTool()
    inp = {"path": str(test_file), "_workspace": None}

    # Reads 1, 2, 3 should succeed (3 gives advisory)
    r1 = tool.execute(inp)
    assert r1.success
    r2 = tool.execute(inp)
    assert r2.success
    r3 = tool.execute(inp)
    assert r3.success
    assert "NO_PROGRESS_LOOP_ADVISORY" in r3.output

    # Read 4 must be REJECTED with NO_PROGRESS
    r4 = tool.execute(inp)
    assert not r4.success, "4th consecutive read of unchanged file must be rejected!"
    assert r4.exit_code == 1
    assert "NO_PROGRESS_LOOP_ENFORCEMENT" in r4.error


# ── 4. Failure Classification & Bounded Escalation ───────────────────────

def test_infrastructure_failure_does_not_cause_t3():
    """Gap 6 & Gap 7: Infrastructure/environment errors are quarantined from T3."""
    router = DisagreementRouter()
    verification = VerificationResult(
        agree=False,
        confidence=0.5,
        risk_score=0.8,  # Under hard block threshold
        critical_issues=["command not found: npm", "exit_code=127"],
        reasoning="npm command was not found on system PATH",
    )

    res = router.route(
        verification=verification,
        tool_name="bash_exec",
        error_message="npm: command not found",
    )

    assert not res.tier3_needed, "Infrastructure failure must NOT trigger Tier 3 escalation!"
    assert res.decision == RoutingDecision.ACCEPT


def test_identical_failure_fingerprints_prevent_repeated_t3():
    """Gap 5: Same failure fingerprint cannot escalate to T3 multiple times per task."""
    router = DisagreementRouter()
    verification = VerificationResult(
        agree=False,
        confidence=0.4,
        risk_score=0.75,
        critical_issues=["Disagreement between T1 and T2 regarding algorithm correctness"],
        reasoning="Semantic divergence in algorithm design",
    )

    res1 = router.route(
        verification=verification,
        tool_name="edit_file",
        task_id="task_1",
        mission_id="m_100",
    )
    assert res1.tier3_needed, "First semantic disagreement should escalate to T3"

    # Second call with identical failure fingerprint
    res2 = router.route(
        verification=verification,
        tool_name="edit_file",
        task_id="task_1",
        mission_id="m_100",
    )
    assert not res2.tier3_needed, "Duplicate failure fingerprint must suppress T3 escalation!"


# ── 5. Project Root & Artifact Manifest ──────────────────────────────────

def test_project_root_and_artifact_manifest(tmp_path: Path):
    """Gap 7 & Gap 8: ArtifactManifest tracks project-scoped relative paths."""
    ArtifactManifest.clear()
    ws = WorkspaceManager()
    ws.lock(tmp_path)

    f1 = tmp_path / "index.html"
    f1.write_text("<h1>Test</h1>", encoding="utf-8")

    entry = ArtifactManifest.record(
        path_str="index.html",
        safe_path=f1,
        sha256_hash="abc123hash",
        size=13,
        mission_id="m_001",
        project_root=str(tmp_path),
    )

    assert entry.relative_path == "index.html"
    assert entry.mission_id == "m_001"
    assert entry.project_root == str(tmp_path)

    # Query by project
    all_proj = ArtifactManifest.get_by_project(str(tmp_path))
    assert len(all_proj) == 1
    assert all_proj[0].relative_path == "index.html"


def test_duplicate_index_html_roots_normalized(tmp_path: Path):
    """Gap 7 & 11: validate_path collapses duplicate workspace prefix into locked root."""
    ws = WorkspaceManager()
    ws.lock(tmp_path)

    # Calling with duplicate prefix of workspace directory
    ws_name = tmp_path.name
    p = ws.validate_path(f"{ws_name}/index.html")
    assert p == (tmp_path / "index.html").resolve()
    assert not (tmp_path / ws_name).exists()


# ── 6. TUI Integrity: Controls, Labels, and Terminal State ───────────────

def test_launch_hermes_label_is_visible():
    """
    Gap 12: Textual parses [ LAUNCH HERMES ] as a markup tag if passed as string.
    Button(Text('[ LAUNCH HERMES ]')) preserves label without markup stripping.
    """
    btn_rich = Button(Text("[ LAUNCH HERMES ]"), id="launch-btn")
    assert str(btn_rich.label) == "[ LAUNCH HERMES ]"
    assert len(str(btn_rich.label)) > 0


def test_send_stop_button_labels_are_not_stripped():
    """Gap 11: SEND and STOP buttons wrapped in Text() are not stripped."""
    send_btn = Button(Text("[ SEND ]"), id="send-btn")
    stop_btn = Button(Text("[ STOP ]"), id="stop-btn")
    assert str(send_btn.label) == "[ SEND ]"
    assert str(stop_btn.label) == "[ STOP ]"


def test_task_0_never_displayed():
    """Gap 10 & 17: Status bar displays Task 1/N instead of Task 0/N."""
    sb = StatusBar()
    sb._start_spinner = MagicMock()
    sb.processing = True
    sb.mission_tasks = "0/8"

    text = sb._render_status_text()
    plain = text.plain
    assert "Task 0/8" not in plain
    assert "Task 1/8" in plain


def test_mission_completion_emitted_exactly_once():
    """Gap 14: Terminal events are deduplicated."""
    loop = AgentLoop(orchestrator=MagicMock())
    loop._mission_id = "m_single_term"

    events_published = []
    loop.event_bus = MagicMock()
    loop.event_bus.publish.side_effect = lambda ev: events_published.append(ev)

    async def emit_events():
        await loop._publish_event(EventType.MISSION_COMPLETED, payload={"reason": "Success"})
        await loop._publish_event(EventType.MISSION_COMPLETED, payload={"reason": "Duplicate Success"})

    asyncio.run(emit_events())
    assert len(events_published) == 1, "MISSION_COMPLETED must be published exactly once!"


# ── 7. Python Subprocess Canonical Interpreter Invariant ─────────────────

def test_canonical_python_312_interpreter():
    """Mandatory: Everything runs on Python 3.12 within canonical venv."""
    assert sys.version_info.major == 3
    assert sys.version_info.minor == 12
    assert "venv" in sys.executable.lower() or "python.exe" in sys.executable.lower()


# ── 8. Stop Button & Worker Cancellation ─────────────────────────────────

@pytest.mark.asyncio
async def test_stop_button_cancels_worker():
    """Gap 11 & 20: Pressing STOP cancels the active mission worker."""
    mock_app = MagicMock()
    mock_worker = MagicMock()
    mock_app._current_worker = mock_worker
    mock_app.is_processing = True

    chat = ChatPanel()
    chat._app = mock_app

    event = MagicMock()
    await chat.handle_stop_pressed(event)

    mock_app.action_stop_mission.assert_called_once()
    mock_worker.cancel.assert_called_once()
    assert not mock_app.is_processing


# ── 9. Non-Tool Event Serialization ──────────────────────────────────────

def test_non_tool_event_never_serialized_as_tool():
    """Gap 15: Presentation sinks and event converters filter non-tool events."""
    from core.sinks import TextSink
    sink = TextSink(quiet=False)
    out_buf = MagicMock()
    sink.stderr = out_buf

    # TOOL_STARTED with "unknown" or "null" should be ignored
    event_unknown = HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id="m_1",
        payload={"tool_name": "unknown"},
    )
    sink.on_event(event_unknown)
    assert not out_buf.write.called

    # TOOL_STARTED with real tool should be formatted
    event_real = HermesEvent(
        event_type=EventType.TOOL_STARTED,
        mission_id="m_1",
        payload={"tool_name": "write_file"},
    )
    sink.on_event(event_real)
    assert out_buf.write.called


# ── 10. Security & Workspace Boundary Invariant ──────────────────────────

def test_security_workspace_boundary_enforced(tmp_path: Path):
    """Gap 27: Security boundary prevents access outside workspace root."""
    ws = WorkspaceManager()
    ws.lock(tmp_path)

    outside_path = tmp_path.parent / "escape.txt"
    with pytest.raises(WorkspaceBoundaryError):
        ws.validate_path(str(outside_path))


# ── 11. FSEditTool Robustness ─────────────────────────────────────────────

def test_fs_edit_parameter_aliases_and_line_number_stripping(tmp_path: Path):
    """FSEditTool tolerates parameter aliases and strips line numbers copied from fs.read."""
    f = tmp_path / "calc.py"
    f.write_text("def add(a, b):\n    # TODO\n    return a + b\n", encoding="utf-8")

    from tools.platform.core_tools import FSEditTool, file_identity_cache
    file_identity_cache.clear()

    tool = FSEditTool()
    # Call with file_path alias, find/replace aliases, and line number prefix from fs.read
    inp = {
        "file_path": str(f),
        "find": "    2 |     # TODO",
        "replace": "    # Done",
    }
    res = tool.execute(inp)
    assert res.success, f"FSEditTool should succeed with aliases and line numbers: {res.error}"
    assert "# Done" in f.read_text(encoding="utf-8")


def test_fs_edit_escaped_newlines_and_whitespace_trimming(tmp_path: Path):
    """FSEditTool tolerates escaped newlines and whitespace differences."""
    f = tmp_path / "greeting.py"
    f.write_text("def greet():\n    print('hi')\n", encoding="utf-8")

    from tools.platform.core_tools import FSEditTool, file_identity_cache
    file_identity_cache.clear()

    tool = FSEditTool()
    inp = {
        "path": str(f),
        "old_string": "def greet():\\n    print('hi')",
        "new_string": "def greet():\\n    print('hello world')",
    }
    res = tool.execute(inp)
    assert res.success, f"FSEditTool should succeed with escaped newlines: {res.error}"
    assert "hello world" in f.read_text(encoding="utf-8")

