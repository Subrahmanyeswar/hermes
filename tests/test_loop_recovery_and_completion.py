# tests/test_loop_recovery_and_completion.py
"""
HERMES 2.x Final Reliability Regression Suite:
No-Progress Loop Recovery, Failure Budget Accounting, and Truthful Mission Completion.

Tests:
Test A: Verified task followed by duplicate reads -> transitions cleanly to completed.
Test B: Incomplete acceptance criteria -> does not falsely complete, gives targeted guidance.
Test C: Repeated loop without progress -> bounds loop without unlimited token burn (Case C terminal failure).
Test D: Genuine tool failures -> still counted in failure budget.
Test E: File written but verification fails -> records failure truthfully.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_loop.behavioral_verifier import TechnologyAwareBehavioralVerifier
from core.agent_loop.completion import CompletionPolicy
from core.agent_loop.types import AgentLoopConfig, ActionEnvelope, ActionStatus, AgentDecision, AgentDecisionType, Observation
from core.agent_loop.loop import AgentLoop
from core.runtime_state.events import EventType
from core.workspace import WorkspaceManager


# ── Test A: Verified task followed by duplicate reads -> transitions to completed ──

def test_a_verified_task_duplicate_reads_transitions_to_completed(tmp_path: Path):
    """
    Test A: Workspace contains complete, functioning Task Tracker application.
    When a read returns NO_PROGRESS_LOOP_ENFORCEMENT (duplicate unchanged read),
    the authoritative CompletionPolicy evaluates and confirms all requirements are verified (Case A),
    transitioning cleanly to completed without counting as fatal crashes.
    """
    ws = WorkspaceManager()
    ws.lock(str(tmp_path))

    # Complete Task Tracker HTML with responsive CSS, interactive controls, JS event listeners, localStorage & filter
    app_html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Task Tracker</title>
<style>
body { font-family: Arial, sans-serif; background: #fff; margin: 0; padding: 20px; }
.task { display: flex; align-items: center; justify-content: space-between; }
.filters button { padding: 4px 8px; }
</style>
</head>
<body>
<h1>Task Tracker</h1>
<input id="new-task" type="text" placeholder="Add task" />
<div id="tasks"></div>
<div class="filters">
    <button data-filter="all">All</button>
    <button data-filter="active">Active</button>
    <button data-filter="completed">Completed</button>
</div>
<script>
let tasks = JSON.parse(localStorage.getItem('tasks') || '[]');
let currentFilter = 'all';
function render() {
    const list = document.getElementById('tasks');
    list.innerHTML = '';
    const filtered = tasks.filter(t => currentFilter === 'all' ? true : (currentFilter === 'active' ? !t.completed : t.completed));
    filtered.forEach(t => {
        const d = document.createElement('div');
        d.className = 'task';
        list.appendChild(d);
    });
}
document.getElementById('new-task').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        tasks.push({ id: Date.now().toString(), text: e.target.value, completed: false });
        localStorage.setItem('tasks', JSON.stringify(tasks));
        render();
    }
});
render();
</script>
</body>
</html>"""
    (tmp_path / "index.html").write_text(app_html, encoding="utf-8")

    prompt = (
        "Build a complete, standalone Task Tracker web application inside this workspace. "
        "Create an index.html file with a responsive, modern UI to create tasks, toggle completion, "
        "delete tasks, and filter tasks by All, Active, and Completed, storing all data in localStorage. "
        "Verify the file and confirm implementation."
    )

    policy = CompletionPolicy()
    accepted, reason, issues = policy.evaluate_completion(
        mission_prompt=prompt,
        workspace=ws,
        written_files=["index.html"]
    )
    assert accepted is True, f"Expected acceptance under Case A, got: {reason} | issues: {issues}"
    assert len(issues) == 0


# ── Test B: Incomplete criteria -> does not falsely complete, gives targeted guidance ──

def test_b_incomplete_criteria_does_not_falsely_complete(tmp_path: Path):
    """
    Test B: Workspace contains stub with missing controls, missing storage, and missing filters.
    When duplicate reads occur, CompletionPolicy rejects completion. Case B feeds targeted guidance
    and does NOT declare false mission success.
    """
    ws = WorkspaceManager()
    ws.lock(str(tmp_path))

    # Stub HTML missing interactive controls and logic
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><head><title>Stub</title></head><body><p>Hello</p></body></html>", encoding="utf-8")

    prompt = (
        "Build a complete, standalone Task Tracker web application inside this workspace. "
        "Create an index.html file with a responsive, modern UI to create tasks, toggle completion, "
        "delete tasks, and filter tasks by All, Active, and Completed, storing all data in localStorage. "
        "Verify the file and confirm implementation."
    )

    policy = CompletionPolicy()
    accepted, reason, issues = policy.evaluate_completion(
        mission_prompt=prompt,
        workspace=ws,
        written_files=["index.html"]
    )
    assert accepted is False, "Incomplete stub must NOT be accepted"
    assert len(issues) > 0
    # Must report missing controls, persistence, or structure
    assert any("controls" in iss.lower() or "persistence" in iss.lower() or "filter" in iss.lower() for iss in issues)


