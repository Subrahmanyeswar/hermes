# tests/test_phase5_contract_verification.py
"""
HERMES Phase 5 Acceptance Test Suite: Scenarios B through I — Physical Workspace Contract Verification.

Scenarios Covered:
- Scenario B: Required-file verification (missing planned blueprint file is detected).
- Scenario C: Broken selector detection (HTML id="submitButton" vs JS querySelector("#submitBtn")).
- Scenario D: Broken import detection (missing ES module import is detected).
- Scenario E: Cross-file consistency (individually valid files with incompatible linkages rejected).
- Scenario F: Asset reference integrity (unresolvable stylesheet or asset detected).
- Scenario G: Required controls (missing contract-specified forms/controls detected).
- Scenario H: Accessibility contract (unlabeled button/input detected under accessibility contract).
- Scenario I: Syntax verification (unbalanced CSS/JS or invalid Python syntax detected).
"""

import tempfile
from pathlib import Path
import pytest

from core.alignment_verifier import (
    verify_project_alignment,
    DefectKind,
    DefectSeverity,
)
from core.contracts.blueprint import ImplementationBlueprint, FilePlan
from core.contracts.manifest import InterfaceManifest, ElementContract, FormContract, AssetContract
from core.contracts.rubric import QualityRubric, RubricRequirement


def test_scenario_b_missing_required_file_detected():
    """
    Scenario B: Verifier detects when a contract-planned file is missing from physical workspace.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        # Create only index.html, omit styles.css and app.js
        (ws / "index.html").write_text("<!DOCTYPE html><html><body><h1>Hello</h1></body></html>", encoding="utf-8")

        bp = ImplementationBlueprint(
            mission_id="msn_b",
            planned_files=[
                FilePlan(path="index.html", purpose="Entrypoint"),
                FilePlan(path="styles.css", purpose="Styles"),
                FilePlan(path="app.js", purpose="Logic"),
            ]
        )

        report = verify_project_alignment(ws, blueprint=bp)
        assert report.status == "FAIL"
        assert report.hard_error_count >= 2

        missing_defects = [d for d in report.defects if d.kind == DefectKind.MISSING_PLANNED_FILE]
        assert len(missing_defects) == 2
        missing_paths = [d.target for d in missing_defects]
        assert "styles.css" in missing_paths
        assert "app.js" in missing_paths


def test_scenario_c_broken_selector_detection():
    """
    Scenario C: Verifier detects mismatch where HTML defines id="submitButton"
    but JavaScript queries querySelector("#submitBtn").
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head><title>Test</title><link rel="stylesheet" href="styles.css"></head>
<body>
    <button id="submitButton">Submit</button>
    <script src="app.js"></script>
</body>
</html>""",
            encoding="utf-8",
        )
        (ws / "styles.css").write_text("button { color: red; }", encoding="utf-8")
        # JS looks for #submitBtn which does NOT exist in HTML
        (ws / "app.js").write_text(
            """document.addEventListener('DOMContentLoaded', () => {
    const btn = document.querySelector('#submitBtn');
    if (btn) btn.addEventListener('click', () => console.log('clicked'));
});""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"

        dom_defects = [d for d in report.defects if d.kind == DefectKind.MISSING_DOM_ID]
        assert len(dom_defects) >= 1
        assert any(d.target == "submitBtn" for d in dom_defects)
        assert "submitBtn" in dom_defects[0].message


