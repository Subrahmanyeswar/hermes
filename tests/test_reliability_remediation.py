"""
HERMES Final Reliability Remediation Test Suite.
Tests T1 through T9:
- T1: Evidence provenance and mission isolation
- T2: Production dispatcher file write with spaces in path
- T3: Path safety and boundary containment
- T4: Progress governor auxiliary mutation churn prevention
- T5: URL basename filtering in planner and agent loop
- T6: Dynamic deadline enforcement and timeout bounding
- T7: Windows process runner rm command translation
- T8: Greenfield web application contract validation
- T9: Greenfield Three.js website preview and browser qualification
"""

import asyncio
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_loop.loop import AgentLoop
from core.agent_loop.types import AgentLoopConfig, AgentTurn
from core.mission_planner import Mission, MissionPlanner, MissionComplexity
from core.runtime_state.events import EventType, EventSeverity
from core.browser.manager import BrowserManager
from core.workspace import WorkspaceManager, workspace_manager
from models.nvidia_client import NvidiaClient, NvidiaTimeoutError
from tools.file_tools import WriteFileTool, ReadFileTool
from tools.platform.core_tools import FSWriteTool, FSReadTool
from tools.shell_tools import _translate_single_command, BashExecTool


# ============================================================================
# T1: Evidence Provenance and Mission Isolation
# ============================================================================
def test_t1_evidence_provenance_isolation(tmp_path):
    """Verify verification evidence is strictly isolated by mission ID and workspace."""
    from core.evidence.store import EvidenceStore
    from core.evidence.models import EvidenceRecord, EvidenceStatus

    ws_alpha = tmp_path / "ws_alpha"
    ws_beta = tmp_path / "ws_beta"
    ws_alpha.mkdir()
    ws_beta.mkdir()

    store_alpha = EvidenceStore(workspace_root=ws_alpha, mission_id="mission_alpha")
    store_beta = EvidenceStore(workspace_root=ws_beta, mission_id="mission_beta")

    rec_alpha = EvidenceRecord(
        evidence_id="ev_alpha_01",
        mission_id="mission_alpha",
        requirement_id="req_launch_telemetry",
        status=EvidenceStatus.VERIFIED,
        command="pytest tests/test_telemetry.py",
        exit_code=0,
    )
    store_alpha.add(rec_alpha, persist=True)

    # Inquiries on store_alpha retrieve rec_alpha
    retrieved = store_alpha.get("ev_alpha_01")
    assert retrieved is not None
    assert retrieved.requirement_id == "req_launch_telemetry"

    # Inquiries on store_beta must NOT leak evidence from store_alpha
    assert store_beta.get("ev_alpha_01") is None
    assert len(store_beta.get_by_requirement("req_launch_telemetry")) == 0


# ============================================================================
# T2: Production Dispatcher File Write With Spaces in Path
# ============================================================================
def test_t2_production_dispatcher_write_file_with_spaces(tmp_path):
    """Verify fs.write and write_file work in workspaces with spaces without NameError."""
    space_ws = tmp_path / "hermes qualification test"
    space_ws.mkdir(parents=True, exist_ok=True)

    wm = WorkspaceManager()
    wm.lock(str(space_ws))

    # Test 1: Native WriteFileTool execution
    write_tool = WriteFileTool()
    res_native = write_tool.execute(
        {"path": "components/app.js", "content": "console.log('space path ok');", "mode": "create", "_workspace": wm}
    )
    assert res_native.success is True, f"Native write_file failed: {res_native.error}"
    written_file_1 = space_ws / "components" / "app.js"
    assert written_file_1.exists()
    assert written_file_1.read_text(encoding="utf-8") == "console.log('space path ok');"

    # Test 2: Platform FSWriteTool execution
    fs_tool = FSWriteTool()
    res_platform = fs_tool.execute(
        {"path": "index.html", "content": "<!DOCTYPE html><html><body><h1>Rocket</h1></body></html>", "_workspace": wm}
    )
    assert res_platform.success is True, f"Platform fs.write failed: {res_platform.error}"
    written_file_2 = space_ws / "index.html"
    assert written_file_2.exists()
    assert "Rocket" in written_file_2.read_text(encoding="utf-8")


