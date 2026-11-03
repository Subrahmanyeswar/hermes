# tests/test_response_contract_and_browser_acceptance.py
"""
Targeted regression tests for:
1. API response shape contract validation (Object envelope vs Raw array, destructuring, mismatches).
2. Authoritative browser acceptance verification via Chrome CDP / headless browser.
3. Deliverable completeness gate in CompletionPolicy (automated tests and README).
4. Safe bypass for non-web projects.
"""

import tempfile
import pytest
from pathlib import Path
from core.cross_file_contract import CrossFileContractValidator
from core.agent_loop.completion import CompletionPolicy
from core.browser.acceptance import BrowserAcceptanceVerifier, BrowserAcceptanceResult


@pytest.fixture
def temp_ws():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_01_object_envelope_pass(temp_ws):
    """Test 1: Backend returns Object envelope { tasks: rows } and frontend destructures { tasks }."""
    (temp_ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        app.get('/api/tasks', (req, res) => {
            res.json({ tasks: [1, 2, 3] });
        });
    """, encoding="utf-8")

    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <div id="app"></div>
        <script src="script.js"></script>
        </body></html>
    """, encoding="utf-8")

    (temp_ws / "script.js").write_text("""
        async function load() {
            const res = await fetch('/api/tasks');
            const { tasks } = await res.json();
            tasks.forEach(t => console.log(t));
        }
        document.getElementById('app');
    """, encoding="utf-8")

    rep = CrossFileContractValidator.validate_workspace(temp_ws)
    assert len(rep.response_shape_mismatches) == 0, f"Expected 0 mismatches, got: {rep.response_shape_mismatches}"


def test_02_raw_array_pass(temp_ws):
    """Test 2: Backend returns raw array [rows] and frontend uses response directly as array."""
    (temp_ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        app.get('/api/items', (req, res) => {
            res.json([1, 2, 3]);
        });
    """, encoding="utf-8")

    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <div id="list"></div>
        <script src="script.js"></script>
        </body></html>
    """, encoding="utf-8")

    (temp_ws / "script.js").write_text("""
        async function load() {
            const res = await fetch('/api/items');
            const items = await res.json();
            items.forEach(i => console.log(i));
        }
        document.getElementById('list');
    """, encoding="utf-8")

    rep = CrossFileContractValidator.validate_workspace(temp_ws)
    assert len(rep.response_shape_mismatches) == 0, f"Expected 0 mismatches, got: {rep.response_shape_mismatches}"


def test_03_envelope_vs_array_mismatch_fail(temp_ws):
    """Test 3: Backend returns Object envelope { tasks: rows } but frontend calls .forEach directly on tasks."""
    (temp_ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        app.get('/api/tasks', (req, res) => {
            res.json({ tasks: [1, 2, 3] });
        });
    """, encoding="utf-8")

    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <div id="task-list"></div>
        <script src="script.js"></script>
        </body></html>
    """, encoding="utf-8")

    (temp_ws / "script.js").write_text("""
        async function fetchTasks() {
            const res = await fetch('/api/tasks');
            const tasks = await res.json();
            renderTasks(tasks);
        }
        function renderTasks(tasks) {
            tasks.forEach(t => console.log(t));
        }
        document.getElementById('task-list');
    """, encoding="utf-8")

    rep = CrossFileContractValidator.validate_workspace(temp_ws)
    assert len(rep.response_shape_mismatches) > 0, "Expected response shape mismatch error"
    assert any("tasks.forEach" in m or "raw Array directly" in m for m in rep.response_shape_mismatches)


def test_04_missing_envelope_property_fail(temp_ws):
    """Test 4: Backend returns { tasks: ... } but frontend destructures { items }."""
    (temp_ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        app.get('/api/tasks', (req, res) => {
            res.json({ tasks: [1, 2, 3] });
        });
    """, encoding="utf-8")

    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <div id="main"></div>
        <script src="script.js"></script>
        </body></html>
    """, encoding="utf-8")

    (temp_ws / "script.js").write_text("""
        async function fetchTasks() {
            const res = await fetch('/api/tasks');
            const { items } = await res.json();
            console.log(items);
        }
        document.getElementById('main');
    """, encoding="utf-8")

    rep = CrossFileContractValidator.validate_workspace(temp_ws)
    assert len(rep.response_shape_mismatches) > 0, "Expected missing envelope property mismatch"