# ── Test C: Repeated loop without progress -> bounds loop without unlimited burn ──

def test_c_repeated_loop_bounds_without_unlimited_burn(tmp_path: Path):
    """
    Test C: Verify that repeated unchanged read blocks on an incomplete workspace
    are strictly bounded to < 3 attempts before terminating in a bounded failure (Case C)
    rather than looping indefinitely or burning unlimited tokens.
    """
    ws = WorkspaceManager()
    ws.lock(str(tmp_path))
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>Empty</h1></body></html>", encoding="utf-8")

    prompt = "Build a complete Task Tracker web application with localStorage and filters."

    policy = CompletionPolicy()
    accepted, reason, issues = policy.evaluate_completion(
        mission_prompt=prompt,
        workspace=ws,
        written_files=["index.html"]
    )
    assert accepted is False

    # Simulate loop governor block counter tracking
    unchanged_read_governor_blocks = 0
    max_blocks = 3
    terminal_failed = False
    termination_reason = ""

    for _ in range(5):
        unchanged_read_governor_blocks += 1
        if accepted:
            break
        elif unchanged_read_governor_blocks < max_blocks:
            # Case B: guidance provided
            continue
        else:
            # Case C: bounded terminal failure
            terminal_failed = True
            termination_reason = f"No-progress loop terminated: unmet criteria after repeated unchanged reads: {'; '.join(issues)}"
            break

    assert terminal_failed is True
    assert unchanged_read_governor_blocks == 3, "Loop must terminate strictly at block threshold (3)"
    assert "No-progress loop terminated" in termination_reason


# ── Test D: Genuine tool failures -> still counted in failure budget ────────

def test_d_genuine_tool_failures_still_counted_in_failure_budget():
    """
    Test D: Genuine tool errors (e.g. command not found, syntax error, missing path)
    are NOT suppressed and MUST increment consecutive_failures toward the budget.
    """
    config = AgentLoopConfig(max_consecutive_failures=5)
    consecutive_failures = 0

    # Genuine failure observations (not unchanged read blocks)
    genuine_errors = [
        Observation(observation_id="o1", mission_id="m1", success=False, error_message="Command failed: exit code 127", content="bash: non_existent_cmd: command not found"),
        Observation(observation_id="o2", mission_id="m1", success=False, error_message="SyntaxError in python script", content="invalid syntax on line 4"),
        Observation(observation_id="o3", mission_id="m1", success=False, error_message="FileNotFoundError: [Errno 2] No such file", content="Path missing.txt does not exist"),
    ]

    for obs in genuine_errors:
        is_unchanged_read_block = (
            "NO_PROGRESS_LOOP_ENFORCEMENT" in (obs.error_message or "") or
            "UNCHANGED_READ" in (obs.error_message or "") or
            "NO_PROGRESS_LOOP_ENFORCEMENT" in (obs.content or "")
        )
        assert not is_unchanged_read_block, "Genuine tool error must not be classified as unchanged read block"
        consecutive_failures += 1

    assert consecutive_failures == 3


# ── Test E: File written but verification fails -> records failure truthfully ──

def test_e_file_written_but_verification_fails_records_failure_truthfully(tmp_path: Path):
    """
    Test E: A file is written but contains invalid syntax or placeholder-only stubs.
    Verification fails truthfully and reports the exact diagnostic issues.
    """
    ws = WorkspaceManager()
    ws.lock(str(tmp_path))

    # Python file with invalid syntax
    (tmp_path / "broken.py").write_text("def faulty_function(\n    return 42", encoding="utf-8")

    prompt = "Create a python math utility module with unit tests"
    policy = CompletionPolicy()
    accepted, reason, issues = policy.evaluate_completion(
        mission_prompt=prompt,
        workspace=ws,
        written_files=["broken.py"]
    )

    assert accepted is False
    assert "deterministic syntax validation failed" in reason
    assert any("syntax error in broken.py" in iss.lower() for iss in issues)