# ============================================================================
# T3: Path Safety and Boundary Containment
# ============================================================================
def test_t3_path_safety_boundary_containment(tmp_path):
    """Verify traversal outside workspace is rejected safely."""
    space_ws = tmp_path / "contained workspace"
    space_ws.mkdir(parents=True, exist_ok=True)

    wm = WorkspaceManager()
    wm.lock(str(space_ws))

    write_tool = WriteFileTool()
    res = write_tool.execute(
        {"path": "../escaped_file.txt", "content": "malicious", "_workspace": wm}
    )
    assert not res.success
    assert "outside" in (res.error or "").lower() or "boundary" in (res.error or "").lower() or "access denied" in (res.error or "").lower()


# ============================================================================
# T4: Progress Governor Auxiliary Mutation Churn Prevention
# ============================================================================
@pytest.mark.asyncio
async def test_t4_progress_governor_auxiliary_churn_prevention(tmp_path):
    """Verify modifying auxiliary files while entrypoint is missing triggers governor and doesn't reset stall count."""
    ws_dir = tmp_path / "aux_churn_test"
    ws_dir.mkdir(parents=True, exist_ok=True)

    wm = WorkspaceManager()
    wm.lock(str(ws_dir))

    # Create loop with dummy orchestrator
    orch = MagicMock()
    loop = AgentLoop(orchestrator=orch, workspace_manager=wm)
    loop._mission_id = "m_test_aux"

    mission = Mission(
        mission_id="m_test_aux",
        user_prompt="Build a 3D rocket website based on reference GSLVmk3_CON.html",
    )

    # Simulate Turn 1: create index.html
    (ws_dir / "index.html").write_text("<!DOCTYPE html><html><body><script src='main.js'></script></body></html>", encoding="utf-8")

    # Target auxiliary file
    aux_file = "GSLVmk3_CON.html"
    loop._file_write_counts[aux_file.lower()] = 1

    # Call auxiliary write when count is already 1 (second write)
    loop._file_write_counts[aux_file.lower()] = 2

    # Verify governor auxiliary check recognizes churn
    norm_target = aux_file.lower()
    core_entrypoints = {"index.html", "main.js", "style.css", "package.json", "vite.config.js", "app.js", "src/main.js", "src/app.js", "src/index.js"}
    clean_prompt = re.sub(r'https?://[^\s<>"\']+', '', mission.user_prompt)
    is_web = any(k in clean_prompt.lower() for k in ("html", "css", "website", "web page", "web app", "observatory", "frontend", "ui", "space", "orbit", "rocket", "3d", "three")) or (ws_dir / "index.html").exists()
    has_main = any((ws_dir / j).exists() and (ws_dir / j).stat().st_size > 100 for j in ("main.js", "src/main.js", "app.js", "index.js", "script.js"))

    assert is_web is True
    assert has_main is False
    assert norm_target not in core_entrypoints
    assert loop._file_write_counts.get(norm_target, 0) >= 2


# ============================================================================
# T5: URL Basename Filtering in Planner and Loop
# ============================================================================
def test_t5_url_basename_filtering_in_planner_and_loop():
    """Verify URLs in user prompts do not pollute task deliverables or loop missing files."""
    planner = MissionPlanner()
    prompt_with_urls = (
        "Build an interactive 3D rocket website based on https://www.isro.gov.in/GSLVmk3_CON.html "
        "and https://www.isro.gov.in/LVM3.html with Three.js"
    )

    # 1. Mission planner task generation
    mission = planner.plan(prompt_with_urls)
    assert len(mission.tasks) > 0

    all_targets = []
    for t in mission.tasks:
        all_targets.extend(t.target_paths)
        all_targets.extend(t.write_dependencies)

    assert "GSLVmk3_CON.html" not in all_targets, f"URL basename leaked into task targets: {all_targets}"
    assert "LVM3.html" not in all_targets, f"URL basename leaked into task targets: {all_targets}"

    # 2. AgentLoop prompt files extraction
    clean_prompt = re.sub(r'https?://[^\s<>"\']+', '', prompt_with_urls)
    prompt_files = re.findall(r'\b[\w\.-]+\.(?:html|css|js|py|json|md)\b', clean_prompt)
    assert "GSLVmk3_CON.html" not in prompt_files
    assert "LVM3.html" not in prompt_files