def test_05_destructured_multiple_properties_pass(temp_ws):
    """Test 5: Multiple envelope properties returned and correctly accessed/destructured."""
    (temp_ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        app.get('/api/dashboard', (req, res) => {
            res.json({ stats: {}, users: [], active_count: 5 });
        });
    """, encoding="utf-8")

    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <div id="dash"></div>
        <script src="script.js"></script>
        </body></html>
    """, encoding="utf-8")

    (temp_ws / "script.js").write_text("""
        async function loadDash() {
            const res = await fetch('/api/dashboard');
            const data = await res.json();
            console.log(data.stats, data.users, data.active_count);
        }
        document.getElementById('dash');
    """, encoding="utf-8")

    rep = CrossFileContractValidator.validate_workspace(temp_ws)
    assert len(rep.response_shape_mismatches) == 0


def test_06_dynamic_unresolved_unverified(temp_ws):
    """Test 6: Dynamic endpoint URL is recorded as uncertainty, not a hard crash."""
    (temp_ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        app.get('/api/users/:id', (req, res) => { res.json({ id: 1 }); });
    """, encoding="utf-8")

    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <div id="u"></div>
        <script src="script.js"></script>
        </body></html>
    """, encoding="utf-8")

    (temp_ws / "script.js").write_text("""
        async function loadUser(customEndpoint) {
            const res = await fetch(customEndpoint);
            const user = await res.json();
        }
        document.getElementById('u');
    """, encoding="utf-8")

    rep = CrossFileContractValidator.validate_workspace(temp_ws)
    # Valid should not be hard-failed by dynamic calls
    assert isinstance(rep.uncertainties, list)


def test_07_completion_gate_rejection_on_shape_mismatch(temp_ws):
    """Test 7: CompletionPolicy rejects completion when response shape mismatch is present."""
    (temp_ws / "server.js").write_text("""
        const express = require('express');
        const app = express();
        app.get('/api/tasks', (req, res) => {
            res.json({ tasks: [1, 2, 3] });
        });
    """, encoding="utf-8")

    (temp_ws / "style.css").write_text("body { color: red; }", encoding="utf-8")

    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html>
        <head><link rel="stylesheet" href="style.css"></head>
        <body>
        <div id="app"><button id="btn">Click</button></div>
        <script src="script.js"></script>
        </body></html>
    """, encoding="utf-8")

    (temp_ws / "script.js").write_text("""
        async function fetchTasks() {
            const res = await fetch('/api/tasks');
            const tasks = await res.json();
            tasks.forEach(t => console.log(t));
        }
        document.getElementById('app');
        document.getElementById('btn');
    """, encoding="utf-8")

    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Create task management app",
        workspace=temp_ws,
    )
    assert not ok, "Completion should be rejected due to response shape mismatch"
    assert any("response shape mismatch" in str(x).lower() or "shape" in str(x).lower() for x in [reason] + issues)


def test_08_completion_gate_rejection_on_console_typeerror(temp_ws):
    """Test 8: Headless browser acceptance fails and CompletionPolicy rejects completion when JavaScript throws runtime exceptions."""
    (temp_ws / "style.css").write_text("body { color: red; margin: 0; padding: 0; background: #fff; }", encoding="utf-8")
    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head><body>
        <div id="content">Hello World this is a dashboard test</div>
        <script src="script.js"></script>
        </body></html>
    """, encoding="utf-8")

    (temp_ws / "script.js").write_text("""
        console.log("App loaded");
        // Injected uncaught runtime TypeError
        const tasks = { notAnArray: true };
        tasks.forEach(t => console.log("Task:", t));
        document.getElementById('content').innerText = "Loaded";
    """, encoding="utf-8")

    (temp_ws / "README.md").write_text(
        "# Task Dashboard Application\n\n## Overview\nComplete task dashboard.\n\n## Setup\nRun npm install\n\n## Usage\nRun npm start\n",
        encoding="utf-8"
    )

    res = BrowserAcceptanceVerifier.verify_workspace_sync(temp_ws)
    if res.status != "SKIPPED":
        assert not res.passed, "Browser verification should fail on unhandled TypeError"
        assert any("TypeError" in str(i) for i in res.issues)

        # Directly verify that CompletionPolicy rejects mission completion due to browser failure
        policy = CompletionPolicy()
        ok, reason, issues = policy.evaluate_completion(
            mission_prompt="Build task dashboard app",
            workspace=temp_ws,
        )
        assert not ok, "CompletionPolicy must reject completion on browser runtime failure"
        assert any("browser acceptance failed" in str(x).lower() or "typeerror" in str(x).lower() for x in [reason] + issues)


def test_09_completion_gate_rejection_on_missing_tests_or_readme(temp_ws):
    """Test 9: CompletionPolicy rejects when prompt requested tests/README but they are missing."""
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body><div id='a'></div><script src='s.js'></script></body></html>")
    (temp_ws / "s.js").write_text("document.getElementById('a');")

    policy = CompletionPolicy()
    # Prompt requested tests and README
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Build application. Create an automated test suite and create README.md",
        workspace=temp_ws,
    )
    assert not ok, "Completion should be rejected when deliverables are missing"
    assert any("test suite" in i.lower() or "readme" in i.lower() for i in issues)


