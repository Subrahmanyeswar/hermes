# tests/test_phase4b_action_discipline.py
"""
HERMES Phase 4B — Autonomous Action Discipline Test Suite
Tests for:
1. repeated list_directory detection
2. repeated read_file detection
3. legitimate repeated read allowed (e.g. after write)
4. non-progress scoring
5. implementation action enforcement
6. target-aware task context
7. model receives existing workspace knowledge
8. no unnecessary discovery after sufficient context
9. deterministic rejection of useless repeated action
10. successful recovery after rejected repeated action
11. complex JS implementation does not exhaust retries due to read loop
12. realistic populated browser workflow
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Canonical Python Check
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.action_discipline import (
    TaskActionContract,
    ActionMomentumTracker,
    derive_action_contract,
)
from core.mission_planner import MissionTask, TaskPriority, TaskState
from core.orchestrator import Orchestrator
from core.workspace import workspace_manager


# ── 1. Repeated list_directory detection ──────────────────────────────────────
def test_repeated_list_directory_detection(tmp_path):
    contract = TaskActionContract(
        task_id="t1",
        title="Implement app.js",
        objective="Write JavaScript logic",
        known_target_paths=["js/app.js"],
        is_implementation=True,
    )
    tracker = ActionMomentumTracker(contract, workspace_root=tmp_path)

    r1 = tracker.record_action("list_directory", {"path": "."}, workspace_changed=False, success=True, model_turn=1)
    assert not r1.is_repeat
    assert tracker.non_progress_score == 0

    r2 = tracker.record_action("list_directory", {"path": "."}, workspace_changed=False, success=True, model_turn=2)
    assert r2.is_repeat
    assert tracker.repeated_list_count == 1
    assert tracker.non_progress_score >= 2


# ── 2. Repeated read_file detection ──────────────────────────────────────────
def test_repeated_read_file_detection(tmp_path):
    contract = TaskActionContract(
        task_id="t2",
        title="Implement app.js",
        objective="Write JavaScript logic",
        known_target_paths=["js/app.js"],
        is_implementation=True,
    )
    tracker = ActionMomentumTracker(contract, workspace_root=tmp_path)

    r1 = tracker.record_action("read_file", {"path": "index.html"}, workspace_changed=False, success=True, model_turn=1)
    assert not r1.is_repeat

    r2 = tracker.record_action("read_file", {"path": "index.html"}, workspace_changed=False, success=True, model_turn=2)
    assert r2.is_repeat
    assert tracker.repeated_read_count == 1
    assert tracker.non_progress_score >= 2


# ── 3. Legitimate repeated read allowed after filesystem mutation ─────────────
def test_legitimate_repeated_read_allowed(tmp_path):
    contract = TaskActionContract(
        task_id="t3",
        title="Update styles.css",
        objective="Edit css styles",
        known_target_paths=["css/styles.css"],
        is_implementation=True,
    )
    tracker = ActionMomentumTracker(contract, workspace_root=tmp_path)

    # Initial read
    tracker.record_action("read_file", {"path": "css/styles.css"}, workspace_changed=False, success=True, model_turn=1)

    # Modification occurred
    tracker.record_action("write_file", {"path": "css/styles.css", "content": "/* new */"}, workspace_changed=True, success=True, model_turn=2)
    assert tracker.implementation_occurred

    # Subsequent re-read after mutation is legitimate verification, not repeat loop
    r3 = tracker.record_action("read_file", {"path": "css/styles.css"}, workspace_changed=False, success=True, model_turn=3)
    assert not r3.is_repeat


# ── 4. Non-progress scoring ──────────────────────────────────────────────────
def test_non_progress_scoring(tmp_path):
    contract = TaskActionContract(
        task_id="t4",
        title="Write app.js",
        objective="Write script",
        known_target_paths=["js/app.js"],
        allowed_exploration_scope=1,
        is_implementation=True,
    )
    tracker = ActionMomentumTracker(contract, workspace_root=tmp_path)

    assert tracker.non_progress_score == 0
    assert tracker.escalation_level == 0

    # Turn 1: 1st read within allowed scope
    tracker.record_action("read_file", {"path": "index.html"}, workspace_changed=False, success=True, model_turn=1)
    assert tracker.non_progress_score == 0

    # Turn 2: 2nd read exceeds exploration scope (scope=1)
    tracker.record_action("list_directory", {"path": "."}, workspace_changed=False, success=True, model_turn=2)
    assert tracker.non_progress_score == 1
    assert tracker.escalation_level == 1

    # Turn 3: 3rd read repeated -> score rises to 3 -> Level 3
    tracker.record_action("list_directory", {"path": "."}, workspace_changed=False, success=True, model_turn=3)
    assert tracker.non_progress_score == 3
    assert tracker.escalation_level == 3


# ── 5. Implementation action enforcement ──────────────────────────────────────
def test_implementation_action_enforcement(tmp_path):
    contract = TaskActionContract(
        task_id="t5",
        title="Write app.js",
        objective="Write script",
        known_target_paths=["js/app.js"],
        is_implementation=True,
    )
    tracker = ActionMomentumTracker(contract, workspace_root=tmp_path)
    tracker.non_progress_score = 3
    assert tracker.escalation_level == 3

    # Level 3 guidance explicitly mandates write_file
    guidance = tracker.get_escalation_guidance()
    assert "LEVEL 3 ENFORCEMENT" in guidance
    assert "NON_PROGRESS_READ_LOOP" in guidance
    assert "write_file" in guidance


# ── 6. Target-aware task context ──────────────────────────────────────────────
def test_target_aware_task_context(tmp_path):
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body>Test</body></html>")
    task = MissionTask(
        title="Implement JavaScript state logic in js/app.js",
        description="Write interactive event board behavior and localStorage persistence",
        target_paths=["js/app.js"],
    )
    contract = derive_action_contract(task, workspace_root=tmp_path)

    assert "js/app.js" in contract.known_target_paths
    assert contract.is_implementation is True
    assert "index.html" in contract.prerequisite_artifacts

    prompt_summary = contract.get_summary_prompt_section(workspace_root=tmp_path)
    assert "TARGET ARTIFACT(S): js/app.js" in prompt_summary
    assert "MISSING (MUST CREATE)" in prompt_summary
    assert "REQUIRED OPERATION: WRITE_FILE" in prompt_summary


# ── 7. Model receives existing workspace knowledge ────────────────────────────
def test_model_receives_existing_workspace_knowledge(tmp_path):
    (tmp_path / "index.html").write_text("<html><div id='cards-container'></div></html>")
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "styles.css").write_text(":root { --primary: #3b82f6; }")

    task = MissionTask(
        title="Implement event cards rendering",
        description="Wire cards rendering logic",
        target_paths=["js/app.js"],
    )
    contract = derive_action_contract(task, workspace_root=tmp_path)
    summary = contract.get_summary_prompt_section(workspace_root=tmp_path)

    assert "index.html: READY" in summary
    assert "css/styles.css: READY" in summary


# ── 8. No unnecessary discovery after sufficient context ──────────────────────
def test_no_unnecessary_discovery_after_sufficient_context(tmp_path):
    contract = TaskActionContract(
        task_id="t8",
        title="Implement js/app.js",
        objective="Write script",
        known_target_paths=["js/app.js"],
        prerequisite_artifacts=["index.html", "css/styles.css"],
        allowed_exploration_scope=0,  # Zero exploration because prerequisites already known
        is_implementation=True,
    )
    tracker = ActionMomentumTracker(contract, workspace_root=tmp_path)

    # First read-only call immediately scores non-progress
    tracker.record_action("list_directory", {"path": "."}, workspace_changed=False, success=True, model_turn=1)
    assert tracker.non_progress_score >= 1
    assert tracker.escalation_level >= 1


# ── 9. Deterministic rejection of useless repeated action ─────────────────────
def test_deterministic_rejection_of_useless_repeated_action(tmp_path):
    contract = TaskActionContract(
        task_id="t9",
        title="Implement app.js",
        objective="Write script",
        known_target_paths=["js/app.js"],
        is_implementation=True,
    )
    tracker = ActionMomentumTracker(contract, workspace_root=tmp_path)
    tracker.non_progress_score = 3  # Level 3 reached

    should_reject, reason = tracker.should_reject_read_action("list_directory")
    assert should_reject is True
    assert "NON_PROGRESS_READ_LOOP" in reason
    assert "rejected" in reason.lower()

    # Mutation action must NOT be rejected
    should_reject_write, _ = tracker.should_reject_read_action("write_file")
    assert should_reject_write is False


# ── 10. Successful recovery after rejected repeated action ────────────────────
def test_successful_recovery_after_rejected_repeated_action(tmp_path):
    contract = TaskActionContract(
        task_id="t10",
        title="Implement app.js",
        objective="Write script",
        known_target_paths=["js/app.js"],
        is_implementation=True,
    )
    tracker = ActionMomentumTracker(contract, workspace_root=tmp_path)
    tracker.non_progress_score = 3

    # Rejection of read action
    rejected, _ = tracker.should_reject_read_action("list_directory")
    assert rejected is True

    # Model recovers and invokes write_file
    r_write = tracker.record_action(
        "write_file",
        {"path": "js/app.js", "content": "console.log('loaded');"},
        workspace_changed=True,
        success=True,
        model_turn=4
    )
    assert r_write.is_progress is True
    assert tracker.implementation_occurred is True
    assert tracker.non_progress_score == 1  # Decremented on progress!


# ── 11. Complex JS implementation does not exhaust retries due to read loop ───
def test_complex_js_implementation_does_not_exhaust_retries(tmp_path):
    (tmp_path / "index.html").write_text("<div id='cards'></div>")
    task = MissionTask(
        title="Implement interactive logic, state management, and persistence",
        description="Implement event board interactive logic and local persistence",
        target_paths=["js/app.js"],
    )
    contract = derive_action_contract(task, workspace_root=tmp_path)
    tracker = ActionMomentumTracker(contract, workspace_root=tmp_path)

    # Turn 1: model attempts list_directory
    tracker.record_action("list_directory", {"path": "."}, workspace_changed=False, success=True, model_turn=1)

    # Turn 2: model attempts repeated list_directory -> triggers escalation
    tracker.record_action("list_directory", {"path": "."}, workspace_changed=False, success=True, model_turn=2)
    guidance = tracker.get_escalation_guidance()
    assert guidance != ""
    assert "ACTION DISCIPLINE" in guidance

    # Turn 3: 3rd repeated list_directory is rejected by enforcement gate
    tracker.record_action("list_directory", {"path": "."}, workspace_changed=False, success=True, model_turn=3)
    should_rej, reason = tracker.should_reject_read_action("list_directory")
    assert should_rej is True
    assert "NON_PROGRESS_READ_LOOP" in reason
    assert tracker.contract.expected_operation == "write_file"


# ── 12. Realistic populated browser workflow validation ───────────────────────
@pytest.mark.asyncio
async def test_populated_browser_workflow(tmp_path):
    from core.quality_verifier import QualityVerifier
    # Setup full populated campus event board (> 500B html, > 250B css, > 200B js)
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Campus Event Board</title>
    <link rel="stylesheet" href="css/styles.css">
</head>
<body>
    <header class="header">
        <h1>Campus Events</h1>
        <div class="controls">
            <input type="search" id="search-input" placeholder="Search events...">
            <select id="category-filter">
                <option value="all">All Categories</option>
                <option value="tech">Technology</option>
                <option value="career">Career</option>
                <option value="arts">Arts & Music</option>
            </select>
        </div>
    </header>
    <main>
        <section id="cards-container" class="cards-grid"></section>
    </main>
    <div id="event-modal" class="modal hidden">
        <div class="modal-content">
            <button id="close-modal" class="close-btn">&times;</button>
            <div id="modal-body"></div>
        </div>
    </div>
    <script src="js/app.js"></script>
</body>
</html>"""
    (tmp_path / "index.html").write_text(html_content, encoding="utf-8")

    (tmp_path / "css").mkdir()
    css_content = """:root {
    --primary: #2563eb;
    --background: #f8fafc;
    --card-bg: #ffffff;
    --text-primary: #1e293b;
    --text-muted: #64748b;
    --border-color: #e2e8f0;
}
body { font-family: system-ui, sans-serif; background: var(--background); margin: 0; padding: 20px; }
.cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
.card { background: var(--card-bg); border-radius: 8px; border: 1px solid var(--border-color); padding: 16px; transition: transform 0.2s; }
.card:hover { transform: translateY(-3px); box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); }
@media (max-width: 768px) { .cards-grid { grid-template-columns: 1fr; } }"""
    (tmp_path / "css" / "styles.css").write_text(css_content, encoding="utf-8")

    (tmp_path / "js").mkdir()
    js_content = """const sampleEvents = [
  { id: 1, title: 'AI & Robotics Hackathon 2026', category: 'tech', date: '2026-10-15', location: 'Tech Hub 101', interested: 42 },
  { id: 2, title: 'Fall Engineering Career Fair', category: 'career', date: '2026-10-20', location: 'Student Union Hall', interested: 110 },
  { id: 3, title: 'Autonomous Navigation Workshop', category: 'tech', date: '2026-10-22', location: 'Robotics Lab 3', interested: 28 },
  { id: 4, title: 'Annual Campus Jazz Concert', category: 'arts', date: '2026-10-28', location: 'Campus Amphitheater', interested: 85 }
];
let events = JSON.parse(localStorage.getItem('campus_events')) || sampleEvents;
function saveEvents() { localStorage.setItem('campus_events', JSON.stringify(events)); }
function renderEvents(items) {
  const container = document.getElementById('cards-container');
  if (!container) return;
  container.innerHTML = items.map(e => `
    <article class="card event-card" data-id="${e.id}">
      <h3>${e.title}</h3>
      <p class="category">${e.category}</p>
      <p class="date">${e.date} | ${e.location}</p>
      <button class="interested-btn">Interested (${e.interested})</button>
    </article>
  `).join('');
}
document.addEventListener('DOMContentLoaded', () => { renderEvents(events); saveEvents(); });"""
    (tmp_path / "js" / "app.js").write_text(js_content, encoding="utf-8")

    qv = QualityVerifier()
    res = qv.verify_project_completeness(
        project_root=str(tmp_path),
        acceptance_criteria=[
            "index.html exists with semantic structure and controls",
            "css/styles.css exists with responsive styles",
            "js/app.js exists with data and search/filter logic",
            "No unresolved placeholder stubs or empty stubs"
        ],
        user_prompt="Build campus event board"
    )
    assert res.overall_verdict == "COMPLETE"
    assert len(res.requirements_missing) == 0
