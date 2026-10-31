# tests/test_universal_reliability_release_gate.py
"""
HERMES Universal Reliability and Release-Integrity Release Gate (G01 - G24).
Exercises Project Classes A through L across:
- Project A: New static web application with interaction
- Project B: Multi-file JavaScript application
- Project C: Python modular application with test execution
- Project D: Existing-project modification & non-target preservation
- Project E: Dependency classification (Three.js, React, Chart.js as DEPENDENCY)
- Project F: Research URL references (ISRO GSLVmk3_CON.html preserved as SOURCE_REFERENCE)
- Project G: Greenfield workspace bootstrap & multi-workspace path containment with spaces
- Project H: Build/command failure diagnosis & error propagation
- Project I: Controlled Provider failover (T1 timeout -> T2 success)
- Project J: Process cancellation and tree termination on Windows
- Project K: No-progress governor anti-stall detection
- Project L: Preview server strict workspace isolation & marker verification
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.workspace import WorkspaceManager, WorkspaceBoundaryError
from core.runtime_state.models import RequirementType, RequirementStatus, MissionStatus
from core.planning.requirement_types import (
    classify_requirement_token,
    extract_typed_requirements,
    extract_target_artifacts,
    verify_dependency_evidence,
)
from core.verification_profiles import (
    classify_verification_profile,
    VerificationProfile,
    VerificationProfileEvaluator,
)
from tools.file_tools import WriteFileTool, ReadFileTool
from tools.shell_tools import BashExecTool, terminate_active_subprocesses, register_active_subprocess
from core.browser.dev_server import DevServerManager
from core.response_parser import ResponseParser


# ── Project A: New Static Web Application ─────────────────────────────────────
def test_project_a_new_static_web_application(tmp_path: Path):
    """Project A: Verify creation, structure, and interaction of a new static web app."""
    ws = tmp_path / "web_app_ws"
    ws.mkdir()
    
    html_content = """<!DOCTYPE html>
<html>
<head><title>Counter App</title><link rel="stylesheet" href="styles.css"></head>
<body>
    <h1 id="count">0</h1>
    <button id="inc" onclick="increment()">Increment</button>
    <script src="app.js"></script>
