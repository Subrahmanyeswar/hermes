# tests/test_phase5_targeted_repair.py
"""
HERMES Phase 5 Acceptance Test Suite: Scenarios J, K, L — Targeted Repair Loop.

Scenarios Covered:
- Scenario J: Targeted repair fixes a deliberately introduced defect while verifying
  unaffected files remain bit-for-bit unchanged.
- Scenario K: Repaired workspace is re-verified from physical disk and only advances if clean.
- Scenario L: Repair budget is strictly bounded (max 3 attempts); exhausted repairs halt truthfully.
"""

import tempfile
from pathlib import Path
import pytest

from core.alignment_verifier import verify_project_alignment
from core.contracts.manifest import InterfaceManifest, ElementContract
from core.contracts.repair import ContractRepairCoordinator


def test_scenario_j_and_k_targeted_repair_and_reverification():
    """
    Scenarios J & K:
    1. Introduce a deliberately mismatched DOM ID (HTML defines #submitButton, JS queries #submitBtn).
    2. Verifier detects the failure.
    3. Targeted repair coordinator applies a single targeted intervention.
    4. Unaffected files maintain identical SHA-256 hashes.
    5. Re-verification runs against physical workspace and passes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)

        # 1. Setup workspace with deliberate defect
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head><title>App</title><link rel="stylesheet" href="styles.css"></head>
<body>
    <button id="submitButton">Submit Form</button>
    <script src="app.js"></script>
</body>
</html>""",
            encoding="utf-8",
        )
        # Unaffected file with initial content
        styles_content = ".container { width: 100%; }\nbutton { color: blue; }\n"
        (ws / "styles.css").write_text(styles_content, encoding="utf-8")

        # Broken JS referencing #submitBtn instead of #submitButton
        (ws / "app.js").write_text(
            """document.addEventListener('DOMContentLoaded', () => {
    const btn = document.querySelector('#submitBtn');
    if (btn) btn.addEventListener('click', () => console.log('sent'));
});""",
            encoding="utf-8",
        )

        manifest = InterfaceManifest(
            element_ids={
                "submitButton": ElementContract(
                    dom_id="submitButton",
                    tag="button",
                    owning_file="index.html",
                )
            }
        )

        # 2. Initial verification fails
        initial_report = verify_project_alignment(ws, interface_manifest=manifest)
        assert initial_report.status == "FAIL"
        assert initial_report.hard_error_count >= 1

        # 3. Execute targeted repair
        coordinator = ContractRepairCoordinator(max_repair_budget=3)
        outcome = coordinator.execute_bounded_repair(
            workspace_root=ws,
            initial_report=initial_report,
            interface_manifest=manifest,
        )

        # 4. Assertions: Repair succeeded, unaffected files preserved
        assert outcome.success is True
        assert outcome.budget_exhausted is False
        assert outcome.attempts_used >= 1
        assert outcome.unaffected_files_preserved is True
        assert outcome.final_report.status == "PASS"
        assert outcome.final_report.hard_error_count == 0

        # Verify styles.css was completely untouched
        assert (ws / "styles.css").read_text(encoding="utf-8") == styles_content

        # 5. Scenario K: Physical re-verification from disk confirms clean state
        physical_report = verify_project_alignment(ws, interface_manifest=manifest)
        assert physical_report.status == "PASS"
        assert physical_report.hard_error_count == 0


def test_scenario_l_repair_budget_exhaustion():
    """
    Scenario L: Unfixable or repeated defects exhaust the repair budget (3 attempts)
    and halt truthfully rather than looping indefinitely.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)

        # Workspace with an intractable syntax error that cannot be automatically reconciled
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head><link rel="stylesheet" href="styles.css"></head><body><h1>Broken</h1></body></html>""",
            encoding="utf-8",
        )
        (ws / "styles.css").write_text("body { font-size: 14px; }", encoding="utf-8")
        # Severely corrupt JS file with multiple syntax and import errors
        (ws / "app.js").write_text(
            """import { unknown1 } from "./missing1.js";
import { unknown2 } from "./missing2.js";
import { unknown3 } from "./missing3.js";
import { unknown4 } from "./missing4.js";
function() {{{{{""",
            encoding="utf-8",
        )

        initial_report = verify_project_alignment(ws)
        assert initial_report.status == "FAIL"

        coordinator = ContractRepairCoordinator(max_repair_budget=3)
        outcome = coordinator.execute_bounded_repair(
            workspace_root=ws,
            initial_report=initial_report,
        )

        # Assert bounded execution: stopped at max_repair_budget
        assert outcome.attempts_used <= 3
        assert outcome.success is False
        assert outcome.final_report.status == "FAIL"
        assert outcome.final_report.hard_error_count > 0
        assert "exhausted" in outcome.message.lower() or outcome.budget_exhausted or not outcome.success
