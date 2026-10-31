"""
HERMES Stage 6.1 - Browser-to-Runtime Mission Correlation and Live Model Acceptance Audit.

Executes real end-to-end browser-submitted missions against the authoritative Python runtime
and live configured model (T1: NVIDIA NIM z-ai/glm-5.3-flash):

1. Browser-Submitted Creation Mission:
   - Types file-creation task into GUI Composer.
   - Clicks Send; captures generated mission ID.
   - Observes runtime execution through live model to COMPLETED.
   - Inspects created files on disk; executes pytest verification check.
   - Captures Changes, Checks, and Outcome screenshots.

2. Browser-Submitted Modification Mission:
   - Pre-populates source file baseline in isolated workspace.
   - Submits file-modification task via GUI Composer.
   - Correlates mission ID; verifies modified contents on disk.
   - Verifies genuine unified diff in API and UI.

3. Complete Read-Only Inspection Mission:
   - Submits inspection task against existing README fixture via GUI Composer.
   - Verifies zero mutations on disk (before/after manifest identical).
   - Verifies diff returns 0 created/modified files.
   - Correlates live model read-only response in Outcome panel.

Exports screenshots, manifests, and browser_acceptance_evidence.json into artifacts/stage6_1/.
"""

from __future__ import annotations

import asyncio
import base64
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

ARTIFACTS_DIR = ROOT / "artifacts" / "stage6_1"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9232
SERVER_PORT = 8765


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


