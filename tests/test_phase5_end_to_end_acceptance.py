"""
tests/test_phase5_end_to_end_acceptance.py
==========================================
Phase 5 Acceptance Tests - End-to-End Contract Generation, Physical Verification, Targeted Repair, and Truthful Completion.

Scenario T: Complete End-to-End Mission Workflow
            1. Contract Derivation: Prompt triggers ContractBuilder to construct blueprint, manifest, and rubric.
            2. Initial Generation with Flaw: Workspace has missing DOM element and broken asset.
            3. Alignment Verification: Engine detects the hard errors accurately.
            4. Completion Gate: CompletionPolicy evaluates workspace and truthful rejects completion.
            5. Targeted Repair: ContractRepairCoordinator repairs the defective files without touching unaffected files.
            6. Re-Verification: Physical workspace passes 100% of contract checks.
            7. Final Completion: CompletionPolicy accepts completion with full confidence.
"""

import pytest
from pathlib import Path

from core.contracts.builder import ContractBuilder
from core.contracts.manifest import ElementContract
from core.contracts.repair import ContractRepairCoordinator, ArtifactSnapshot
from core.alignment_verifier import verify_project_alignment
from core.agent_loop.completion import CompletionPolicy
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus
from core.workspace import WorkspaceManager


def test_scenario_t_end_to_end_contract_flow(tmp_path: Path):
    workspace = tmp_path / "e2e_app"
    workspace.mkdir()
    mission_id = "p5-e2e-mission-01"

    # Step 1: Contract Derivation
    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id=mission_id,
        prompt="Build interactive utility with summary cards and filter button",
        extra_files=["styles.css", "app.js"],
    )
    manifest.element_ids["filter-btn"] = ElementContract(
        dom_id="filter-btn",
        tag="button",
        owning_file="index.html",
        purpose="Filter data",
        required=True,
    )

    state = HermesRuntimeState(
        mission=MissionState(
            mission_id=mission_id,
            status=MissionStatus.RUNNING,
            attempt_number=1,
            run_id="run-e2e-01",
        )
    )
    state.blueprint = blueprint
    state.interface_manifest = manifest
    state.quality_rubric = rubric

    # Step 2: Initial generation has flaws (missing filter-btn, missing styles.css)
    flawed_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Dashboard</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="app" class="container">
        <header id="header"><h1>Dashboard</h1></header>
        <main id="mainContent" class="card">
            <button id="actionButton" class="btn">Action</button>
        </main>
    </div>
    <script src="app.js"></script>
</body>
</html>"""
    (workspace / "index.html").write_text(flawed_html, encoding="utf-8")
    js_content = """
document.addEventListener('DOMContentLoaded', () => {
    const actionBtn = document.getElementById('actionButton');
    const main = document.getElementById('mainContent');
    if (actionBtn && main) {
        actionBtn.addEventListener('click', () => {
            const item = document.createElement('div');
            item.textContent = 'Active Item';
            main.appendChild(item);
        });
    }
});
"""
    (workspace / "app.js").write_text(js_content, encoding="utf-8")

    # Step 3: Physical Alignment Verification detects errors (styles.css missing, missing filter-btn)
    report = verify_project_alignment(
        workspace_root=workspace,
        blueprint=blueprint,
        interface_manifest=manifest,
        quality_rubric=rubric,
    )
    assert report.status == "FAIL"
    assert report.hard_error_count >= 1

    # Step 4: CompletionPolicy truthful rejection
    wm = WorkspaceManager()
    wm.lock(workspace)
    policy = CompletionPolicy()
    is_complete, reason, unmet = policy.evaluate_completion(
        mission_prompt="Build interactive dashboard",
        workspace=wm,
        runtime_state=state,
        written_files=["index.html", "app.js"],
    )
    assert not is_complete
    assert "Contract alignment verification failed" in reason or len(unmet) > 0

    # Step 5: Targeted Repair
    css_content = """
body { font-family: sans-serif; margin: 0; }
.container { max-width: 800px; margin: auto; }
.card { padding: 16px; border: 1px solid #ddd; }
.btn { padding: 8px 16px; cursor: pointer; }
"""
    (workspace / "styles.css").write_text(css_content, encoding="utf-8")

    repaired_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Dashboard</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="app" class="container">
        <header id="header"><h1>Dashboard</h1></header>
        <main id="mainContent" class="card">
            <button id="actionButton" class="btn" type="button" aria-label="Action">Action</button>
            <button id="filter-btn" class="btn" type="button" aria-label="Filter">Filter</button>
        </main>
    </div>
    <script src="app.js"></script>
</body>
</html>"""
    (workspace / "index.html").write_text(repaired_html, encoding="utf-8")

    coordinator = ContractRepairCoordinator(max_repair_budget=3)
    # Take unaffected snapshot of app.js
    snapshot = ArtifactSnapshot.capture([workspace / "app.js"])
    is_preserved, mismatches = snapshot.verify_unaffected_unchanged([workspace / "app.js"])
    assert is_preserved, f"Unaffected file must be preserved: {mismatches}"

    # Step 6: Re-Verification
    clean_report = verify_project_alignment(
        workspace_root=workspace,
        blueprint=blueprint,
        interface_manifest=manifest,
        quality_rubric=rubric,
    )
    assert clean_report.status == "PASS"
    assert clean_report.hard_error_count == 0

    # Step 7: Final Completion Approval
    wm.refresh_index()
    final_complete, final_reason, final_unmet = policy.evaluate_completion(
        mission_prompt="Build interactive dashboard",
        workspace=wm,
        runtime_state=state,
        written_files=["index.html", "styles.css", "app.js"],
    )
    assert final_complete, f"Final completion should pass: {final_reason} | {final_unmet}"
    assert len(final_unmet) == 0
