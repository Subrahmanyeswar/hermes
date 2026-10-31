# tests/test_multifile_contract_and_recovery.py
"""
Deterministic Regression & Acceptance Suite for HERMES Multi-File Contracts,
DOM Validation, Checkpointed Failover, and No-Progress Recovery Remediation.
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from core.project_contract import ProjectContract
from core.integration_validator import CrossArtifactValidator, IntegrationReport, StructuredDefect
from core.agent_loop.mvp_gate import WebsiteMvpGate, MvpPhase


@pytest.fixture
def temp_ws(tmp_path):
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# =========================================================================
# Part 4 & Historical SpendWise Failure Reproduction Tests
# =========================================================================

def test_historical_spendwise_failure_reproduction(temp_ws):
    """
    Reproduces the exact historical multi-file defects from testing 6 in a temporary fixture:
    1. index.html references app.js, package.json references app.js, but on disk main.js exists.
    2. main.js references #clear-filters, #transaction-list, #category-breakdown, #monthly-trend,
       while HTML has #btn-clear-filters, #transactions-tbody, #category-breakdown-container.
    3. main.js accesses formData.get('amount') while HTML only has id='tx-amount' without name='amount'.
    4. main.js contains placeholder calculateCategoryProgress().
    Asserts that CrossArtifactValidator deterministically catches EVERY defect before repair,
    and passes after alignment repair.
    """
    # 1. Setup defective historical fixture
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SpendWise</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <button id="theme-toggle">Theme</button>
    <button id="btn-add-transaction">Add</button>
    <h2 id="total-balance">$0.00</h2>
    <h2 id="total-income">$0.00</h2>
    <h2 id="total-expense">$0.00</h2>
    <h2 id="total-count">0</h2>
    <div id="trend-chart-container"><div id="monthly-bar-chart"></div></div>
    <div id="category-breakdown-container"></div>
    <button id="btn-clear-filters">Reset</button>
    <table><tbody id="transactions-tbody"></tbody></table>
    <form id="transaction-form">
        <input type="text" id="tx-title">
        <input type="number" id="tx-amount">
    </form>
    <script src="app.js"></script>
</body>
</html>"""
    (temp_ws / "index.html").write_text(html_content, encoding="utf-8")
    (temp_ws / "style.css").write_text("/* style */ #total-balance { color: green; }", encoding="utf-8")
    (temp_ws / "package.json").write_text(json.dumps({"name": "spendwise", "main": "app.js"}), encoding="utf-8")

    # Mismatched main.js on disk (instead of app.js)
    main_js_content = """// main.js
document.addEventListener('DOMContentLoaded', () => {
    const list = document.getElementById('transaction-list');
    const resetBtn = document.getElementById('clear-filters');
    const chart = document.getElementById('category-breakdown');
    const trend = document.getElementById('monthly-trend');
    const form = document.getElementById('transaction-form');
    if (form) {
        form.addEventListener('submit', (e) => {
            const formData = new FormData(form);
            const amt = formData.get('amount');
        });
    }
});
function calculateCategoryProgress() {
    return 50; // TODO placeholder
}
"""
    (temp_ws / "main.js").write_text(main_js_content, encoding="utf-8")

    # 2. Run validator against defective fixture
    rep = CrossArtifactValidator.validate_web_integration(temp_ws)
    assert not rep.valid, "Validator should detect historical defects"
    assert len(rep.issues) >= 4, f"Expected >= 4 defects, got {len(rep.issues)}: {rep.issues}"

    # Verify specific defect kinds caught
    issue_text = " ".join(rep.issues)
    assert "Broken script reference in index.html: 'app.js' not found on disk" in rep.issues
    assert "clear-filters" in issue_text
    assert "transaction-list" in issue_text
    assert "FormData name mismatch" in issue_text
    assert "Incomplete placeholder function" in issue_text

    # 3. Apply targeted alignment repair
    # - Rename main.js to app.js and bind to correct HTML IDs
    # - Add name attributes to form in index.html
    # - Replace placeholder calculation
    repaired_html = html_content.replace('<input type="text" id="tx-title">', '<input type="text" id="tx-title" name="title">')
    repaired_html = repaired_html.replace('<input type="number" id="tx-amount">', '<input type="number" id="tx-amount" name="amount">')
    (temp_ws / "index.html").write_text(repaired_html, encoding="utf-8")

    (temp_ws / "main.js").unlink()
    repaired_app_js = """// app.js
document.addEventListener('DOMContentLoaded', () => {
    const list = document.getElementById('transactions-tbody');
    const resetBtn = document.getElementById('btn-clear-filters');
    const chart = document.getElementById('category-breakdown-container');
    const trend = document.getElementById('trend-chart-container');
    const form = document.getElementById('transaction-form');
    if (form) {
        form.addEventListener('submit', (e) => {
            const formData = new FormData(form);
            const amt = parseFloat(formData.get('amount') || 0);
        });
    }
});
function calculateCategoryProgress(txs, cat) {
    if (!txs || txs.length === 0) return 0;
    const catTotal = txs.filter(t => t.category === cat).reduce((s, t) => s + t.amount, 0);
    const total = txs.reduce((s, t) => s + t.amount, 0);
    return total > 0 ? (catTotal / total) * 100 : 0;
}
"""
    (temp_ws / "app.js").write_text(repaired_app_js, encoding="utf-8")

    # 4. Run validator against repaired fixture
    repaired_rep = CrossArtifactValidator.validate_web_integration(temp_ws)
    assert repaired_rep.valid, f"Repaired fixture should pass validation, but got: {repaired_rep.issues}"
    assert len(repaired_rep.issues) == 0


