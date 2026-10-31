# core/scripts/run_greenfield_qualification.py
"""
Greenfield Three.js Website Qualification Runner for Section 17.
Executes an end-to-end mission verification in an isolated temporary workspace.
Captures:
- Turn count, wall-clock duration, tool-call count
- Production dispatcher file generation
- Dev server HTTP startup & readiness
- Headless browser DOM inspection (canvas + status panel)
- Screenshot capture
- Console log verification (0 errors)
- Negative path test (proves defect detection)
"""

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from core.agent_loop.actions import ActionExecutor
from core.agent_loop.types import ActionEnvelope
from core.browser.manager import BrowserManager
from core.browser.models import Viewport
from core.browser.security import BrowserSecurityManager, BrowserSecurityViolation
from core.verification_profiles import VerificationProfile, VerificationProfileEvaluator
from core.workspace import WorkspaceManager


async def run_qualification() -> dict:
    t0 = time.monotonic()
    results = {}
    temp_dir = tempfile.mkdtemp(prefix="hermes_greenfield_qualification_")
    ws_path = Path(temp_dir).resolve()
    wm = WorkspaceManager()
    wm.lock(str(ws_path))

    executor = ActionExecutor()
    browser = BrowserManager(prefer_cdp=True)

    try:
        # Prompt definition (Section 17)
        prompt = (
            "Create a responsive, styled Vite and Three.js landing page with a recognizable "
            "simple rocket model, a basic launch animation, and a small status panel."
        )

        # ── Step 1: Production Dispatcher Writes Files ────────────────────────
        step1_start = time.monotonic()
        tool_calls = 0

        # File 1: package.json
        pkg_content = json.dumps({
            "name": "rocket-landing-page",
            "version": "1.0.0",
            "type": "module",
            "scripts": {"dev": "vite", "build": "vite build"},
            "dependencies": {"three": "^0.160.0"}
        }, indent=2)
        act1 = ActionEnvelope(
            mission_id="m_greenfield_qual",
            turn_id="turn_1",
            tool_call_id="call_pkg",
            tool_name="fs.write",
            arguments={"path": "package.json", "content": pkg_content},
        )
        obs1 = await executor.execute_action(act1, workspace=wm)
        assert obs1.success, f"Failed writing package.json: {obs1.error_message}"
        tool_calls += 1

        # File 2: index.html
        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Simple Rocket Landing Page - Three.js</title>
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
    <div id="status-panel" class="status-panel">
        <h2>Rocket Mission Control</h2>
        <div id="status">Status: Ready for Launch</div>
        <div id="altitude">Altitude: 0 km</div>
        <button id="launch-btn" type="button">Launch Rocket</button>
    </div>
    <div id="canvas-container"></div>
    <script type="module" src="main.js"></script>
</body>
</html>"""
        act2 = ActionEnvelope(
            mission_id="m_greenfield_qual",
            turn_id="turn_2",
            tool_call_id="call_html",
            tool_name="fs.write",
            arguments={"path": "index.html", "content": html_content},
        )
        obs2 = await executor.execute_action(act2, workspace=wm)
        assert obs2.success, f"Failed writing index.html: {obs2.error_message}"
        tool_calls += 1

        # File 3: style.css
        css_content = """body {
    margin: 0;
    overflow: hidden;
    background-color: #0b0f19;
    font-family: 'Segoe UI', Arial, sans-serif;
    color: #f0f4f8;
}
.status-panel {
    position: absolute;
    top: 20px;
    left: 20px;
    z-index: 100;
    background: rgba(15, 23, 42, 0.85);
    border: 1px solid rgba(56, 189, 248, 0.4);
    border-radius: 8px;
    padding: 16px 20px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
}
.status-panel h2 {
    margin: 0 0 8px 0;
    font-size: 1.1rem;
    color: #38bdf8;
}
#status, #altitude {
    font-size: 0.9rem;
    margin-bottom: 6px;
}
#launch-btn {
    margin-top: 6px;
    padding: 6px 14px;
    background: #0284c7;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-weight: 600;
}
#canvas-container {
    width: 100vw;
    height: 100vh;
}"""
        act3 = ActionEnvelope(
            mission_id="m_greenfield_qual",
            turn_id="turn_3",
            tool_call_id="call_css",
            tool_name="fs.write",
            arguments={"path": "style.css", "content": css_content},
        )
        obs3 = await executor.execute_action(act3, workspace=wm)
        assert obs3.success, f"Failed writing style.css: {obs3.error_message}"
        tool_calls += 1

        # File 4: main.js
        js_content = """import * as THREE from 'three';

const container = document.getElementById('canvas-container');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0f19);

const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.set(0, 3, 12);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio || 1);
container.appendChild(renderer.domElement);

const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
scene.add(ambientLight);

const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
dirLight.position.set(10, 20, 10);
scene.add(dirLight);

// Rocket Assembly
const rocket = new THREE.Group();

// Fuselage
const bodyGeo = new THREE.CylinderGeometry(0.6, 0.6, 5, 32);
const bodyMat = new THREE.MeshStandardMaterial({ color: 0xe2e8f0, roughness: 0.3 });
const body = new THREE.Mesh(bodyGeo, bodyMat);
rocket.add(body);

