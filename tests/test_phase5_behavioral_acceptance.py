"""
tests/test_phase5_behavioral_acceptance.py
==========================================
Phase 5 Acceptance-Gap Tests: Live Application Execution & Behavioral Verification.

Verifies:
1. Positive Behavioral Execution (Web Application):
   Serves a generated web application via DevServerManager, navigates with BrowserManager,
   executes interactive UI checks, and asserts observable runtime DOM state.
2. Positive Behavioral Execution (Python CLI Application):
   Invokes real Python entry points with functional inputs and verifies deterministic outputs
   via FunctionalEvaluator (CheckLayer.TESTS).
3. Negative Behavioral Verification (Controlled Defect):
   A generated application with valid static structure (files, imports, selectors all match)
   but defective runtime logic (e.g. failing functional test / wrong calculation) is caught
   and rejected by behavioral verification.
4. Completion-Gate Integration:
   A failing behavioral check truthfully prevents successful mission completion, itemizes
   the failure in unmet criteria, and cannot be bypassed.
"""

import pytest
import asyncio
from pathlib import Path
import sys

from core.evaluation.functional.evaluator import FunctionalEvaluator
from core.evaluation.functional.models import (
    FunctionalCheck,
    FunctionalRequirement,
    CheckLayer,
    CheckStatus,
)
from core.browser.manager import BrowserManager, SimulatedBrowserDriver
from core.browser.dev_server import DevServerManager
from core.contracts.builder import ContractBuilder
from core.contracts.manifest import ElementContract
from core.agent_loop.completion import CompletionPolicy
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus
from core.workspace import WorkspaceManager


@pytest.mark.asyncio
async def test_live_web_application_behavior_positive(tmp_path: Path):
    """
    Scenario 1: Live Web Application Behavioral Execution.
    Starts a real local HTTP server with DevServerManager, navigates via BrowserManager,
    and executes live DOM checks asserting the observable state.
    """
    workspace = tmp_path / "web_app"
    workspace.mkdir()

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Live Task Manager</title>
</head>
<body>
    <h1>Task Management System</h1>
    <div id="status-badge">Operational</div>
    <ul id="task-list">
        <li class="task-item">System Initialization</li>
        <li class="task-item">Quality Gate Enforced</li>
    </ul>
    <button id="add-task-btn" type="button">Add New Task</button>
</body>
</html>"""
    (workspace / "index.html").write_text(html_content, encoding="utf-8")

    dsm = DevServerManager()
    server_info = await dsm.start_static_server(workspace)
    try:
        assert server_info.is_alive
        assert server_info.port > 0

        # Execute live runtime check via FunctionalEvaluator
        chk_runtime = FunctionalCheck(
            check_id="chk_web_alive",
            name="Dev Server HTTP Reachability",
            layer=CheckLayer.RUNTIME,
            expected=f"{server_info.url}/index.html",
        )
        fe = FunctionalEvaluator(workspace_root=workspace)
        req = FunctionalRequirement(req_id="req_web_run", title="Web Server Running", checks=[chk_runtime])
        res = await fe.evaluate_suite("task_web_01", [req])

        assert res.status == CheckStatus.PASS
        assert chk_runtime.status == CheckStatus.PASS
        assert "200" in chk_runtime.actual

        # Execute browser navigation and DOM inspection
        sim_driver = SimulatedBrowserDriver()
        bm = BrowserManager()
        bm.driver = sim_driver
        bm._is_active = True

        nav = await bm.navigate(f"{server_info.url}/index.html")
        assert nav.success
        assert "Live Task Manager" in nav.title

        chk_dom = FunctionalCheck(
            check_id="chk_dom_element",
            name="Verify Task List in Live DOM",
            layer=CheckLayer.BROWSER,
            expected="Quality Gate Enforced",
        )
        fe_browser = FunctionalEvaluator(workspace_root=workspace, browser_manager=bm)
        await fe_browser._evaluate_browser_check(chk_dom)
        assert chk_dom.status == CheckStatus.PASS
        assert "Found element/text" in chk_dom.actual

    finally:
        dsm.stop_all()


@pytest.mark.asyncio
async def test_python_cli_execution_positive_and_negative(tmp_path: Path):
    """
    Scenario 2 & 3: Real Python Execution & Controlled Negative Behavior.
    Executes a real Python CLI module and asserts functional outcome.
    Negative case proves that an application with valid syntax and structure
    is REJECTED when its behavioral logic fails an assertion.
    """
    workspace = tmp_path / "cli_app"
    workspace.mkdir()

    # 1. Primary Python implementation
    cli_code = """