def test_10_non_web_task_bypass(temp_ws):
    """Test 10: Non-web projects (e.g. CLI tools, data scripts) safely bypass browser acceptance."""
    (temp_ws / "calculator.py").write_text("""
def add(a, b):
    return a + b

if __name__ == '__main__':
    print(add(2, 3))
    """, encoding="utf-8")

    # BrowserAcceptanceVerifier should return SKIPPED, passed=True
    b_res = BrowserAcceptanceVerifier.verify_workspace_sync(temp_ws)
    assert b_res.passed
    assert b_res.status == "SKIPPED"

    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Implement a Python calculator module",
        workspace=temp_ws,
    )
    assert ok, f"Non-web mission should complete cleanly: {reason}, issues: {issues}"


def test_11_browser_cannot_start_rejection(temp_ws, monkeypatch):
    """Test 11: Browser acceptance fails when browser binary cannot start or is missing."""
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body><h1>App</h1></body></html>", encoding="utf-8")
    (temp_ws / "app.js").write_text("console.log('init');", encoding="utf-8")

    monkeypatch.setattr(BrowserAcceptanceVerifier, "find_browser_executable", classmethod(lambda cls: None))
    res = BrowserAcceptanceVerifier.verify_workspace_sync(temp_ws)
    assert not res.passed
    assert res.status == "FAIL"
    assert any("Missing browser binary" in str(res.details) or "binary found" in i for i in res.issues)


def test_12_cdp_connection_failure_rejection(temp_ws, monkeypatch):
    """Test 12: Browser acceptance fails when CDP connection fails."""
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body><h1>App</h1></body></html>", encoding="utf-8")
    (temp_ws / "app.js").write_text("console.log('init');", encoding="utf-8")

    monkeypatch.setattr(BrowserAcceptanceVerifier, "find_free_port", classmethod(lambda cls: 65530))
    # Make urlopen raise exception
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionRefusedError("Connection refused")))

    res = BrowserAcceptanceVerifier.verify_workspace_sync(temp_ws)
    assert not res.passed
    assert res.status == "FAIL"
    assert any("CDP connection" in i for i in res.issues)


def test_13_meaningful_rendering_failure_rejection(temp_ws):
    """Test 13: Browser acceptance fails when page loads but body rendering is empty/meaningless."""
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body>   </body></html>", encoding="utf-8")
    (temp_ws / "app.js").write_text("// No rendering", encoding="utf-8")

    res = BrowserAcceptanceVerifier.verify_workspace_sync(temp_ws)
    if res.status != "SKIPPED":
        assert not res.passed
        assert any("empty or unrendered" in i for i in res.issues)