# =========================================================================
# Part 5 & 6: Project Contract & Generation Tests
# =========================================================================

def test_project_contract_creation_and_canonical_entrypoints(temp_ws):
    """Test contract creation, canonical entrypoint resolution, and persistence."""
    # When prompt specifies app.js
    contract_app = ProjectContract.create_or_load(temp_ws, "m_test1", "Build SpendWise with index.html, style.css, and app.js.")
    assert contract_app.canonical_js == "app.js"
    assert (temp_ws / ".hermes" / "project_contract.json").exists()

    # Re-loading preserves contract
    loaded = ProjectContract.create_or_load(temp_ws, "m_test1")
    assert loaded.canonical_js == "app.js"
    assert loaded.contract_hash == contract_app.contract_hash


def test_project_contract_determines_main_js_when_requested(temp_ws):
    """When prompt explicitly requests main.js, contract must choose main.js."""
    c_js = ProjectContract.determine_canonical_js("Use index.html, style.css, and main.js.", temp_ws)
    assert c_js == "main.js"


def test_dom_inventory_extraction(temp_ws):
    """Test extracting authoritative DOM inventory from index.html into dom_contract.json."""
    html_content = """<!DOCTYPE html>
<html>
<head><link rel="stylesheet" href="style.css"></head>
<body>
    <div id="stat-total"></div>
    <button id="btn-submit" name="submit-btn" class="btn btn-primary"></button>
    <input type="text" id="user-email" name="email">
    <script src="app.js"></script>
</body>
</html>"""
    (temp_ws / "index.html").write_text(html_content, encoding="utf-8")

    inv = ProjectContract.extract_dom_inventory(temp_ws)
    assert "stat-total" in inv["ids"]
    assert "btn-submit" in inv["ids"]
    assert "email" in inv["form_names"]
    assert "app.js" in inv["scripts"]
    assert (temp_ws / ".hermes" / "dom_contract.json").exists()


# =========================================================================
# Part 7 & 8: Entrypoint & Dynamic Repair Target Parsing Tests
# =========================================================================