def test_scenario_d_broken_import_detection():
    """
    Scenario D: Verifier detects broken or missing ES module imports.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="styles.css"></head>
<body>
    <div id="content">Content</div>
    <script type="module" src="app.js"></script>
</body>
</html>""",
            encoding="utf-8",
        )
        (ws / "styles.css").write_text("body { margin: 0; }", encoding="utf-8")
        # app.js imports from a non-existent module
        (ws / "app.js").write_text(
            """import { computeTotal } from "./missing-calculator.js";
console.log(computeTotal(10));""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"

        import_defects = [d for d in report.defects if d.kind == DefectKind.UNRESOLVED_IMPORT]
        assert len(import_defects) >= 1
        assert any("./missing-calculator.js" in d.message for d in import_defects)


def test_scenario_e_cross_file_consistency():
    """
    Scenario E: Valid individual files with incompatible linkages are rejected.
    HTML has valid syntax, JS has valid syntax, but they disagree on element contract.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="styles.css"></head>
<body>
    <div id="userProfileCard">Profile</div>
    <script src="app.js"></script>
</body>
</html>""",
            encoding="utf-8",
        )
        (ws / "styles.css").write_text(".card { padding: 10px; }", encoding="utf-8")
        (ws / "app.js").write_text(
            """// Perfectly valid JS syntax
const card = document.getElementById("profileContainer");
card.style.display = "block";""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        assert any(d.kind == DefectKind.MISSING_DOM_ID and d.target == "profileContainer" for d in report.defects)


def test_scenario_f_asset_reference_integrity():
    """
    Scenario F: Verifier detects referenced media or stylesheets that do not exist on disk.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="missing-theme.css">
</head>
<body>
    <img src="images/missing-logo.png" alt="Logo">
</body>
</html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"

        broken_refs = [d for d in report.defects if d.kind == DefectKind.BROKEN_REFERENCE]
        assert len(broken_refs) >= 2
        ref_targets = [d.target for d in broken_refs]
        assert "missing-theme.css" in ref_targets
        assert "images/missing-logo.png" in ref_targets


def test_scenario_g_required_controls_and_forms():
    """
    Scenario G: Verifier detects missing contract-specified forms and required fields.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        # HTML has a form, but lacks the required 'category' field
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="styles.css"></head>
<body>
    <form id="eventForm">
        <input type="text" name="title" id="title" placeholder="Event title">
        <button type="submit" id="submitBtn">Create</button>
    </form>
    <script src="app.js"></script>
</body>
</html>""",
            encoding="utf-8",
        )
        (ws / "styles.css").write_text("form { display: block; }", encoding="utf-8")
        (ws / "app.js").write_text("console.log('loaded');", encoding="utf-8")

        manifest = InterfaceManifest(
            forms={
                "eventForm": FormContract(
                    form_id="eventForm",
                    owning_file="index.html",
                    fields=["title", "category"],  # 'category' is missing in HTML!
                ),
                "userSettingsForm": FormContract(
                    form_id="userSettingsForm",  # this form is completely missing in HTML!
                    owning_file="index.html",
                    fields=["theme"],
                )
            }
        )

        report = verify_project_alignment(ws, interface_manifest=manifest)
        assert report.status == "FAIL"

        missing_forms = [d for d in report.defects if d.kind == DefectKind.MISSING_REQUIRED_CONTROL]
        assert any(d.target == "userSettingsForm" for d in missing_forms)

        mismatched_fields = [d for d in report.defects if d.kind == DefectKind.FORM_FIELD_MISMATCH]
        assert any(d.target == "category" for d in mismatched_fields)


def test_scenario_h_accessibility_contract_verification():
    """
    Scenario H: Verifier flags interactive controls lacking accessible names/labels
    when accessibility requirements are mandated in the contract.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="styles.css"></head>
<body>
    <!-- Anonymous button with no text, aria-label, or title -->
    <button id="iconBtn"><svg></svg></button>
    <!-- Input without associated label or aria-label/placeholder -->
    <input type="text" id="unlabeledInput" name="data">
    <script src="app.js"></script>
</body>
</html>""",
            encoding="utf-8",
        )
        (ws / "styles.css").write_text("button { width: 30px; }", encoding="utf-8")
        (ws / "app.js").write_text("console.log('ready');", encoding="utf-8")

        # Rubric with explicit accessibility requirement
        rubric = QualityRubric(
            hard_requirements=[
                RubricRequirement(
                    req_id="REQ-A11Y",
                    title="Accessibility Requirements",
                    description="All buttons and inputs must satisfy accessibility label contracts",
                    rule_type="accessibility",
                    is_mandatory=True,
                )
            ]
        )

        report = verify_project_alignment(ws, quality_rubric=rubric)
        assert report.status == "FAIL"

        a11y_defects = [d for d in report.defects if d.kind == DefectKind.ACCESSIBILITY_VIOLATION]
        assert len(a11y_defects) >= 2


def test_scenario_i_syntax_verification():
    """
    Scenario I: Verifier detects malformed generated source code (unbalanced brackets/braces).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            "<!DOCTYPE html><html><head><link rel=\"stylesheet\" href=\"styles.css\"></head><body><script src=\"app.js\"></script></body></html>",
            encoding="utf-8",
        )
        # CSS with unbalanced braces
        (ws / "styles.css").write_text("body { margin: 0; div { padding: 5px; }", encoding="utf-8")
        # JS with unbalanced braces
        (ws / "app.js").write_text("function test() { if (true) { console.log('err'); }", encoding="utf-8")

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"

        syntax_defects = [d for d in report.defects if d.kind == DefectKind.SYNTAX_ERROR]
        assert len(syntax_defects) >= 2