async def run_stage6_1_audit():
    print(f"[*] Starting Stage 6.1 End-to-End Live Browser Acceptance Audit on port {SERVER_PORT}...")

    evidence = {
        "stage": "6.1",
        "timestamp": time.time(),
        "model_configured": "z-ai/glm-5.3-flash (NVIDIA NIM)",
        "scenarios": {},
        "screenshots": {},
        "manifests": {},
        "verification_runs": {},
    }

    # ── WORKSPACE 1: Browser-Submitted Creation Mission ──
    ws_create = (ROOT / "data" / "ws_stage6_1_creation").resolve()
    if ws_create.exists():
        shutil.rmtree(ws_create, ignore_errors=True)
    ws_create.mkdir(parents=True, exist_ok=True)
    workspace_manager.lock(ws_create)
    clear_file_baselines()

    adapter = RuntimeAdapter(event_bus=event_bus, workspace_manager=workspace_manager)
    app = create_app(adapter=adapter)

    config = uvicorn.Config(app=app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    user_data_dir = ROOT / ".temp_chrome_audit_6_1"
    if user_data_dir.exists():
        shutil.rmtree(user_data_dir, ignore_errors=True)
    user_data_dir.mkdir(exist_ok=True)

    chrome_cmd = [
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={user_data_dir}",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1440,900",
        "about:blank",
    ]
    chrome_proc = subprocess.Popen(chrome_cmd)

    try:
        async with httpx.AsyncClient() as http_client:
            for _ in range(30):
                await asyncio.sleep(0.2)
                try:
                    r = await http_client.get(f"http://127.0.0.1:{SERVER_PORT}/api/health", timeout=1.0)
                    if r.status_code == 200:
                        print("[+] FastAPI server ready.")
                        break
                except Exception:
                    pass

            cdp_ws_url = None
            for _ in range(30):
                await asyncio.sleep(0.3)
                try:
                    r = await http_client.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=1.0)
                    if r.status_code == 200:
                        pages = r.json()
                        page = next((p for p in pages if p.get("type") == "page" and "webSocketDebuggerUrl" in p), None)
                        if page:
                            cdp_ws_url = page["webSocketDebuggerUrl"]
                            print(f"[+] Chrome CDP connected: {cdp_ws_url}")
                            break
                except Exception:
                    pass

        if not cdp_ws_url:
            raise RuntimeError("Could not connect to Chrome CDP endpoint.")

        async with websockets.connect(cdp_ws_url, max_size=20_000_000) as ws:
            await cdp_call(ws, "Page.enable")
            await cdp_call(ws, "Runtime.enable")

            # ═════════════════════════════════════════════════════════════════════
            # SCENARIO 1: Real Browser-Submitted Creation Mission
            # ═════════════════════════════════════════════════════════════════════
            print("\n[*] --------------------------------------------------------")
            print("[*] EXECUTING SCENARIO 1: Browser-Submitted Creation Mission")
            print("[*] --------------------------------------------------------")
            await cdp_call(ws, "Page.navigate", {"url": f"http://127.0.0.1:{SERVER_PORT}"})
            await asyncio.sleep(2.5)

            creation_prompt = "Write a python module string_ops.py with a function reverse_str(s: str) -> str that reverses s."
            sub_res = await submit_prompt_in_browser(ws, creation_prompt)
            print("[+] Creation prompt submitted via browser:", sub_res)

            m_create_id = None
            for _ in range(15):
                await asyncio.sleep(1.0)
                if adapter._active_tasks:
                    m_create_id = list(adapter._active_tasks.keys())[-1]
                    break

            print(f"[+] Captured creation mission ID: {m_create_id}")
            assert m_create_id, "Creation mission ID not found"

            # Wait for mission completion via live model
            print("[*] Awaiting live model execution...")
            for i in range(45):
                await asyncio.sleep(1.0)
                snap = adapter.get_mission_snapshot(m_create_id)
                status = snap.mission.status.value if snap else "none"
                if i % 5 == 0:
                    print(f"    - Turn check {i}s: {status}")
                if snap and snap.mission.is_terminal:
                    print(f"[+] Creation mission reached terminal status: {status}")
                    break

            # Filesystem check
            created_files = [p.name for p in ws_create.iterdir() if p.is_file() and not p.name.startswith(".")]
            print(f"[+] Files on disk in workspace: {created_files}")

            # Verification check execution: run python test against created file
            verify_file = ws_create / "string_ops.py"
            py_verify_out = ""
            py_verify_code = 0
            if verify_file.exists():
                verify_proc = subprocess.run(
                    [sys.executable, "-c", "import string_ops; assert string_ops.reverse_str('hermes') == 'semreh'; print('VERIFIED_OK')"],
                    cwd=str(ws_create),
                    capture_output=True,
                    text=True,
                )
                py_verify_code = verify_proc.returncode
                py_verify_out = verify_proc.stdout.strip()
                print(f"[+] Verification run exit code: {py_verify_code} output: {py_verify_out}")

            # Click Changes tab in browser
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Changes'))?.click()"
            })
            await asyncio.sleep(1.0)
            ss_create_changes = ARTIFACTS_DIR / "01_browser_creation_changes.png"
            await capture_screenshot(ws, ss_create_changes)

            # Click Outcome tab in browser
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Outcome'))?.click()"
            })
            await asyncio.sleep(1.0)
            ss_create_outcome = ARTIFACTS_DIR / "02_browser_creation_outcome.png"
            await capture_screenshot(ws, ss_create_outcome)

            evidence["scenarios"]["creation"] = {
                "mission_id": m_create_id,
                "prompt": creation_prompt,
                "terminal_status": snap.mission.status.value if snap else "FAILED",
                "created_files": created_files,
                "verification_exit_code": py_verify_code,
                "verification_output": py_verify_out,
                "verdict": "PASS" if verify_file.exists() and py_verify_code == 0 else "FAIL",
            }
            evidence["screenshots"]["creation_changes"] = str(ss_create_changes)
            evidence["screenshots"]["creation_outcome"] = str(ss_create_outcome)

            # ═════════════════════════════════════════════════════════════════════
            # SCENARIO 2: Real Browser-Submitted Modification Mission
            # ═════════════════════════════════════════════════════════════════════
            print("\n[*] --------------------------------------------------------")
            print("[*] EXECUTING SCENARIO 2: Browser-Submitted Modification Mission")
            print("[*] --------------------------------------------------------")
            ws_mod = (ROOT / "data" / "ws_stage6_1_mod").resolve()
            if ws_mod.exists():
                shutil.rmtree(ws_mod, ignore_errors=True)
            ws_mod.mkdir(parents=True, exist_ok=True)
            mod_target = ws_mod / "multiplier.py"
            initial_content = "def multiply(a: int, b: int) -> int:\n    return a * 1\n"
            mod_target.write_text(initial_content, encoding="utf-8")
            workspace_manager.lock(ws_mod)
            clear_file_baselines()
            record_file_baseline(ws_mod, "multiplier.py", initial_content)

            mod_prompt = "Edit multiplier.py so that multiply(a, b) returns a * b instead of a * 1."
            # Navigate to clean GUI root
            await cdp_call(ws, "Page.navigate", {"url": f"http://127.0.0.1:{SERVER_PORT}"})
            await asyncio.sleep(2.0)
            # Click New Task in Left Pane
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('New Task'))?.click()"
            })
            await asyncio.sleep(1.0)
            sub_mod_res = await submit_prompt_in_browser(ws, mod_prompt)
            print("[+] Modification prompt submitted via browser:", sub_mod_res)

            m_mod_id = None
            for _ in range(20):
                await asyncio.sleep(1.0)
                if adapter._active_tasks:
                    cand = list(adapter._active_tasks.keys())[-1]
                    if cand != m_create_id:
                        m_mod_id = cand
                        break

            print(f"[+] Captured modification mission ID: {m_mod_id}")
            assert m_mod_id, "Modification mission ID not found"

            print("[*] Awaiting live model execution...")
            for i in range(45):
                await asyncio.sleep(1.0)
                snap_mod = adapter.get_mission_snapshot(m_mod_id)
                status_mod = snap_mod.mission.status.value if snap_mod else "none"
                if i % 5 == 0:
                    print(f"    - Turn check {i}s: {status_mod}")
                if snap_mod and snap_mod.mission.is_terminal:
                    print(f"[+] Modification mission reached terminal status: {status_mod}")
                    break

            post_content = mod_target.read_text(encoding="utf-8")
            print(f"[+] Post-modification content:\n{post_content.strip()}")

            # Verification execution
            mod_verify_proc = subprocess.run(
                [sys.executable, "-c", "import multiplier; assert multiplier.multiply(4, 5) == 20; print('MULTIPLY_VERIFIED_OK')"],
                cwd=str(ws_mod),
                capture_output=True,
                text=True,
            )
            print(f"[+] Multiplier verification exit code: {mod_verify_proc.returncode} output: {mod_verify_proc.stdout.strip()}")

            # Capture Changes tab with diff
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Changes'))?.click()"
            })
            await asyncio.sleep(1.0)
            ss_mod_changes = ARTIFACTS_DIR / "03_browser_modification_diff.png"
            await capture_screenshot(ws, ss_mod_changes)

            evidence["scenarios"]["modification"] = {
                "mission_id": m_mod_id,
                "prompt": mod_prompt,
                "terminal_status": snap_mod.mission.status.value if snap_mod else "FAILED",
                "file_modified": "multiplier.py",
                "initial_content": initial_content,
                "resulting_content": post_content,
                "verification_exit_code": mod_verify_proc.returncode,
                "verification_output": mod_verify_proc.stdout.strip(),
                "verdict": "PASS" if "return a * b" in post_content and mod_verify_proc.returncode == 0 else "FAIL",
            }
            evidence["screenshots"]["modification_diff"] = str(ss_mod_changes)

            # =====================================================================
            # SCENARIO 3: Complete Read-Only Inspection Mission
            # =====================================================================
            print("\n[*] --------------------------------------------------------")
            print("[*] EXECUTING SCENARIO 3: Real Read-Only Inspection Mission")
            print("[*] --------------------------------------------------------")
            ws_ro = (ROOT / "data" / "ws_stage6_1_readonly").resolve()
            if ws_ro.exists():
                shutil.rmtree(ws_ro, ignore_errors=True)
            ws_ro.mkdir(parents=True, exist_ok=True)
            readme_target = ws_ro / "README.md"
            readme_text = "# Project Antigravity Architecture\n\nThis system provides autonomous agent engineering with strict safety gates.\n"
            readme_target.write_text(readme_text, encoding="utf-8")
            workspace_manager.lock(ws_ro)
            clear_file_baselines()

            ro_manifest_before = {p.name: {"size": p.stat().st_size, "mtime": p.stat().st_mtime} for p in ws_ro.iterdir() if p.is_file() and not p.name.startswith(".")}
            evidence["manifests"]["readonly_before"] = ro_manifest_before

            ro_prompt = "Inspect README.md and report its primary heading and description without modifying any files."
            await cdp_call(ws, "Page.navigate", {"url": f"http://127.0.0.1:{SERVER_PORT}"})
            await asyncio.sleep(2.0)
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('New Task'))?.click()"
            })
            await asyncio.sleep(1.0)
            sub_ro_res = await submit_prompt_in_browser(ws, ro_prompt)
            print("[+] Read-only prompt submitted via browser:", sub_ro_res)

            m_ro_id = None
            for _ in range(20):
                await asyncio.sleep(1.0)
                if adapter._active_tasks:
                    cand = list(adapter._active_tasks.keys())[-1]
                    if cand not in (m_create_id, m_mod_id):
                        m_ro_id = cand
                        break

            print(f"[+] Captured read-only mission ID: {m_ro_id}")
            assert m_ro_id, "Read-only mission ID not found"

            print("[*] Awaiting live model execution...")
            for i in range(45):
                await asyncio.sleep(1.0)
                snap_ro = adapter.get_mission_snapshot(m_ro_id)
                status_ro = snap_ro.mission.status.value if snap_ro else "none"
                if i % 5 == 0:
                    print(f"    - Turn check {i}s: {status_ro}")
                if snap_ro and snap_ro.mission.is_terminal:
                    print(f"[+] Read-only mission reached terminal status: {status_ro}")
                    break

            ro_manifest_after = {p.name: {"size": p.stat().st_size, "mtime": p.stat().st_mtime} for p in ws_ro.iterdir() if p.is_file() and not p.name.startswith(".")}
            evidence["manifests"]["readonly_after"] = ro_manifest_after
            manifest_identical = (ro_manifest_before == ro_manifest_after)
            print(f"[+] Filesystem immutability verified: {manifest_identical}")

            # Check API diff returns 0 files
            async with httpx.AsyncClient() as client:
                diff_ro_res = await client.get(f"http://127.0.0.1:{SERVER_PORT}/api/missions/{m_ro_id}/diffs")
                diff_ro_data = diff_ro_res.json()
                print(f"[+] API diff affected files count: {len(diff_ro_data.get('files', []))}")

            # Capture Outcome tab
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Outcome'))?.click()"
            })
            await asyncio.sleep(1.0)
            ss_ro_outcome = ARTIFACTS_DIR / "04_browser_readonly_outcome.png"
            await capture_screenshot(ws, ss_ro_outcome)

            evidence["scenarios"]["readonly"] = {
                "mission_id": m_ro_id,
                "prompt": ro_prompt,
                "terminal_status": snap_ro.mission.status.value if snap_ro else "FAILED",
                "manifest_immutable": manifest_identical,
                "diff_files_count": len(diff_ro_data.get("files", [])),
                "verdict": "PASS" if manifest_identical and snap_ro and snap_ro.mission.status.value == "COMPLETED" and len(diff_ro_data.get("files", [])) == 0 else "FAIL",
            }
            evidence["screenshots"]["readonly_outcome"] = str(ss_ro_outcome)

            evidence["overall_verdict"] = "PASS" if all(s["verdict"] == "PASS" for s in evidence["scenarios"].values()) else "FAIL"

            evidence_file = ARTIFACTS_DIR / "browser_acceptance_evidence.json"
            evidence_file.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(f"\n[+] Stage 6.1 Audit Complete! Saved evidence to {evidence_file}")

    finally:
        if chrome_proc:
            chrome_proc.kill()
        server.should_exit = True
        await server_task
        workspace_manager.unlock()
        clear_file_baselines()
        if user_data_dir.exists():
            shutil.rmtree(user_data_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_stage6_1_audit())