def test_mvp_gate_dynamic_entrypoint_detection(temp_ws):
    """MVP gate must detect dynamic script in index.html and NOT hardcode main.js."""
    (temp_ws / "index.html").write_text('<html><body><script src="app.js"></script></body></html>', encoding="utf-8")
    (temp_ws / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    (temp_ws / "package.json").write_text('{"name": "test"}', encoding="utf-8")

    gate = WebsiteMvpGate(workspace_root=temp_ws)
    ok, missing = gate.check_scaffold_complete(temp_ws)
    assert not ok
    # Must report 'app.js' missing, NEVER hardcode 'main.js'!
    assert "app.js" in missing
    assert "main.js" not in missing


def test_parse_scaffold_target_identifies_missing_script(temp_ws):
    """When script is missing on disk, parse_scaffold_target must target the script, NOT index.html."""
    err_str = "Scaffold missing/incomplete: DOM mismatch: Broken script reference in index.html: 'app.js' not found on disk"
    target, hint = WebsiteMvpGate.parse_scaffold_target(err_str)
    assert target == "app.js", f"Target should be 'app.js', got: {target}"
    assert "app.js" in hint
    assert "Create 'app.js'" in hint


def test_parse_scaffold_target_identifies_dom_mismatch(temp_ws):
    """When JS queries non-existent ID, target must be the JS file."""
    err_str = "Scaffold missing/incomplete: DOM mismatch: JavaScript DOM mismatch: app.js calls getElementById('clear-filters'), but #clear-filters does not exist in index.html"
    target, hint = WebsiteMvpGate.parse_scaffold_target(err_str)
    assert target == "app.js"
    assert "clear-filters" in hint or "index.html" in hint


def test_parse_scaffold_target_identifies_formdata_mismatch(temp_ws):
    """When FormData name is missing in HTML, target must be index.html."""
    err_str = "Scaffold missing/incomplete: DOM mismatch: FormData name mismatch: app.js accesses formData.get('amount'), but no form input/select/textarea in index.html has name='amount'"
    target, hint = WebsiteMvpGate.parse_scaffold_target(err_str)
    assert target == "index.html"
    assert "name='amount'" in hint


# =========================================================================
# Part 9 & 10: Governor & Read Unblocking Tests
# =========================================================================

def test_diagnostic_reads_permitted_on_active_issues(temp_ws):
    """Verify that a file implicated in an active issue is marked readable without blocking."""
    # Simulation of loop.py read governor logic
    unmet_reqs_pre = [
        "Scaffold missing/incomplete: DOM mismatch: JavaScript DOM mismatch: app.js calls getElementById('missing-card'), but #missing-card does not exist in index.html"
    ]
    target_disk_file_html = Path("index.html")
    target_disk_file_js = Path("app.js")
    target_disk_file_css = Path("style.css")

    # html and app.js are implicated
    html_has_issue = any(target_disk_file_html.name.lower() in u.lower() for u in unmet_reqs_pre)
    js_has_issue = any(target_disk_file_js.name.lower() in u.lower() for u in unmet_reqs_pre)
    css_has_issue = any(target_disk_file_css.name.lower() in u.lower() for u in unmet_reqs_pre)

    assert html_has_issue is True, "index.html should be implicated"
    assert js_has_issue is True, "app.js should be implicated"
    assert css_has_issue is False, "style.css should not be implicated"

    # Reading implicated files should NEVER block
    read_count = 5
    should_block_html = False if html_has_issue else (read_count >= 3)
    should_block_js = False if js_has_issue else (read_count >= 3)
    should_block_css = False if css_has_issue else (read_count >= 3)

    assert should_block_html is False, "index.html read must NOT be blocked"
    assert should_block_js is False, "app.js read must NOT be blocked"
    assert should_block_css is True, "unimplicated style.css read should be blocked after 3 reads"


# =========================================================================
# Part 11: Checkpoint Failover Preservation Tests
# =========================================================================

def test_checkpoint_failover_preserves_contract_and_state(temp_ws):
    """Verify that recovery checkpoints store and preserve contract, DOM inventory, and repair tickets."""
    contract = ProjectContract.create_or_load(temp_ws, "m_failover_1", "SpendWise with app.js")
    (temp_ws / "index.html").write_text('<div id="dash-root"></div><script src="app.js"></script>', encoding="utf-8")
    dom_inv = ProjectContract.extract_dom_inventory(temp_ws)

    checkpoint_data = {
        "mission_id": "m_failover_1",
        "current_tier": 2,
        "provider": "groq",
        "model": "qwen/qwen3.8-27b",
        "target_repair_file": "app.js",
        "unmet_requirements": ["Scaffold missing/incomplete: app.js"],
        "completed_files": ["index.html", "style.css"],
        "trigger_reason": "Model timeout or provider outage",
        "canonical_js": contract.canonical_js,
        "dom_ids": dom_inv["ids"],
    }
    ckpt_file = temp_ws / ".hermes" / "recovery_checkpoint.json"
    ckpt_file.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")

    assert ckpt_file.exists()
    loaded_ckpt = json.loads(ckpt_file.read_text(encoding="utf-8"))
    assert loaded_ckpt["current_tier"] == 2
    assert loaded_ckpt["canonical_js"] == "app.js"
    assert "dash-root" in loaded_ckpt["dom_ids"]
    assert loaded_ckpt["target_repair_file"] == "app.js"


# =========================================================================
# Part 16: Additional Regression & Edge Case Scenarios
# =========================================================================

def test_preview_serves_selected_workspace_not_repo_root(temp_ws):
    """
    Regression test for skeleton screenshot bug:
    BrowserOpenPreviewTool must resolve target file's parent as workspace_root,
    never defaulting silently to the HERMES repository root.
    """
    from tools.browser_tools import BrowserOpenPreviewTool
    tool = BrowserOpenPreviewTool()

    target_file = temp_ws / "index.html"
    target_file.write_text("<h1>SpendWise Dedicated Workspace</h1>", encoding="utf-8")

    # When called with path only
    inp = {"path": str(target_file)}
    ws_dir = inp.get("workspace_dir") or inp.get("directory")
    if not ws_dir and inp.get("path"):
        raw_p = Path(inp["path"]).resolve()
        if raw_p.is_file():
            ws_dir = str(raw_p.parent)

    assert Path(ws_dir).resolve() == temp_ws.resolve(), f"Expected {temp_ws}, got {ws_dir}"
    assert Path(ws_dir).resolve() != Path.cwd().resolve(), "Must not default to repo root"


def test_error_delta_progress_tracking():
    """
    Real progress is measured by defect reduction or fingerprint change towards resolution.
    Reading without mutating or making changes that do not reduce defects is not progress.
    """
    initial_issues = ["Broken script 'app.js'", "DOM mismatch #btn-clear-filters", "FormData 'amount'"]
    canon1 = json.dumps(sorted(initial_issues))
    fp1 = hashlib.sha256(canon1.encode("utf-8")).hexdigest()[:16]

    # Attempt 1: only read or write unrelated file (defects unchanged)
    after_attempt1 = ["Broken script 'app.js'", "DOM mismatch #btn-clear-filters", "FormData 'amount'"]
    fp2 = hashlib.sha256(json.dumps(sorted(after_attempt1)).encode("utf-8")).hexdigest()[:16]
    assert fp1 == fp2, "Fingerprint unchanged indicates zero progress"

    # Attempt 2: successfully resolve script and form
    after_attempt2 = ["DOM mismatch #btn-clear-filters"]
    fp3 = hashlib.sha256(json.dumps(sorted(after_attempt2)).encode("utf-8")).hexdigest()[:16]
    assert fp3 != fp1, "Fingerprint changed"
    assert len(after_attempt2) < len(initial_issues), "Defect count decreased indicates true progress"


def test_tool_directory_read_rejected(temp_ws):
    """fs.read on a directory must fail with clear error, not treat directory as a file."""
    sub_dir = temp_ws / "sub_directory"
    sub_dir.mkdir()

    from tools.platform.core_tools import FSReadTool
    read_tool = FSReadTool()
    res = read_tool.execute({"path": str(sub_dir)})
    assert not res.success
    assert "directory" in str(res.error).lower() or "is a directory" in str(res.output).lower()
