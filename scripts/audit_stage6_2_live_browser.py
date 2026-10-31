"""
HERMES Stage 6.2 - Task Goal Fulfillment and Evidence Integrity Live Browser Acceptance Audit.

Executes live end-to-end browser-submitted read-only inspection mission against the authoritative
Python runtime and live configured model (T1: NVIDIA NIM z-ai/glm-5.3-flash):

1. Calculates cryptographic SHA-256 manifests of all workspace files before and after mission.
2. Submits prompt in browser via CDP:
   "Inspect README.md and report its primary heading and description without modifying any files."
3. Awaits live model execution to COMPLETED terminal status.
4. Verifies that the delivered final_output directly states:
   - Primary heading: "Project Antigravity Architecture"
   - Description: "This system provides autonomous agent engineering with strict safety gates."
5. Verifies zero workspace mutations (SHA-256 match) and 0 diff additions/deletions.
6. Executes child verification subprocess recording canonical python executable:
   C:\\Users\\SUBBU\\Downloads\\hermes\\venv\\Scripts\\python.exe
7. Captures screenshots into artifacts/stage6_2/ and saves browser_acceptance_evidence.json.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
import uvicorn
import websockets

from core.event_bus import event_bus
from core.server.app import create_app
from core.server.diff_service import clear_file_baselines, record_file_baseline
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import workspace_manager

ARTIFACTS_DIR = ROOT / "artifacts" / "stage6_2"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9234
SERVER_PORT = 8765
CANONICAL_PYTHON = r"C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe"


def compute_sha256_manifest(workspace_root: Path) -> dict[str, str]:
    manifest = {}
    for p in workspace_root.rglob("*"):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(workspace_root).parts):
            rel = p.relative_to(workspace_root).as_posix()
            manifest[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return manifest


async def cdp_call(ws, method: str, params: dict = None, timeout: float = 12.0):
    """Send CDP command over WebSocket and await result."""
    msg_id = int(time.time() * 1000) % 1000000
    payload = {"id": msg_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(payload))

    start = time.time()
    while time.time() - start < timeout:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data.get("result", {})
        except asyncio.TimeoutError:
            pass
        except Exception:
            break
    return {}


async def capture_screenshot(ws, output_path: Path):
    res = await cdp_call(ws, "Page.captureScreenshot", {"format": "png", "quality": 95})
    b64_data = res.get("data", "")
    if b64_data:
        output_path.write_bytes(base64.b64decode(b64_data))
        print(f"[+] Screenshot captured: {output_path.name}")
        return True
    return False


async def submit_prompt_in_browser(ws, prompt_text: str):
    """Type prompt in React Composer and click Send button."""
    js_type = f"""
    (() => {{
        const ta = document.querySelector('textarea');
        if (!ta) return {{ success: false, reason: 'no textarea' }};
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
        setter.call(ta, {json.dumps(prompt_text)});
        ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
        ta.dispatchEvent(new Event('change', {{ bubbles: true }}));
        const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Send'));
        if (!btn) return {{ success: false, reason: 'no send button' }};
        if (btn.disabled) return {{ success: false, reason: 'send button disabled' }};
        btn.click();
        return {{ success: true }};
    }})()
    """
    res = await cdp_call(ws, "Runtime.evaluate", {"expression": js_type, "returnByValue": True})
    return res.get("result", {}).get("value", {})


async def run_stage6_2_audit():
    print(f"[*] Starting Stage 6.2 Goal Fulfillment and Evidence Integrity Audit on port {SERVER_PORT}...")

    evidence = {
        "stage": "6.2",
        "timestamp": time.time(),
        "model_configured": "z-ai/glm-5.3-flash (NVIDIA NIM)",
        "canonical_python": CANONICAL_PYTHON,
        "scenarios": {},
        "screenshots": {},
        "manifests": {},
    }

    # Setup isolated test workspace
    ws_dir = (ROOT / "data" / "ws_stage6_2_readonly").resolve()
    if ws_dir.exists():
        shutil.rmtree(ws_dir, ignore_errors=True)
    ws_dir.mkdir(parents=True, exist_ok=True)

    readme_target = ws_dir / "README.md"
    readme_text = (
        "# Project Antigravity Architecture\n\n"
        "This system provides autonomous agent engineering with strict safety gates.\n"
    )
    readme_target.write_text(readme_text, encoding="utf-8")
    workspace_manager.lock(ws_dir)
    clear_file_baselines()
    record_file_baseline(ws_dir, "README.md", readme_text)

    # Calculate SHA-256 manifest before
    sha_manifest_before = compute_sha256_manifest(ws_dir)
    evidence["manifests"]["sha256_before"] = sha_manifest_before
    print(f"[+] Initial workspace SHA-256: README.md = {sha_manifest_before.get('README.md')}")

    # Launch server
    adapter = RuntimeAdapter(event_bus=event_bus, workspace_manager=workspace_manager)
    app = create_app(adapter=adapter)
    config = uvicorn.Config(app=app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    # Wait for server
    for _ in range(30):
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"http://127.0.0.1:{SERVER_PORT}/api/health")
                if res.status_code == 200:
                    print("[+] FastAPI Runtime Bridge ready.")
                    break
        except Exception:
            await asyncio.sleep(0.5)

    # Launch Chrome headless with CDP
    chrome_proc = None
    try:
        user_data_dir = ROOT / "data" / "chrome_stage6_2_profile"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        chrome_cmd = [
            CHROME_PATH,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={user_data_dir}",
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"http://127.0.0.1:{SERVER_PORT}",
        ]
        chrome_proc = subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[+] Chrome headless launched on CDP port {CDP_PORT}")

        # Connect to CDP Page Target
        ws_url = None
        for _ in range(30):
            try:
                async with httpx.AsyncClient() as client:
                    v_res = await client.get(f"http://127.0.0.1:{CDP_PORT}/json")
                    if v_res.status_code == 200:
                        pages = v_res.json()
                        page = next((p for p in pages if p.get("type") == "page" and "webSocketDebuggerUrl" in p), None)
                        if page:
                            ws_url = page["webSocketDebuggerUrl"]
                            break
            except Exception:
                pass
            await asyncio.sleep(0.5)

        assert ws_url, "Could not obtain Chrome Page WebSocket Debugger URL"
        print(f"[+] Connected to Chrome CDP Page: {ws_url}")

        async with websockets.connect(ws_url) as ws:
            await cdp_call(ws, "Page.enable")
            await cdp_call(ws, "Runtime.enable")
            await cdp_call(ws, "Emulation.setDeviceMetricsOverride", {
                "width": 1440,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            })

            # Navigate to GUI
            await cdp_call(ws, "Page.navigate", {"url": f"http://127.0.0.1:{SERVER_PORT}"})
            await asyncio.sleep(2.0)

            # Submit prompt in browser
            ro_prompt = "Inspect README.md and report its primary heading and description without modifying any files."
            sub_res = await submit_prompt_in_browser(ws, ro_prompt)
            print("[+] Submitted prompt via browser Composer:", sub_res)

            # Capture prompt submitted screenshot
            ss_composer = ARTIFACTS_DIR / "01_browser_prompt_submitted.png"
            await capture_screenshot(ws, ss_composer)
            evidence["screenshots"]["prompt_submitted"] = str(ss_composer)

            # Correlate mission ID
            m_id = None
            for _ in range(25):
                await asyncio.sleep(1.0)
                if adapter._active_tasks:
                    m_id = list(adapter._active_tasks.keys())[-1]
                    break

            print(f"[+] Correlated mission ID: {m_id}")
            assert m_id, "Mission ID not correlated from browser submission"

            # Await live model execution
            print("[*] Awaiting live model execution...")
            final_snapshot = None
            for i in range(50):
                await asyncio.sleep(1.0)
                snap = adapter.get_mission_snapshot(m_id)
                status_str = snap.mission.status.value if snap else "none"
                if i % 5 == 0:
                    print(f"    - Execution turn {i}s: {status_str}")
                if snap and snap.mission.is_terminal:
                    print(f"[+] Mission reached terminal status: {status_str}")
                    final_snapshot = snap
                    break

            # Switch to Outcome tab
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Outcome'))?.click()"
            })
            await asyncio.sleep(1.5)
            ss_outcome = ARTIFACTS_DIR / "02_browser_outcome_with_response.png"
            await capture_screenshot(ws, ss_outcome)
            evidence["screenshots"]["outcome_tab"] = str(ss_outcome)

            # Switch to Checks tab
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Checks'))?.click()"
            })
            await asyncio.sleep(1.0)
            ss_checks = ARTIFACTS_DIR / "03_browser_checks_tab.png"
            await capture_screenshot(ws, ss_checks)
            evidence["screenshots"]["checks_tab"] = str(ss_checks)

            # Switch to Changes tab
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Changes'))?.click()"
            })
            await asyncio.sleep(1.0)
            ss_changes = ARTIFACTS_DIR / "04_browser_changes_tab.png"
            await capture_screenshot(ws, ss_changes)
            evidence["screenshots"]["changes_tab"] = str(ss_changes)

            # Verify Final Output Content
            async with httpx.AsyncClient() as client:
                snap_resp = await client.get(f"http://127.0.0.1:{SERVER_PORT}/api/missions/{m_id}")
                snap_data = snap_resp.json()

            delivered_output = snap_data.get("final_output") or ""
            print(f"[+] Delivered Agent Final Output:\n--------------------\n{delivered_output}\n--------------------")

            heading_found = "project antigravity architecture" in delivered_output.lower()
            desc_found = "autonomous agent engineering" in delivered_output.lower()

            print(f"[+] Semantic Verification: heading_found={heading_found}, desc_found={desc_found}")

            # Verify Workspace SHA-256 Immutability
            sha_manifest_after = compute_sha256_manifest(ws_dir)
            evidence["manifests"]["sha256_after"] = sha_manifest_after
            manifest_match = (sha_manifest_before == sha_manifest_after)
            print(f"[+] Workspace SHA-256 Immutability match: {manifest_match}")

            # Check Diffs
            async with httpx.AsyncClient() as client:
                diff_resp = await client.get(f"http://127.0.0.1:{SERVER_PORT}/api/missions/{m_id}/diffs")
                diff_data = diff_resp.json()

            additions = diff_data.get("total_additions", 0)
            deletions = diff_data.get("total_deletions", 0)
            print(f"[+] Diffs reported: +{additions} / -{deletions}, affected files: {len(diff_data.get('files', []))}")

            # Run explicit child verification subprocess with canonical python
            verify_script = (
                f"import hashlib\n"
                f"content = open(r'{readme_target}', 'rb').read()\n"
                f"assert hashlib.sha256(content).hexdigest() == '{sha_manifest_before.get('README.md')}'\n"
                f"assert 'Project Antigravity Architecture' in content.decode('utf-8')\n"
                f"print('VERIFICATION_SUBPROCESS_SUCCESS')\n"
            )
            child_verify_proc = subprocess.run(
                [CANONICAL_PYTHON, "-c", verify_script],
                cwd=str(ws_dir),
                capture_output=True,
                text=True,
            )
            print(f"[+] Child Subprocess Exit Code: {child_verify_proc.returncode}")
            print(f"[+] Child Subprocess Output: {child_verify_proc.stdout.strip()}")

            verdict = (
                snap_data.get("status") == "COMPLETED"
                and heading_found
                and desc_found
                and manifest_match
                and additions == 0
                and deletions == 0
                and child_verify_proc.returncode == 0
            )

            evidence["scenarios"]["live_read_only_fulfillment"] = {
                "mission_id": m_id,
                "prompt": ro_prompt,
                "terminal_status": snap_data.get("status"),
                "delivered_output": delivered_output,
                "heading_fulfilled": heading_found,
                "description_fulfilled": desc_found,
                "sha256_manifest_before": sha_manifest_before,
                "sha256_manifest_after": sha_manifest_after,
                "manifest_immutable": manifest_match,
                "diff_additions": additions,
                "diff_deletions": deletions,
                "child_verification_executable": CANONICAL_PYTHON,
                "child_verification_exit_code": child_verify_proc.returncode,
                "child_verification_output": child_verify_proc.stdout.strip(),
                "verdict": "PASS" if verdict else "FAIL",
            }
            evidence["overall_verdict"] = "PASS" if verdict else "FAIL"

            evidence_path = ARTIFACTS_DIR / "browser_acceptance_evidence.json"
            evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(f"[+] Saved audit evidence to {evidence_path}")
            print(f"[*] Overall Audit Verdict: {evidence['overall_verdict']}")

    finally:
        if chrome_proc:
            chrome_proc.kill()
        server.should_exit = True
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(run_stage6_2_audit())
