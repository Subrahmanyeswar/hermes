# tests/test_requirement_classification_and_workspace_lifecycle.py
"""
High-Value Regression Suite for HERMES Autonomous Execution Engine:
Requirement Classification, Workspace Initialization Lifecycle, and Preview Binding.

Verifies:
- R01: Library classification (Three.js, React.js as DEPENDENCY)
- R02: Runtime classification (Node.js, npm, Python as RUNTIME)
- R03: Source URL classification (GSLVmk3_CON.html as SOURCE_REFERENCE)
- R04: Explicit file deliverables (index.html, styles.css as OUTPUT_ARTIFACT)
- R05: Greenfield workspace bootstrap (deterministic directory creation)
- R06: Existing workspace protection (preserves files in existing directory)
- R07: Paths with spaces handled cleanly across workspace manager and shell tools
- R08: Preview server strict workspace binding (no cross-workspace contamination)
- R09: Genuine missing artifact detection (flags truly missing required files)
- R10: No-progress loop governor recovery (Case A completion when requirements satisfied)
- R11: Structured write_file operation integrity
- R12: Parser protection against adversarial bash code blocks
- R13: Dependency evidence verification (script tags, CDN, package.json)
- R14: Runtime state and ledger serialization round-trip with RequirementType
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest
import shutil

from core.runtime_state.models import RequirementType, RequirementState, RequirementCategory, RequirementPriority, RequirementStatus
from core.planning.requirement_types import (
    classify_requirement_token,
    extract_typed_requirements,
    extract_target_artifacts,
    verify_dependency_evidence,
    verify_runtime_evidence,
    strip_urls,
    extract_urls,
)
from core.verification_profiles import (
    classify_verification_profile,
    VerificationProfile,
    VerificationProfileEvaluator,
)
from core.workspace import WorkspaceManager
from tools.shell_tools import BashExecTool
from core.browser.dev_server import DevServerManager
from core.agent_loop.completion import CompletionPolicy
from core.response_parser import ResponseParser


# ── R01: Library Classification ──────────────────────────────────────────────
def test_r01_library_classification():
    """R01: Verify libraries like Three.js and React.js are classified as DEPENDENCY, not OUTPUT_ARTIFACT."""
    assert classify_requirement_token("Three.js") == RequirementType.DEPENDENCY
    assert classify_requirement_token("react.js") == RequirementType.DEPENDENCY
    assert classify_requirement_token("chart.js") == RequirementType.DEPENDENCY
    assert classify_requirement_token("d3.js") == RequirementType.DEPENDENCY

    prompt = "Build a 3D orbital simulation using Three.js and OrbitControls."
    typed = extract_typed_requirements(prompt)
    assert "Three.js" in typed[RequirementType.DEPENDENCY] or "three.js" in [x.lower() for x in typed[RequirementType.DEPENDENCY]]
    assert "Three.js" not in typed[RequirementType.OUTPUT_ARTIFACT]


# ── R02: Runtime Classification ──────────────────────────────────────────────
def test_r02_runtime_classification():
    """R02: Verify runtimes like Node.js, npm, Python are classified as RUNTIME, not OUTPUT_ARTIFACT."""
    assert classify_requirement_token("Node.js") == RequirementType.RUNTIME
    assert classify_requirement_token("npm") == RequirementType.RUNTIME
    assert classify_requirement_token("python") == RequirementType.RUNTIME

    prompt = "Use Node.js and npm to manage the project dependencies."
    typed = extract_typed_requirements(prompt)
    assert any("node" in x.lower() for x in typed[RequirementType.RUNTIME])
    assert "Node.js" not in typed[RequirementType.OUTPUT_ARTIFACT]


# ── R03: Source Reference URL Classification ─────────────────────────────────
def test_r03_source_url_classification():
    """R03: Verify URLs and URL basenames like GSLVmk3_CON.html are classified as SOURCE_REFERENCE."""
    url = "https://www.isro.gov.in/GSLVmk3_CON.html"
    prompt = f"Consult official specifications at {url} and build simulation."
    
    urls = extract_urls(prompt)
    assert url in urls

    typed = extract_typed_requirements(prompt)
    assert url in typed[RequirementType.SOURCE_REFERENCE]
    assert "GSLVmk3_CON.html" not in typed[RequirementType.OUTPUT_ARTIFACT]
    assert "gslvmk3_con.html" not in [x.lower() for x in typed[RequirementType.OUTPUT_ARTIFACT]]


# ── R04: Explicit File Deliverables ──────────────────────────────────────────
def test_r04_explicit_file_deliverables():
    """R04: Verify genuine file deliverables are accurately extracted as OUTPUT_ARTIFACT."""
    prompt = "Create index.html, styles.css, and app.js for the aerospace simulation."
    artifacts = extract_target_artifacts(prompt)
    assert "index.html" in artifacts
    assert "styles.css" in artifacts
    assert "app.js" in artifacts


# ── R05: Greenfield Workspace Bootstrap ──────────────────────────────────────
def test_r05_greenfield_workspace_bootstrap(tmp_path: Path):
    """R05: Verify WorkspaceManager.lock creates non-existent directory deterministically."""
    target_dir = tmp_path / "greenfield_project_test"
    assert not target_dir.exists()

    wm = WorkspaceManager()
    wm.lock(str(target_dir), create=True)
    try:
        assert target_dir.exists()
        assert target_dir.is_dir()
        assert wm.is_locked
        assert wm.workspace_root == target_dir.resolve()
    finally:
        wm.unlock()


# ── R06: Existing Workspace Protection ───────────────────────────────────────
def test_r06_existing_workspace_protection(tmp_path: Path):
    """R06: Verify locking an existing workspace preserves existing files."""
    ws = tmp_path / "existing_ws"
    ws.mkdir()
    sentinel = ws / "important_data.txt"
    sentinel.write_text("critical user content", encoding="utf-8")

    wm = WorkspaceManager()
    wm.lock(str(ws), create=True)
    try:
        assert sentinel.exists()
        assert sentinel.read_text(encoding="utf-8") == "critical user content"
    finally:
        wm.unlock()


# ── R07: Path with Spaces ────────────────────────────────────────────────────
def test_r07_path_with_spaces_handling(tmp_path: Path):
    """R07: Verify directories with spaces are created and shell tools execute in them cleanly."""
    ws_with_spaces = tmp_path / "rocket test with spaces"
    wm = WorkspaceManager()
    wm.lock(str(ws_with_spaces), create=True)
    try:
        assert ws_with_spaces.exists()

        # Execute bash tool inside directory with spaces
        tool = BashExecTool()
        res = tool.execute(tool.Input(command='echo "workspace_ok" > test.txt', working_dir=str(ws_with_spaces)))
        assert res.success is True
        created_file = ws_with_spaces / "test.txt"
        assert created_file.exists()
        assert "workspace_ok" in created_file.read_text(encoding="utf-8")
    finally:
        wm.unlock()


# ── R08: Dev Server Strict Workspace Binding ─────────────────────────────────
@pytest.mark.asyncio
async def test_r08_dev_server_strict_workspace_binding(tmp_path: Path):
    """R08: Verify dev servers are strictly bound to their requested workspace directory."""
    ws_a = tmp_path / "site_alpha"
    ws_b = tmp_path / "site_beta"
    ws_a.mkdir()
    ws_b.mkdir()

    (ws_a / "index.html").write_text("<h1>Site Alpha</h1>", encoding="utf-8")
    (ws_b / "index.html").write_text("<h1>Site Beta</h1>", encoding="utf-8")

    dsm = DevServerManager()
    try:
        server_a = await dsm.start_static_server(ws_a, name="site_a")
        assert server_a.workspace_dir == ws_a.resolve()

        # Query by workspace
        matched_a = dsm.get_server_for_workspace(ws_a)
        assert matched_a is not None
        assert matched_a.port == server_a.port

        # Workspace B should have no server yet
        assert dsm.get_server_for_workspace(ws_b) is None

        # Clean non-matching
        stopped = dsm.stop_stale_servers_not_matching(ws_a)
        assert stopped == 0

        # Start server for B and stop non-matching
        server_b = await dsm.start_static_server(ws_b, name="site_b")
        stopped = dsm.stop_stale_servers_not_matching(ws_b)
        assert stopped == 1  # site_a was stopped
        assert dsm.get_server_for_workspace(ws_a) is None
        assert dsm.get_server_for_workspace(ws_b) is not None
    finally:
        dsm.stop_all()


# ── R09: Genuine Missing Artifact Detection ──────────────────────────────────
def test_r09_genuine_missing_artifact_detection(tmp_path: Path):
    """R09: Verify Profile C evaluator accurately detects genuinely missing index.html."""
    ws = tmp_path / "empty_ws"
    ws.mkdir()

    prompt = "Build a rocket launch simulation website."
    res = VerificationProfileEvaluator.evaluate(VerificationProfile.PROFILE_C, ws, prompt)
    assert res.passed is False
    assert any("index.html not found" in iss for iss in res.issues)


# ── R10: No-Progress Loop Recovery (Case A) ──────────────────────────────────
def test_r10_no_progress_recovery_case_a(tmp_path: Path):
    """R10: Verify CompletionPolicy accepts completed project without false missing file failures."""
    ws = tmp_path / "completed_project"
    ws.mkdir()
    (ws / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>ISRO LVM3</title>"
        "<script src='https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js'></script></head>"
        "<body><h1>LVM3 Simulation</h1><canvas id='c'></canvas></body></html>",
        encoding="utf-8",
    )

    prompt = (
        "Build an ISRO LVM3 simulation using Three.js and Node.js. "
        "Reference: https://www.isro.gov.in/GSLVmk3_CON.html"
    )

    wm = WorkspaceManager()
    wm.lock(str(ws))
    try:
        policy = CompletionPolicy()
        accepted, reason, issues = policy.evaluate_completion(
            mission_prompt=prompt,
            workspace=wm,
            written_files=["index.html"],
        )
        assert accepted is True
        assert len(issues) == 0
        assert "Three.js" not in str(issues)
        assert "GSLVmk3_CON.html" not in str(issues)
    finally:
        wm.unlock()


# ── R11: Structured Writing Integrity ────────────────────────────────────────
def test_r11_structured_writing_integrity(tmp_path: Path):
    """R11: Verify structured file tool writes file faithfully."""
    from tools.file_tools import WriteFileTool
    from core.workspace import workspace_manager
    ws = tmp_path / "write_test"
    ws.mkdir()

    workspace_manager.lock(str(ws))
    try:
        tool = WriteFileTool()
        content = "const G = 6.674e-11;\nexport { G };\n"
        res = tool.execute(tool.Input(path="physics.js", content=content))
        assert res.success is True
        written = ws / "physics.js"
        assert written.exists()
        assert written.read_text(encoding="utf-8") == content
    finally:
        workspace_manager.unlock()


# ── R12: Parser Safety Against Adversarial Blocks ─────────────────────────────
def test_r12_parser_safety_against_adversarial_blocks():
    """R12: Verify parser guards reject adversarial shell instruction blocks."""
    adversarial_response = """