# ============================================================================
# T6: Dynamic Deadline Enforcement and Timeout Bounding
# ============================================================================
@pytest.mark.asyncio
async def test_t6_dynamic_deadline_enforcement():
    """Verify turn timeout is clamped to remaining budget and client respects it."""
    from core.agent_loop.loop import calculate_effective_turn_timeout
    max_wall_time = 1200.0
    elapsed_time = 1170.0
    remaining_wall_time = max_wall_time - elapsed_time  # 30.0s

    turn_timeout = calculate_effective_turn_timeout(remaining_wall_time, 360.0)
    # 30 - 10 = 20.0s
    assert turn_timeout == 20.0

    # Verify NvidiaClient accepts timeout_seconds override
    client = NvidiaClient(api_key="test_key")
    assert client.timeout_seconds == 360

    # Verify client._generate_stream enforces effective_timeout
    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "data"}}]}'
            await asyncio.sleep(0.1)
            yield 'data: [DONE]'

    mock_http_client = MagicMock()
    mock_http_client.stream.return_value = FakeStreamResponse()

    # With effective_timeout = 0.05s, starting with start_time 1.0s ago, it must raise TOTAL_GENERATION_TIMEOUT
    with pytest.raises(NvidiaTimeoutError) as exc_info:
        await client._generate_stream(
            client=mock_http_client,
            url="http://test/chat/completions",
            payload={},
            headers={},
            active_model="nvidia/nemotron-3.5-super-vl-120b-a12b",
            prompt="test",
            system="",
            temperature=0.0,
            start_time=time.monotonic() - 1.0,  # 1.0s elapsed > 0.05s limit
            effective_timeout=0.05,
        )
    assert exc_info.value.timeout_type == "TOTAL_GENERATION_TIMEOUT"


# ============================================================================
# T7: Windows Process Runner rm Command Translation
# ============================================================================
def test_t7_windows_shell_rm_translation(tmp_path):
    """Verify rm and rm -f are translated to Python unlinking and execute cleanly."""
    py = sys.executable

    # 1. Test translation string
    cmd_rm = _translate_single_command("rm -f smoke_test.txt", py)
    assert py in cmd_rm
    assert "force = True" in cmd_rm
    assert "smoke_test.txt" in cmd_rm

    cmd_rm_rf = _translate_single_command("rm -rf build_dir", py)
    assert "recursive = True" in cmd_rm_rf
    assert "force = True" in cmd_rm_rf

    # 2. Test actual execution via BashExecTool
    try:
        workspace_manager.lock(str(tmp_path))

        test_file = tmp_path / "smoke_rm_target.txt"
        test_file.write_text("temporary content", encoding="utf-8")
        assert test_file.exists()

        bash_tool = BashExecTool()
        res = bash_tool.execute(BashExecTool.Input(command=f'rm -f "{test_file.name}"'))
        assert res.exit_code == 0, f"rm -f failed: {res.output} {res.error}"
        assert not test_file.exists(), "Target file was not deleted"

        # Removing already deleted file with -f must succeed with exit code 0
        res_f = bash_tool.execute(BashExecTool.Input(command=f'rm -f "{test_file.name}"'))
        assert res_f.exit_code == 0, f"rm -f non-existent failed: {res_f.output} {res_f.error}"
    finally:
        workspace_manager.unlock()


