"""
tests/test_phase5_line_count_policy.py
======================================
Phase 5 Acceptance-Gap Tests: Line-Count Policy Verification.

Verifies:
1. A correct, minimal implementation is NOT rejected merely for having fewer lines
   than an arbitrary baseline or metadata recommendation.
2. An implementation with excessive lines is NOT accepted merely because it meets
   or exceeds a line-count threshold if structural or semantic defects exist.
3. A genuinely missing required element or broken reference STILL prevents completion,
   regardless of line count.
4. Contract serialization, persistence, and state reconstruction preserve blueprint
   and rubric min_lines metadata as informational values without converting them into
   hard completion blockers.
"""

import pytest
from pathlib import Path

from core.contracts.builder import ContractBuilder
from core.contracts.manifest import ElementContract
from core.alignment_verifier import verify_project_alignment
from core.agent_loop.completion import CompletionPolicy
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus
from core.workspace import WorkspaceManager
from core.persistence.serializer import serialize_runtime_state, deserialize_runtime_state


def test_compact_correct_implementation_passes(tmp_path: Path):
    """
    Case 1: A correct, minimal implementation (e.g. 10 lines of HTML, 8 lines of CSS,
    12 lines of JS) that satisfies all functional contracts must PASS alignment verification
    and completion evaluation, despite planned_files min_lines metadata suggesting 15-20 lines.
    """
    workspace = tmp_path / "compact_app"
    workspace.mkdir()

    # Highly compact HTML (10 lines)
    html_content = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Compact App</title><link rel="stylesheet" href="styles.css"></head>
<body>
<div id="app" class="container">
<header id="header"><h1>Compact App</h1></header>
<main id="mainContent" class="card"><button id="actionButton" class="btn" type="button" aria-label="Action">Click</button></main>
</div>
<script src="app.js"></script>
</body></html>"""
    (workspace / "index.html").write_text(html_content, encoding="utf-8")

    # Compact CSS (5 lines)
    css_content = """.container { margin: 0 auto; }
.card { padding: 10px; }
.btn { cursor: pointer; }"""
    (workspace / "styles.css").write_text(css_content, encoding="utf-8")

    # Compact JS with real interactive DOM rendering (10 lines)
    js_content = """document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('actionButton');
    const main = document.getElementById('mainContent');
    if (btn && main) {
        btn.addEventListener('click', () => {
            const item = document.createElement('div');
            item.textContent = 'Active Item';
            main.appendChild(item);
        });
    }
});"""
    (workspace / "app.js").write_text(js_content, encoding="utf-8")

    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id="p5-compact-test",
        prompt="Create a compact interactive utility with summary cards",
        extra_files=["styles.css", "app.js"],
    )

    # Note: blueprint.planned_files specify min_lines=15, 15, 20
    # Our files are significantly shorter (e.g. 3 lines CSS, 10 lines JS).
    report = verify_project_alignment(
        workspace_root=workspace,
        blueprint=blueprint,
        interface_manifest=manifest,
        quality_rubric=rubric,
    )
    assert report.status == "PASS", f"Compact valid app must pass alignment verifier, but failed: {[d.message for d in report.defects]}"
    assert report.hard_error_count == 0

    state = HermesRuntimeState(
        mission=MissionState(
            mission_id="p5-compact-test",
            status=MissionStatus.RUNNING,
            attempt_number=1,
            run_id="run-compact-01",
        )
    )
    state.blueprint = blueprint
    state.interface_manifest = manifest
    state.quality_rubric = rubric

    wm = WorkspaceManager()
    wm.lock(workspace)

    policy = CompletionPolicy()
    is_complete, reason, unmet = policy.evaluate_completion(
        mission_prompt="Create a compact interactive utility with summary cards",
        workspace=wm,
        runtime_state=state,
        written_files=["index.html", "styles.css", "app.js"],
    )

    assert is_complete, f"CompletionPolicy must accept compact valid app: {reason} | {unmet}"
    assert len(unmet) == 0


def test_long_broken_implementation_fails(tmp_path: Path):
    """
    Case 2: An implementation that exceeds line count targets (e.g. 150 lines of bloated
    HTML and CSS) but has a broken CSS link and missing DOM element MUST be rejected.
    Line count cannot buy a pass.
    """
    workspace = tmp_path / "bloated_broken_app"
    workspace.mkdir()

    # Generate 120 lines of HTML, but referencing a nonexistent stylesheet and missing required elements
    lines = ["<!DOCTYPE html>", "<html>", "<head>", '<link rel="stylesheet" href="nonexistent.css">', "</head>", "<body>"]
    for i in range(110):
        lines.append(f"  <p id='para_{i}'>Bloat text line {i}</p>")
    lines.extend(["</body>", "</html>"])
    (workspace / "index.html").write_text("\n".join(lines), encoding="utf-8")

    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id="p5-bloated-test",
        prompt="Create web app",
        extra_files=["styles.css", "app.js"],
    )

    report = verify_project_alignment(
        workspace_root=workspace,
        blueprint=blueprint,
        interface_manifest=manifest,
        quality_rubric=rubric,
    )

    assert report.status == "FAIL"
    assert report.hard_error_count > 0
    assert any("nonexistent.css" in d.message for d in report.defects)

    state = HermesRuntimeState(
        mission=MissionState(
            mission_id="p5-bloated-test",
            status=MissionStatus.RUNNING,
        )
    )
    state.blueprint = blueprint
    state.interface_manifest = manifest
    state.quality_rubric = rubric

    wm = WorkspaceManager()
    wm.lock(workspace)
    policy = CompletionPolicy()
    is_complete, reason, unmet = policy.evaluate_completion(
        mission_prompt="Create web app",
        workspace=wm,
        runtime_state=state,
        written_files=["index.html"],
    )
    assert not is_complete, "Bloated broken implementation must NOT be approved"


def test_serialization_preserves_min_lines_as_informational(tmp_path: Path):
    """
    Case 4: Contract serialization and deserialization preserves min_lines
    in FilePlan without any data corruption or conversion into hard enforcement gates.
    """
    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id="p5-ser-lines-test",
        prompt="Build app",
        extra_files=["styles.css"],
    )

    state = HermesRuntimeState(
        mission=MissionState(
            mission_id="p5-ser-lines-test",
            status=MissionStatus.RUNNING,
        )
    )
    state.blueprint = blueprint
    state.interface_manifest = manifest
    state.quality_rubric = rubric

    serialized_dict, state_hash = serialize_runtime_state(state)
    restored = deserialize_runtime_state(serialized_dict)

    # Check that planned_files retain min_lines metadata
    html_plan = next(f for f in restored.blueprint.planned_files if f.path == "index.html")
    assert html_plan.min_lines == 15
    assert restored.blueprint.mission_id == "p5-ser-lines-test"