def test_14_required_interaction_workflow_failure(temp_ws):
    """Test 14: Browser acceptance fails when a required interactive workflow encounters an assertion failure."""
    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <div id="content">Static Content</div>
        <button id="btn" onclick="document.getElementById('content').innerText = 'Wrong Text'">Click</button>
        <script src="app.js"></script>
        </body></html>
    """, encoding="utf-8")
    (temp_ws / "app.js").write_text("// app loaded", encoding="utf-8")

    workflows = [
        {
            "name": "Update Text Workflow",
            "steps": [
                {"action": "evaluate", "expression": "document.getElementById('btn').click()"},
                {"action": "assert_dom", "expression": "document.getElementById('content').innerText === 'Expected Text'", "error": "Content did not update to expected text"}
            ]
        }
    ]
    res = BrowserAcceptanceVerifier.verify_workspace_sync(temp_ws, workflows=workflows)
    if res.status != "SKIPPED":
        assert not res.passed
        assert any("Update Text Workflow" in i for i in res.issues)


def test_15_application_persistence_failure(temp_ws):
    """Test 15: Browser acceptance fails when application state fails to persist across page reload."""
    (temp_ws / "index.html").write_text("""
        <!DOCTYPE html><html><body>
        <div id="items">Initial Content In Document Body</div>
        <p>Another paragraph to ensure meaningful body rendering for acceptance checks.</p>
        <script src="app.js"></script>
        </body></html>
    """, encoding="utf-8")
    (temp_ws / "app.js").write_text("// loaded", encoding="utf-8")

    workflows = [
        {
            "name": "Check Persistence Workflow",
            "steps": [
                {"action": "evaluate", "expression": "window.__ephemeral_state = 123;"},
                {"action": "reload"},
                {"action": "assert_dom", "expression": "window.__ephemeral_state === 123", "error": "Ephemeral state failed to persist across page reload"}
            ]
        }
    ]
    res = BrowserAcceptanceVerifier.verify_workspace_sync(temp_ws, workflows=workflows)
    if res.status != "SKIPPED":
        assert not res.passed
        assert any("Persistence" in i or "persist" in i.lower() for i in res.issues)


def test_16_stale_or_missing_evidence_rejection(temp_ws):
    """Test 16: Acceptance evidence check rejects missing or stale evidence from modified workspace."""
    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body><h1>Title Of App</h1><p>Meaningful paragraph content for browser acceptance verification testing.</p></body></html>", encoding="utf-8")
    (temp_ws / "app.js").write_text("console.log('1');", encoding="utf-8")

    # Missing evidence initially
    fresh_ok, msg = BrowserAcceptanceVerifier.check_evidence_freshness(temp_ws)
    assert not fresh_ok
    assert "missing" in msg.lower()

    # Generate evidence
    res = BrowserAcceptanceVerifier.verify_workspace_sync(temp_ws)
    if res.status != "SKIPPED":
        fresh_ok, msg = BrowserAcceptanceVerifier.check_evidence_freshness(temp_ws)
        assert fresh_ok

        # Mutate a source file
        (temp_ws / "app.js").write_text("console.log('mutated 2');", encoding="utf-8")
        fresh_ok_after_mutation, msg2 = BrowserAcceptanceVerifier.check_evidence_freshness(temp_ws)
        assert not fresh_ok_after_mutation
        assert "stale" in msg2.lower()


def test_17_invalid_or_empty_readme_rejection(temp_ws):
    """Test 17: CompletionPolicy rejects when README.md is empty or lacks setup/run instructions."""
    (temp_ws / "app.py").write_text("print('hello')", encoding="utf-8")
    (temp_ws / "README.md").write_text("# Project Title\n\nShort placeholder without setup instructions.", encoding="utf-8")

    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Build application. Include README.md with setup and execution instructions.",
        workspace=temp_ws,
    )
    assert not ok
    assert any("readme" in i.lower() for i in issues)


def test_18_test_file_exists_but_execution_fails(temp_ws):
    """Test 18: CompletionPolicy rejects when test file exists but test runner execution fails."""
    (temp_ws / "app.py").write_text("def add(a, b): return a + b", encoding="utf-8")
    (temp_ws / "test_app.py").write_text("""
import pytest
from app import add

def test_add_failing():
    assert add(1, 1) == 999  # Deliberate failure
""", encoding="utf-8")
    (temp_ws / "README.md").write_text("""# App
This is an app.
## Setup and Run
Run: python -m pytest
Run tests to verify.
""", encoding="utf-8")

    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Build app with automated tests and README documentation.",
        workspace=temp_ws,
    )
    assert not ok
    assert any("tests failed" in i.lower() or "tests failed" in reason.lower() for i in issues + [reason])


def test_19_test_command_succeeds_acceptance(temp_ws):
    """Test 19: CompletionPolicy accepts when automated tests execute and pass cleanly."""
    (temp_ws / "app.py").write_text("def add(a, b): return a + b", encoding="utf-8")
    (temp_ws / "test_app.py").write_text("""
import pytest
from app import add

def test_add_passing():
    assert add(1, 1) == 2
""", encoding="utf-8")
    (temp_ws / "README.md").write_text("""# App Title
This is a verified test application.
## Setup and Execution
Run with: python -m pytest
Install dependencies: pip install pytest
""", encoding="utf-8")

    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion(
        mission_prompt="Build app with automated tests and README documentation.",
        workspace=temp_ws,
    )
    assert ok, f"Passing tests and valid README should be accepted: {reason}, {issues}"


def test_20_acceptance_ledger_integration(temp_ws):
    """Test 20: Browser acceptance records result into AcceptanceLedger."""
    from core.runtime_state.models import AcceptanceLedger, AcceptanceCheckStatus
    ledger = AcceptanceLedger()

    (temp_ws / "index.html").write_text("<!DOCTYPE html><html><body><h1>Valid Page Content</h1><script src='app.js'></script></body></html>", encoding="utf-8")
    (temp_ws / "app.js").write_text("console.log('App active');", encoding="utf-8")

    res = BrowserAcceptanceVerifier.verify_workspace_sync(temp_ws, acceptance_ledger=ledger)
    if res.status != "SKIPPED":
        chk = ledger.checks.get("chk_browser_acceptance")
        assert chk is not None, "chk_browser_acceptance should be registered in ledger"
        assert chk.status in (AcceptanceCheckStatus.PASS, AcceptanceCheckStatus.FAIL)