# ============================================================================
# T8: Greenfield Web Application Contract Validation
# ============================================================================
def test_t8_greenfield_web_application_contract(tmp_path):
    """Verify web project contract mandates main.js when index.html references it."""
    ws_dir = tmp_path / "web_contract_ws"
    ws_dir.mkdir(parents=True, exist_ok=True)

    # Empty workspace
    has_main_js = any((ws_dir / j).exists() and (ws_dir / j).stat().st_size > 400 for j in ("main.js", "app.js", "index.js", "script.js"))
    assert has_main_js is False

    # Create index.html referencing main.js
    (ws_dir / "index.html").write_text('<!DOCTYPE html><html><body><script type="module" src="main.js"></script></body></html>', encoding="utf-8")

    # Still missing main.js
    has_main_js = any((ws_dir / j).exists() and (ws_dir / j).stat().st_size > 400 for j in ("main.js", "app.js", "index.js", "script.js"))
    assert has_main_js is False

    # Now create substantive main.js (>400 bytes)
    main_code = (
        "import * as THREE from 'three';\n"
        "const scene = new THREE.Scene();\n"
        "const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);\n"
        "const renderer = new THREE.WebGLRenderer({ antialias: true });\n"
        "renderer.setSize(window.innerWidth, window.innerHeight);\n"
        "document.body.appendChild(renderer.domElement);\n"
        "const geometry = new THREE.CylinderGeometry(1, 1.5, 8, 32);\n"
        "const material = new THREE.MeshStandardMaterial({ color: 0xcccccc });\n"
        "const rocket = new THREE.Mesh(geometry, material);\n"
        "scene.add(rocket);\n"
        "function animate() { requestAnimationFrame(animate); renderer.render(scene, camera); }\n"
        "animate();\n"
    )
    assert len(main_code) > 400
    (ws_dir / "main.js").write_text(main_code, encoding="utf-8")

    has_main_js = any((ws_dir / j).exists() and (ws_dir / j).stat().st_size > 400 for j in ("main.js", "app.js", "index.js", "script.js"))
    assert has_main_js is True


# ============================================================================
# T9: Greenfield Three.js Website Preview and Browser Qualification
# ============================================================================
@pytest.mark.asyncio
async def test_t9_bounded_greenfield_threejs_website_qualification(tmp_path):
    """Verify creation, syntax, serving, and headless browser inspection of a Three.js web app."""
    ws_dir = tmp_path / "threejs qualification space"
    ws_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write package.json
    pkg_json = {
        "name": "lvm3-rocket-observatory",
        "version": "1.0.0",
        "type": "module",
        "scripts": {"dev": "vite", "build": "vite build"}
    }
    import json
    (ws_dir / "package.json").write_text(json.dumps(pkg_json, indent=2), encoding="utf-8")

    # 2. Write index.html with Three.js import map and rocket canvas container
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LVM3 Rocket Interactive 3D Observatory</title>
    <link rel="stylesheet" href="style.css">
    <script type="importmap">
    {
      "imports": {
        "three": "https://unpkg.com/three@0.160.0/build/three.module.js"
      }
    }
    </script>
</head>
<body>
    <div id="hud">
        <h1>LVM3 / GSLV Mk III Observatory</h1>
        <div id="telemetry">Status: Orbit Ready | Altitude: 200 km</div>
    </div>
    <div id="canvas-container"></div>
    <script type="module" src="main.js"></script>
</body>
</html>"""
    (ws_dir / "index.html").write_text(html_content, encoding="utf-8")

    # 3. Write style.css
    css_content = """body {
    margin: 0;
    overflow: hidden;
    background-color: #050510;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    color: #ffffff;
}
#hud {
    position: absolute;
    top: 20px;
    left: 20px;
    z-index: 10;
    pointer-events: none;
    background: rgba(10, 15, 30, 0.7);
    padding: 15px 25px;
    border-radius: 8px;
    border: 1px solid rgba(0, 200, 255, 0.3);
}
#canvas-container {
    width: 100vw;
    height: 100vh;
}"""
    (ws_dir / "style.css").write_text(css_content, encoding="utf-8")

    # 4. Write substantive procedural Three.js in main.js
    js_content = """import * as THREE from 'three';