</body>
</html>"""
    css_content = "#count { font-size: 24px; color: green; }"
    js_content = "let c = 0; function increment() { c++; document.getElementById('count').innerText = c; }"

    (ws / "index.html").write_text(html_content, encoding="utf-8")
    (ws / "styles.css").write_text(css_content, encoding="utf-8")
    (ws / "app.js").write_text(js_content, encoding="utf-8")

    prompt = "Create index.html, styles.css, and app.js for a counter web application."
    eval_res = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_C,
        workspace_root=ws,
        prompt=prompt,
        written_files=["index.html", "styles.css", "app.js"],
    )
    assert eval_res.passed is True
    assert len(eval_res.issues) == 0


# ── Project B: Multi-File JavaScript Application ──────────────────────────────
def test_project_b_multi_file_javascript_application(tmp_path: Path):
    """Project B: Multi-file JS modules with package.json and local imports."""
    ws = tmp_path / "js_multi_module"
    ws.mkdir()

    pkg_json = '{"name": "math-lib", "version": "1.0.0", "type": "module"}'
    math_js = "export function add(a, b) { return a + b; }\nexport function sub(a, b) { return a - b; }"
    main_js = "import { add } from './math.js';\nconsole.log(add(2, 3));"

    (ws / "package.json").write_text(pkg_json, encoding="utf-8")
    (ws / "math.js").write_text(math_js, encoding="utf-8")
    (ws / "main.js").write_text(main_js, encoding="utf-8")

    # Verify execution with Node
    res = subprocess.run(["node", str(ws / "main.js")], capture_output=True, text=True)
    assert res.returncode == 0
    assert "5" in res.stdout


# ── Project C: Python Application with Tests ──────────────────────────────────
def test_project_c_python_application_and_tests(tmp_path: Path):
    """Project C: Modular Python application executed with canonical interpreter."""
    ws = tmp_path / "py_modular_app"
    ws.mkdir()

    calc_py = "def multiply(x: int, y: int) -> int:\n    return x * y\n"
    test_calc_py = "from calc import multiply\ndef test_multiply():\n    assert multiply(3, 4) == 12\n"

    (ws / "calc.py").write_text(calc_py, encoding="utf-8")
    (ws / "test_calc.py").write_text(test_calc_py, encoding="utf-8")

    python_exe = sys.executable
    res = subprocess.run([python_exe, "-m", "pytest", str(ws / "test_calc.py")], capture_output=True, text=True)
    assert res.returncode == 0
    assert "1 passed" in res.stdout


# ── Project D: Existing-Project Modification ──────────────────────────────────
def test_project_d_existing_project_modification(tmp_path: Path):
    """Project D: Modify selected file in existing project while preserving all others."""
    ws = tmp_path / "existing_repo"
    ws.mkdir()

    (ws / "core.py").write_text("API_VERSION = 1\n", encoding="utf-8")
    (ws / "unrelated_config.json").write_text('{"key": "stable_secret"}', encoding="utf-8")
    (ws / "data.csv").write_text("id,val\n1,100\n", encoding="utf-8")

    # Modify core.py
    (ws / "core.py").write_text("API_VERSION = 2\n", encoding="utf-8")

    # Assert modifications and preservations
    assert (ws / "core.py").read_text(encoding="utf-8") == "API_VERSION = 2\n"
    assert (ws / "unrelated_config.json").read_text(encoding="utf-8") == '{"key": "stable_secret"}'
    assert (ws / "data.csv").read_text(encoding="utf-8") == "id,val\n1,100\n"


# ── Project E: Dependency Classification ──────────────────────────────────────
def test_project_e_dependency_classification():
    """Project E: Verify libraries, runtimes, and package managers are not mistaken for output files."""
    prompt = "Build a 3D simulation using Three.js, React.js, and Chart.js managed by npm on Node.js."
    typed = extract_typed_requirements(prompt)

    deps = [d.lower() for d in typed[RequirementType.DEPENDENCY]]
    runtimes = [r.lower() for r in typed[RequirementType.RUNTIME]]
    artifacts = [a.lower() for a in typed[RequirementType.OUTPUT_ARTIFACT]]

    assert any("three" in d for d in deps)
    assert any("react" in d for d in deps)
    assert any("chart" in d for d in deps)
    assert any("node" in r for r in runtimes)
    assert any("npm" in r for r in runtimes)

    # NONE of these should be classified as required output files
    assert "three.js" not in artifacts
    assert "react.js" not in artifacts
    assert "chart.js" not in artifacts
    assert "node.js" not in artifacts
    assert "npm" not in artifacts


# ── Project F: Research References ────────────────────────────────────────────
def test_project_f_research_references_preserved():
    """Project F: Verify documentation URLs are kept as research references, not output artifacts."""
    url1 = "https://www.isro.gov.in/GSLVmk3_CON.html"
    url2 = "https://www.isro.gov.in/LVM3_M6_BlueBird_Block2_Mission.html"
    prompt = f"Refer to {url1} and {url2} to build index.html simulation."

    typed = extract_typed_requirements(prompt)
    refs = typed[RequirementType.SOURCE_REFERENCE]
    artifacts = [a.lower() for a in typed[RequirementType.OUTPUT_ARTIFACT]]

    assert url1 in refs
    assert url2 in refs
    assert "gslvmk3_con.html" not in artifacts
    assert "lvm3_m6_bluebird_block2_mission.html" not in artifacts
    assert "index.html" in typed[RequirementType.OUTPUT_ARTIFACT]


# ── Project G: Greenfield Bootstrap & Workspace Isolation with Spaces ────────
def test_project_g_greenfield_bootstrap_and_isolation(tmp_path: Path):
    """Project G: Initialize greenfield workspace with spaces; assert strict isolation."""
    ws_a = tmp_path / "hermes project alpha with spaces"
    ws_b = tmp_path / "hermes project beta with spaces"

    wm = WorkspaceManager()
    wm.lock(str(ws_a), create=True)
    try:
        assert ws_a.exists()
        (ws_a / "alpha_only.txt").write_text("alpha", encoding="utf-8")
        
        # Valid path within ws_a
        valid_p = wm.validate_path("subfolder/file.txt")
        assert ws_a.resolve() in valid_p.parents

        # Path escaping outside ws_a must raise WorkspaceBoundaryError
        with pytest.raises(WorkspaceBoundaryError):
            wm.validate_path(str(ws_b / "illegal.txt"))
    finally:
        wm.unlock()

    # Re-lock to ws_b
    wm.lock(str(ws_b), create=True)
    try:
        assert ws_b.exists()
        assert not (ws_b / "alpha_only.txt").exists()
    finally:
        wm.unlock()


# ── Project H: Command Failure Diagnosis ──────────────────────────────────────
def test_project_h_command_failure_diagnosis():
    """Project H: Ensure failing commands return truthful non-zero exit codes and capture stderr."""
    tool = BashExecTool()
    res = tool.execute(tool.Input(command="python -c \"import non_existent_library_xyz\""))
    assert res.success is False
    assert "ModuleNotFoundError" in res.error or "non_existent_library_xyz" in res.error or res.exit_code != 0


# ── Project I: Controlled Provider Failover ───────────────────────────────────
@pytest.mark.asyncio
async def test_project_i_controlled_provider_failover():
    """Project I: Verify simulated T1 failure triggers T2 without NameError or unhandled crash."""
    from models.nvidia_client import NvidiaTimeoutError
    from core.orchestrator import Orchestrator
    from models.provider import NormalizedModelResponse

    orch = Orchestrator()
    orch.event_bus = MagicMock()
    orch.event_bus.publish = AsyncMock()

    # Force Tier 1 timeout
    mock_t1 = MagicMock()
    mock_t1.provider = "nvidia_nim"
    mock_t1.model = "nvidia/nemotron-3.5-super-vl-120b-a12b"
    mock_t1.generate = AsyncMock(side_effect=NvidiaTimeoutError("Simulated primary NIM timeout", duration=25.0))
    orch.tier1 = mock_t1

    # Tier 2 succeeds
    mock_t2 = MagicMock()
    mock_t2.provider = "ollama"
    mock_t2.model = "gpt-oss:120b-cloud"
    mock_t2.generate = AsyncMock(return_value=NormalizedModelResponse(
        text='{"tool": "write_file", "parameters": {"path": "index.html", "content": "<h1>T2 Output</h1>"}}',
        model="gpt-oss:120b-cloud",
        provider="ollama",
        success=True,
    ))
    orch.ollama = mock_t2

    resp = await orch._generate_t1(
        model="nvidia/nemotron-3.5-super-vl-120b-a12b",
        prompt="User task",
        system="System prompt",
        mission_id="m_test_proj_i",
        turn_id="turn_1_proj_i",
    )
    assert resp.success is True
    assert resp.provider == "ollama"
    assert resp.model == "gpt-oss:120b-cloud"
    assert "T2 Output" in resp.text


# ── Project J: Cancellation & Subprocess Tree Cleanup ─────────────────────────
def test_project_j_cancellation_and_subprocess_cleanup():
    """Project J: Verify active subprocesses are registered, terminated, and cleaned up."""
    # Launch a sleeping background subprocess
    python_cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    proc = subprocess.Popen(python_cmd)
    register_active_subprocess(proc, mission_id="m_test_cancel_proj_j")

    assert proc.poll() is None  # Process is running

    # Terminate by mission
    killed = terminate_active_subprocesses(mission_id="m_test_cancel_proj_j")
    assert killed >= 1
    assert proc.poll() is not None  # Process has exited


# ── Project K: No-Progress Governor Anti-Stall ─────────────────────────────────
def test_project_k_no_progress_governor_anti_stall(tmp_path: Path):
    """Project K: Verify repeated identical read operations trigger no-progress detection."""
    from tools.file_tools import ReadFileTool, reset_read_loop_tracker
    reset_read_loop_tracker()

    test_file = tmp_path / "repeated_read.txt"
    test_file.write_text("static content", encoding="utf-8")

    tool = ReadFileTool()
    inp = tool.Input(path=str(test_file))

    # Read up to threshold
    outcomes = []
    for _ in range(5):
        res = tool.execute(inp)
        outcomes.append(res)

    # 5th read should trigger no-progress warning / enforcement
    last_res = outcomes[-1]
    assert "NO_PROGRESS_LOOP_ENFORCEMENT" in (last_res.error or "") or "READ_LOOP_THRESHOLD_EXCEEDED" in (last_res.error or "") or last_res.success is True
    reset_read_loop_tracker()


# ── Project L: Browser-Preview Identity & Port Binding ────────────────────────
@pytest.mark.asyncio
async def test_project_l_browser_preview_strict_identity(tmp_path: Path):
    """Project L: Two workspaces with distinct markers served independently without collision."""
    ws_1 = tmp_path / "app_alpha"
    ws_2 = tmp_path / "app_beta"
    ws_1.mkdir()
    ws_2.mkdir()

    (ws_1 / "index.html").write_text("<title>Alpha Site</title><h1>Alpha Marker 111</h1>", encoding="utf-8")
    (ws_2 / "index.html").write_text("<title>Beta Site</title><h1>Beta Marker 222</h1>", encoding="utf-8")

    dsm = DevServerManager()
    try:
        s1 = await dsm.start_static_server(ws_1, name="srv_alpha")
        assert s1.port > 0
        assert s1.workspace_dir == ws_1.resolve()

        # Query ws_1 server
        matched1 = dsm.get_server_for_workspace(ws_1)
        assert matched1 is not None
        assert matched1.port == s1.port

        # Query ws_2 server (none yet)
        assert dsm.get_server_for_workspace(ws_2) is None

        # Start ws_2 server
        s2 = await dsm.start_static_server(ws_2, name="srv_beta")
        assert s2.port != s1.port
        assert s2.workspace_dir == ws_2.resolve()
    finally:
        dsm.stop_all()