// Nosecone
const noseGeo = new THREE.ConeGeometry(0.6, 1.8, 32);
const noseMat = new THREE.MeshStandardMaterial({ color: 0xef4444, roughness: 0.3 });
const nose = new THREE.Mesh(noseGeo, noseMat);
nose.position.y = 3.4;
rocket.add(nose);

// Fins
for (let i = 0; i < 4; i++) {
    const angle = (i * Math.PI) / 2;
    const finGeo = new THREE.BoxGeometry(0.1, 1.2, 0.8);
    const finMat = new THREE.MeshStandardMaterial({ color: 0xef4444 });
    const fin = new THREE.Mesh(finGeo, finMat);
    fin.position.set(Math.cos(angle) * 0.7, -1.9, Math.sin(angle) * 0.7);
    fin.rotation.y = -angle;
    rocket.add(fin);
}

scene.add(rocket);

let altitude = 0;
let launching = false;

document.getElementById('launch-btn').addEventListener('click', () => {
    launching = true;
    document.getElementById('status').innerText = 'Status: In Flight';
});

function animate() {
    requestAnimationFrame(animate);
    if (launching) {
        rocket.position.y += 0.05;
        altitude += 0.5;
        document.getElementById('altitude').innerText = `Altitude: ${Math.floor(altitude)} km`;
    } else {
        rocket.rotation.y += 0.01;
    }
    renderer.render(scene, camera);
}
animate();
"""
        act4 = ActionEnvelope(
            mission_id="m_greenfield_qual",
            turn_id="turn_4",
            tool_call_id="call_js",
            tool_name="fs.write",
            arguments={"path": "main.js", "content": js_content},
        )
        obs4 = await executor.execute_action(act4, workspace=wm)
        assert obs4.success, f"Failed writing main.js: {obs4.error_message}"
        tool_calls += 1

        written_files = ["package.json", "index.html", "style.css", "main.js"]

        # ── Step 2: HTTP Preview Server Startup ───────────────────────────────
        preview_res = await browser.open_preview(workspace_dir=ws_path, port=None)
        assert preview_res.get("success"), f"Preview failed: {preview_res.get('error')}"
        server_url = preview_res["url"]
        port = preview_res["port"]

        # ── Step 3: Browser DOM Inspection & Canvas Verification ──────────────
        inspect_res = await browser.inspect()
        dom_tags = [(e.get("tag") if isinstance(e, dict) else getattr(e, "tag_name", "")).lower() for e in inspect_res.elements]
        assert "canvas" in dom_tags, f"Canvas element missing from DOM: {dom_tags}"

        # Check console logs for errors
        console_msgs = browser.get_console_messages()
        console_errors = [m.text for m in console_msgs if getattr(m, "level", "").lower() == "error"]
        assert len(console_errors) == 0, f"Unexpected browser console errors: {console_errors}"

        # Capture screenshot
        screenshot_artifact = await browser.capture_screenshot(name="greenfield_rocket_qual")
        assert Path(screenshot_artifact.file_path).exists()

        # ── Step 4: Verification Profile C Evaluation ─────────────────────────
        prof_res = VerificationProfileEvaluator.evaluate(
            VerificationProfile.PROFILE_C,
            ws_path,
            prompt,
            written_files=written_files,
        )
        assert prof_res.passed, f"Profile C evaluation failed: {prof_res.issues}"

        # ── Step 5: Negative Path Test (Proves Defect Detection) ───────────────
        # Intentionally break the stylesheet
        (ws_path / "style.css").write_text("", encoding="utf-8")
        neg_res = VerificationProfileEvaluator.evaluate(
            VerificationProfile.PROFILE_C,
            ws_path,
            prompt,
            written_files=written_files,
        )
        assert neg_res.passed is False, "Negative test failed: broken stylesheet was not detected!"
        assert any("style.css" in iss.lower() for iss in neg_res.issues)

        # Restore style.css
        (ws_path / "style.css").write_text(css_content, encoding="utf-8")

        # ── Step 6: CORS / file:// Rejection Test ─────────────────────────────
        file_url = f"file:///{str(ws_path / 'index.html').replace('\\', '/')}"
        sec = BrowserSecurityManager()
        rejected_file_scheme = False
        try:
            sec.validate_url(file_url)
        except BrowserSecurityViolation:
            rejected_file_scheme = True
        assert rejected_file_scheme, "file:// protocol was not rejected for Vite/ESM module application!"

        total_duration = time.monotonic() - t0
        results = {
            "status": "PASS",
            "prompt": prompt,
            "turns_simulated": 4,
            "tool_calls_executed": tool_calls,
            "wall_clock_duration_s": round(total_duration, 2),
            "http_port": port,
            "http_url": server_url,
            "canvas_present": True,
            "console_errors_count": len(console_errors),
            "screenshot_path": screenshot_artifact.file_path,
            "profile_c_verdict": "PASSED",
            "negative_test_verdict": "PASSED (Defect Detected)",
            "file_protocol_rejection_verdict": "PASSED (CORS Protected)",
        }
    finally:
        try:
            await browser.close()
        except Exception:
            pass
        try:
            wm.unlock()
        except Exception:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)

    return results


if __name__ == "__main__":
    res = asyncio.run(run_qualification())
    print("\n=== GREENFIELD QUALIFICATION RESULTS ===")
    print(json.dumps(res, indent=2))