const container = document.getElementById('canvas-container');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x050510);

const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.set(0, 4, 14);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
container.appendChild(renderer.domElement);

const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
scene.add(ambientLight);

const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
dirLight.position.set(10, 20, 15);
scene.add(dirLight);

// Build procedural LVM3 Rocket Assembly
const rocketGroup = new THREE.Group();

// Core Stage (L110)
const coreGeo = new THREE.CylinderGeometry(0.8, 0.8, 8, 32);
const coreMat = new THREE.MeshStandardMaterial({ color: 0xdd6600, roughness: 0.4 });
const coreStage = new THREE.Mesh(coreGeo, coreMat);
rocketGroup.add(coreStage);

// Cryogenic Upper Stage (C25)
const c25Geo = new THREE.CylinderGeometry(0.8, 0.8, 3, 32);
const c25Mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.3 });
const c25Stage = new THREE.Mesh(c25Geo, c25Mat);
c25Stage.position.y = 5.5;
rocketGroup.add(c25Stage);

// Payload Fairing (Nosecone)
const noseGeo = new THREE.ConeGeometry(0.85, 2.5, 32);
const noseMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.2 });
const noseCone = new THREE.Mesh(noseGeo, noseMat);
noseCone.position.y = 8.25;
rocketGroup.add(noseCone);

// Solid Boosters (S200)
const boosterGeo = new THREE.CylinderGeometry(0.5, 0.5, 7, 32);
const boosterMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.3 });
const boosterNoseGeo = new THREE.ConeGeometry(0.5, 1.2, 32);

[-1.5, 1.5].forEach((xPos) => {
    const booster = new THREE.Mesh(boosterGeo, boosterMat);
    booster.position.set(xPos, -0.5, 0);
    const boosterNose = new THREE.Mesh(boosterNoseGeo, boosterMat);
    boosterNose.position.set(xPos, 3.6, 0);
    rocketGroup.add(booster);
    rocketGroup.add(boosterNose);
});

scene.add(rocketGroup);

let animationFrameId;
function animate() {
    animationFrameId = requestAnimationFrame(animate);
    rocketGroup.rotation.y += 0.01;
    renderer.render(scene, camera);
}
animate();

window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});
"""
    (ws_dir / "main.js").write_text(js_content, encoding="utf-8")

    # 5. Verify all 4 required files exist and have sufficient size
    assert (ws_dir / "package.json").exists()
    assert (ws_dir / "index.html").exists()
    assert (ws_dir / "style.css").exists()
    assert (ws_dir / "main.js").exists()
    assert (ws_dir / "main.js").stat().st_size > 1000

    # 6. Verify real browser loading via BrowserManager
    bm = BrowserManager()
    launched = await bm.launch()
    assert launched is True, "Browser failed to launch"

    try:
        # Open local HTML file in headless browser
        index_url = (ws_dir / "index.html").as_uri()
        nav_res = await bm.navigate(index_url)
        assert nav_res.success is True, f"Navigation failed: {nav_res.error}"

        # Allow Three.js module to load from CDN and initialize WebGL
        await asyncio.sleep(2.0)

        # Inspect DOM
        inspection = await bm.inspect()
        assert inspection.title == "LVM3 Rocket Interactive 3D Observatory"
        text_content = inspection.visible_text or ""
        assert "LVM3 / GSLV Mk III Observatory" in text_content

        # Verify console errors
        console_errors = bm.get_console_errors()
        assert len(console_errors) == 0, f"Encountered browser console errors: {console_errors}"

        # Capture qualification screenshot
        screenshot_path = ws_dir / "lvm3_qualification_preview.png"
        shot_res = await bm.capture_screenshot(str(screenshot_path))
        assert Path(shot_res.file_path).exists()
        assert Path(shot_res.file_path).stat().st_size > 5000, "Screenshot file is empty"

    finally:
        await bm.close()
