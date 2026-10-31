"""
tests/test_phase5_completion_gate.py
====================================
Phase 5 Acceptance Tests - Completion Policy & Quality Gate Enforcement.

Scenario M: Incomplete/broken application is evaluated by CompletionPolicy.
            Even if tool calls succeeded, if alignment verification finds hard errors,
            CompletionPolicy rejects completion (is_complete=False).

Scenario N: Complete valid application passing all contract checks is evaluated.
            CompletionPolicy approves completion (is_complete=True).
"""

import pytest
from pathlib import Path

from core.contracts.builder import ContractBuilder
from core.contracts.manifest import ElementContract
from core.agent_loop.completion import CompletionPolicy
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus
from core.workspace import WorkspaceManager


@pytest.fixture
def mock_runtime_state():
    state = HermesRuntimeState(mission=MissionState(mission_id="p5-completion-gate-test", status=MissionStatus.RUNNING))
    return state


def test_scenario_m_no_false_completion_when_verification_fails(tmp_path: Path, mock_runtime_state):
    """
    Scenario M:
    An application where index.html references a nonexistent stylesheet and missing DOM elements.
    CompletionPolicy MUST reject completion because verify_project_alignment flags hard errors.
    """
    workspace = tmp_path / "broken_app"
    workspace.mkdir()

    # Broken HTML: broken link href and broken script src
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>Defective App</title>
    <link rel="stylesheet" href="missing.css">
</head>
<body>
    <div id="content">Hello</div>
    <script src="app.js"></script>
</body>
</html>"""
    (workspace / "index.html").write_text(html_content, encoding="utf-8")
    (workspace / "styles.css").write_text("body { color: red; }", encoding="utf-8")
    (workspace / "app.js").write_text("console.log('app running');", encoding="utf-8")

    # Contract mandates index.html, styles.css, app.js, and specific controls
    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id="p5-completion-gate-test",
        prompt="Create an interactive calculator with styles.css and app.js",
        extra_files=["styles.css", "app.js"],
    )
    manifest.element_ids["calc-btn"] = ElementContract(dom_id="calc-btn", tag="button", owning_file="index.html", purpose="calculate", required=True)
    manifest.element_ids["display"] = ElementContract(dom_id="display", tag="div", owning_file="index.html", purpose="display", required=True)

    mock_runtime_state.blueprint = blueprint
    mock_runtime_state.interface_manifest = manifest
    mock_runtime_state.quality_rubric = rubric

    wm = WorkspaceManager()
    wm.lock(workspace)

    policy = CompletionPolicy()
    is_complete, reason, unmet = policy.evaluate_completion(
        mission_prompt="Create an interactive calculator with styles.css and app.js",
        workspace=wm,
        runtime_state=mock_runtime_state,
        written_files=["index.html", "styles.css", "app.js"],
    )

    # Verification must reject completion
    assert not is_complete, f"CompletionPolicy must NOT approve completion when contracts fail. Reason: {reason}"
    assert len(unmet) > 0
    # Must report contract verification errors
    assert "Contract alignment verification failed" in reason or any("BROKEN_REFERENCE" in u for u in unmet)


def test_scenario_n_legitimate_completion_when_contract_passes(tmp_path: Path, mock_runtime_state):
    """
    Scenario N:
    A fully valid application matching all contract requirements and passing alignment verification.
    CompletionPolicy approves completion.
    """
    workspace = tmp_path / "valid_app"
    workspace.mkdir()

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Valid Timer App</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="app" class="container">
        <header id="header">
            <h1>Timer Application</h1>
        </header>
        <main id="mainContent" class="card">
            <div id="display">00:00</div>
            <button id="actionButton" class="btn" type="button" aria-label="Action">Action</button>
            <button id="start-btn" class="btn" type="button" aria-label="Start Timer">Start</button>
            <button id="reset-btn" class="btn" type="button" aria-label="Reset Timer">Reset</button>
        </main>
    </div>
    <script src="app.js"></script>
</body>
</html>"""
    (workspace / "index.html").write_text(html_content, encoding="utf-8")

    css_content = """
body { font-family: sans-serif; margin: 0; padding: 20px; }
.container { max-width: 600px; margin: 0 auto; }
.card { padding: 20px; background: #fff; }
.btn { padding: 10px 20px; cursor: pointer; }
#display { font-size: 2rem; font-weight: bold; }
button { padding: 10px 20px; cursor: pointer; }
"""
    (workspace / "styles.css").write_text(css_content, encoding="utf-8")

    js_content = """
let timer = null;
let seconds = 0;
const display = document.getElementById('display');
const startBtn = document.getElementById('start-btn');
const resetBtn = document.getElementById('reset-btn');

startBtn.addEventListener('click', () => {
    if (!timer) {
        timer = setInterval(() => {
            seconds++;
            const mins = String(Math.floor(seconds / 60)).padStart(2, '0');
            const secs = String(seconds % 60).padStart(2, '0');
            display.textContent = `${mins}:${secs}`;
        }, 1000);
    }
});

resetBtn.addEventListener('click', () => {
    clearInterval(timer);
    timer = null;
    seconds = 0;
    display.textContent = '00:00';
});
"""
    (workspace / "app.js").write_text(js_content, encoding="utf-8")

    builder = ContractBuilder()
    blueprint, manifest, rubric = builder.build_web_contract(
        mission_id="p5-completion-gate-test",
        prompt="Create a functional timer app with start and reset buttons",
        extra_files=["styles.css", "app.js"],
    )
    manifest.element_ids["start-btn"] = ElementContract(dom_id="start-btn", tag="button", owning_file="index.html", purpose="start", required=True)
    manifest.element_ids["reset-btn"] = ElementContract(dom_id="reset-btn", tag="button", owning_file="index.html", purpose="reset", required=True)
    manifest.element_ids["display"] = ElementContract(dom_id="display", tag="div", owning_file="index.html", purpose="display", required=True)

    mock_runtime_state.blueprint = blueprint
    mock_runtime_state.interface_manifest = manifest
    mock_runtime_state.quality_rubric = rubric

    wm = WorkspaceManager()
    wm.lock(workspace)

    policy = CompletionPolicy()
    is_complete, reason, unmet = policy.evaluate_completion(
        mission_prompt="Create a functional timer app with start and reset buttons",
        workspace=wm,
        runtime_state=mock_runtime_state,
        written_files=["index.html", "styles.css", "app.js"],
    )

    assert is_complete, f"CompletionPolicy should approve valid app, but failed: {reason} | {unmet}"
    assert len(unmet) == 0