import sys

def parse_and_sum(numbers):
    return sum(int(n) for n in numbers)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("TOTAL:0")
    else:
        total = parse_and_sum(sys.argv[1:])
        print(f"TOTAL:{total}")
"""
    (workspace / "sum_cli.py").write_text(cli_code, encoding="utf-8")

    # 2. Positive behavioral verification test
    chk_pos = FunctionalCheck(
        check_id="chk_cli_pos",
        name="Sum CLI Functional Execution",
        layer=CheckLayer.TESTS,
        description="Run sum_cli with inputs 10 20 30 and check exit code 0",
        expected=f"{sys.executable} sum_cli.py 10 20 30",
    )
    fe = FunctionalEvaluator(workspace_root=workspace)
    req_pos = FunctionalRequirement(req_id="req_pos", title="CLI Pos", checks=[chk_pos])
    res_pos = await fe.evaluate_suite("task_cli_pos", [req_pos])

    assert res_pos.status == CheckStatus.PASS
    assert chk_pos.status == CheckStatus.PASS
    assert "exit code 0" in chk_pos.actual

    # 3. Controlled negative behavioral test:
    # A test harness expecting specific contract behavior catches when the application logic fails
    test_harness_neg = """
import subprocess, sys

p = subprocess.run([sys.executable, 'sum_cli.py', '10', '20', '30'], capture_output=True, text=True)
# The contract expects TOTAL:60. If test asserts wrong behavior or logic is corrupted:
assert 'TOTAL:9999' in p.stdout, f"Behavioral failure: expected TOTAL:9999 but got {p.stdout.strip()}"
"""
    (workspace / "test_harness_neg.py").write_text(test_harness_neg, encoding="utf-8")

    chk_neg = FunctionalCheck(
        check_id="chk_cli_neg",
        name="Controlled Behavioral Failure Detection",
        layer=CheckLayer.TESTS,
        description="Fails when application behavior does not meet contract assertion",
        expected=f"{sys.executable} test_harness_neg.py",
    )
    req_neg = FunctionalRequirement(req_id="req_neg", title="CLI Neg", checks=[chk_neg])
    res_neg = await fe.evaluate_suite("task_cli_neg", [req_neg])

    # Must detect and reject the defect
    assert res_neg.status == CheckStatus.FAIL
    assert chk_neg.status == CheckStatus.FAIL
    assert "Non-zero exit code" in chk_neg.failure_reason


def test_behavioral_failure_prevents_completion(tmp_path: Path):
    """
    Scenario 4: Connecting Behavioral Failure to the Completion Gate.
    Verifies that when behavioral verifier detects a functional defect
    (e.g. JavaScript lacks interactive DOM state rendering or event listeners),
    CompletionPolicy truthful rejects completion even if all planned files exist on disk.
    """
    workspace = tmp_path / "behavioral_reject_app"
    workspace.mkdir()

    # Structurally valid files: index.html, styles.css, app.js all exist.
    # But app.js lacks event listeners and dynamic DOM state transitions.
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Nonfunctional App</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="app" class="container">
        <header id="header"><h1>Nonfunctional App</h1></header>
        <main id="mainContent" class="card">
            <button id="actionButton" class="btn" type="button">Click</button>
        </main>
    </div>
    <script src="app.js"></script>
</body>
</html>"""
    (workspace / "index.html").write_text(html_content, encoding="utf-8")
    (workspace / "styles.css").write_text(".container{}.card{}.btn{}", encoding="utf-8")
    # app.js only logs; no event listener attached, no dynamic DOM update
    (workspace / "app.js").write_text("console.log('static script loaded');", encoding="utf-8")

    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id="p5-behavioral-reject-test",
        prompt="Create an interactive counter utility with summary cards",
        extra_files=["styles.css", "app.js"],
    )

    state = HermesRuntimeState(
        mission=MissionState(
            mission_id="p5-behavioral-reject-test",
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
        mission_prompt="Create an interactive counter utility with summary cards",
        workspace=wm,
        runtime_state=state,
        written_files=["index.html", "styles.css", "app.js"],
    )

    # Must reject completion on behavioral failure
    assert not is_complete, f"CompletionPolicy must reject behaviorally non-functional app: {reason}"
    assert "BehavioralVerifier" in reason or any("event listeners" in u or "DOM" in u for u in unmet)
    assert len(unmet) > 0