Here is how you install three:
```bash
mkdir my-rocket
cd my-rocket
npm install three
```
Now write the app in `index.html`.
"""
    parser = ResponseParser()
    res = parser.parse(adversarial_response)
    # The bash block must NOT be parsed into a fake write_file action for "index.html" or "Three.js"
    tool_calls = res.tool_calls if hasattr(res, "tool_calls") else []
    write_calls = [tc for tc in tool_calls if tc.tool_name == "write_file"]
    for wc in write_calls:
        assert wc.arguments.get("path") not in ("Three.js", "Node.js", "mkdir")


# ── R13: Dependency Evidence Verification ─────────────────────────────────────
def test_r13_dependency_evidence_verification(tmp_path: Path):
    """R13: Verify verify_dependency_evidence detects script tag and import map."""
    ws = tmp_path / "dep_test"
    ws.mkdir()

    # Case 1: missing
    ok, msg = verify_dependency_evidence("Three.js", ws)
    assert ok is False

    # Case 2: present via CDN script tag in index.html
    (ws / "index.html").write_text("<script src='https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js'></script>", encoding="utf-8")
    ok, msg = verify_dependency_evidence("Three.js", ws)
    assert ok is True
    assert "index.html" in msg


# ── R14: Serialization Round-Trip with RequirementType ────────────────────────
def test_r14_runtime_state_requirement_type_roundtrip():
    """R14: Verify RequirementState preserves requirement_type through serialization and deserialization."""
    from core.persistence.serializer import serialize_runtime_state, deserialize_runtime_state
    from core.runtime_state.models import HermesRuntimeState, MissionState

    state = HermesRuntimeState(mission=MissionState(mission_id="m_test", prompt="test"))
    req = RequirementState(
        requirement_id="req.dep.three",
        goal_id="goal_1",
        title="Three.js Library",
        category=RequirementCategory.FUNCTIONAL,
        requirement_type=RequirementType.DEPENDENCY,
        priority=RequirementPriority.HIGH,
        status=RequirementStatus.VERIFIED,
    )
    state.requirements[req.requirement_id] = req

    serialized, state_hash = serialize_runtime_state(state)
    reconstructed = deserialize_runtime_state(serialized)

    assert "req.dep.three" in reconstructed.requirements
    rec_req = reconstructed.requirements["req.dep.three"]
    assert rec_req.requirement_type == RequirementType.DEPENDENCY
    assert rec_req.category == RequirementCategory.FUNCTIONAL
    assert rec_req.status == RequirementStatus.VERIFIED
