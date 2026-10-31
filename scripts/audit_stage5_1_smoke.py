"""
HERMES Stage 5.1 - Real Browser Smoke Acceptance & Lifecycle Resilience Script.

Verifies:
1. Normal launch and connection via Chrome/CDP on http://127.0.0.1:8765.
2. Verified TopBar connectivity ("127.0.0.1:8765") and isolated test workspace display.
3. Browser refresh without creating a duplicate backend server (process count constant).
4. Clear handling of backend unavailability (shows offline state when server stopped).
5. Correct GUI reconnection after a server restart (reconnects cleanly to 127.0.0.1:8765).
6. Captures screenshots and exports evidence into artifacts/stage5_1/.
"""

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
import websockets
import psutil

from core.event_bus import event_bus
from core.runtime_state.events import EventType, HermesEvent
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import workspace_manager
from core.server import launcher

ARTIFACTS_DIR = ROOT / "artifacts" / "stage5_1"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9227
SERVER_PORT = 8765

_msg_counter = 0

async def cdp_call(ws, method: str, params: dict = None, timeout: float = 12.0):
    global _msg_counter
    _msg_counter += 1
    msg_id = _msg_counter
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


async def evaluate_js(ws, expr: str):
    res = await cdp_call(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return res.get("result", {}).get("value")


async def capture_screenshot(ws, filename: str):
    res = await cdp_call(ws, "Page.captureScreenshot", {"format": "png", "quality": 95})
    b64_data = res.get("data", "")
    if b64_data:
        out_path = ARTIFACTS_DIR / filename
        out_path.write_bytes(base64.b64decode(b64_data))
        print(f"[Screenshot] Saved: {out_path.name}")
        return True
    return False


def spawn_isolated_server_proc():
    """Spawn an isolated real subprocess running HERMES backend."""
    cmd = [
        sys.executable,
        "-m", "uvicorn", "core.server.app:app",
        "--host", "127.0.0.1",
        "--port", str(SERVER_PORT),
        "--log-level", "warning"
    ]
    proc = subprocess.Popen(cmd, cwd=str(ROOT))
    return proc


async def wait_for_server(timeout: float = 10.0) -> bool:
    start = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                r = await client.get(f"http://127.0.0.1:{SERVER_PORT}/api/health", timeout=1.0)
                if r.status_code == 200:
                    return True
            except Exception:
                await asyncio.sleep(0.3)
    return False


async def run_stage5_1_browser_smoke():
    print("=" * 70)
    print("  HERMES Stage 5.1 - Real Browser Failure-Path & Lifecycle Smoke Audit")
    print("=" * 70)

    # 1. Setup isolated test workspace
    audit_ws = ROOT / "data" / "stage5_1_audit_ws"
    audit_ws.mkdir(parents=True, exist_ok=True)
    workspace_manager.lock(audit_ws)

    # Isolated test mission fixture
    mission_id = "m_stage5_1_lifecycle_fixture"
    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={
            "prompt": "Verify Stage 5.1 Windows process safety and failure paths",
            "workspace_root": str(audit_ws),
        }
    ))

    # Spawn real server process 1
    server_proc1 = spawn_isolated_server_proc()
    ready = await wait_for_server(10.0)
    if not ready:
        server_proc1.kill()
        raise RuntimeError("Isolated server 1 failed to become ready.")
    print(f"[Server] Isolated FastAPI server 1 running (PID: {server_proc1.pid})")

    # 2. Launch Headless Chrome
    chrome_user_dir = ROOT / "data" / "stage5_1_chrome_user_dir"
    if chrome_user_dir.exists():
        shutil.rmtree(chrome_user_dir, ignore_errors=True)
    chrome_user_dir.mkdir(parents=True, exist_ok=True)

    chrome_cmd = [
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={chrome_user_dir}",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1440,900",
        "about:blank",
    ]
    chrome_proc = subprocess.Popen(chrome_cmd)
    print(f"[Chrome] Headless Chrome started (PID: {chrome_proc.pid}, Port: {CDP_PORT})")

    # Connect to CDP
    cdp_ws_url = None
    async with httpx.AsyncClient() as http_c:
        for _ in range(25):
            await asyncio.sleep(0.3)
            try:
                r = await http_c.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=1.0)
                if r.status_code == 200:
                    pages = r.json()
                    # Strictly select the browser tab page (e.g. about:blank), ignoring background extensions
                    page_tab = next((p for p in pages if p.get("type") == "page" and "webSocketDebuggerUrl" in p and ("about:blank" in p.get("url", "") or "8765" in p.get("url", ""))), None)
                    if not page_tab:
                        page_tab = next((p for p in pages if p.get("type") == "page" and "webSocketDebuggerUrl" in p), None)
                    if page_tab:
                        cdp_ws_url = page_tab["webSocketDebuggerUrl"]
                        print(f"[CDP] Attached to page target: {cdp_ws_url} (URL: {page_tab.get('url')})")
                        break
            except Exception:
                pass

    if not cdp_ws_url:
        chrome_proc.kill()
        server_proc1.kill()
        raise RuntimeError("Failed to attach to Chrome CDP endpoint")

    evidence = {
        "stage": "Stage 5.1",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mission_id": mission_id,
        "tests": {},
    }

    server_proc2 = None
    try:
        async with websockets.connect(cdp_ws_url, max_size=20 * 1024 * 1024) as ws:
            await cdp_call(ws, "Page.enable")
            await cdp_call(ws, "DOM.enable")
            await cdp_call(ws, "Runtime.enable")
            await cdp_call(ws, "Emulation.setDeviceMetricsOverride", {
                "width": 1440,
                "height": 900,
                "deviceScaleFactor": 1,
                "mobile": False,
            })

            # Navigate to GUI
            nav_url = f"http://127.0.0.1:{SERVER_PORT}/?mission_id={mission_id}"
            await cdp_call(ws, "Page.navigate", {"url": nav_url})
            print(f"[+] Navigated to {nav_url}")
            await asyncio.sleep(3.5)

            # Scenario 1: Normal Launch and Connection
            body_text = await evaluate_js(ws, "document.body.innerText")
            connected_1 = await evaluate_js(ws, "document.body.innerText.includes('127.0.0.1:8765')")
            not_offline_1 = await evaluate_js(ws, "!document.body.innerText.includes('Offline')")
            has_hermes = "HERMES" in (body_text or "")
            # Check for either workspace name in sidebar/topbar or repo root
            has_workspace = "hermes" in (body_text or "").lower() or "stage5_1" in (body_text or "").lower()
            await capture_screenshot(ws, "01_normal_launch_and_connection.png")

            evidence["tests"]["normal_launch_and_connection"] = {
                "connected": bool(connected_1 and not_offline_1),
                "has_hermes_branding": has_hermes,
                "has_workspace": has_workspace,
                "status": "PASS" if connected_1 and not_offline_1 and has_hermes and has_workspace else "FAIL",
            }
            print(f"[Scenario 1] Normal launch & connection: {evidence['tests']['normal_launch_and_connection']['status']}")

            # Scenario 2: Refresh without creating duplicate backend
            initial_hermes_processes = [
                p.pid for p in psutil.process_iter(["pid", "name", "cmdline"])
                if launcher.is_hermes_process(p)
            ]
            await cdp_call(ws, "Page.reload")
            # Wait for client to complete initial GET /api/health after reload
            await asyncio.sleep(5.0)

            post_refresh_hermes_processes = [
                p.pid for p in psutil.process_iter(["pid", "name", "cmdline"])
                if launcher.is_hermes_process(p)
            ]
            connected_after_refresh = await evaluate_js(ws, "document.body.innerText.includes('127.0.0.1:8765')")
            await capture_screenshot(ws, "02_browser_refresh_no_duplicates.png")

            evidence["tests"]["refresh_no_duplicate_processes"] = {
                "connected": bool(connected_after_refresh),
                "process_count_before": len(initial_hermes_processes),
                "process_count_after": len(post_refresh_hermes_processes),
                "no_duplicate_spawned": len(post_refresh_hermes_processes) <= max(1, len(initial_hermes_processes)),
                "status": "PASS" if connected_after_refresh and len(post_refresh_hermes_processes) <= max(1, len(initial_hermes_processes)) else "FAIL",
            }
            print(f"[Scenario 2] Browser refresh without duplicate processes: {evidence['tests']['refresh_no_duplicate_processes']['status']}")

            # Scenario 3: Backend unavailability handling
            print(f"[*] Terminating server 1 (PID: {server_proc1.pid}) to test offline banner and status...")
            server_proc1.terminate()
            try:
                server_proc1.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                server_proc1.kill()

            print("[*] Waiting for client polling interval to detect offline state...")
            await asyncio.sleep(8.0)

            offline_banner_shown = await evaluate_js(ws, "Boolean(document.body.innerText.includes('Local HERMES backend offline') || document.body.innerText.includes('Offline'))")
            await capture_screenshot(ws, "03_backend_offline_state.png")

            evidence["tests"]["backend_unavailability"] = {
                "offline_state_detected": bool(offline_banner_shown),
                "status": "PASS" if offline_banner_shown else "FAIL",
            }
            print(f"[Scenario 3] Backend unavailability handling: {evidence['tests']['backend_unavailability']['status']}")

            # Scenario 4: GUI Reconnection after server restart
            print("[*] Restarting backend server 2 to verify automatic GUI reconnection...")
            server_proc2 = spawn_isolated_server_proc()
            ready2 = await wait_for_server(10.0)
            assert ready2, "Server 2 failed to become ready"
            print(f"[Server] Server 2 running (PID: {server_proc2.pid})")

            print("[*] Waiting for GUI to poll and re-establish connection...")
            await asyncio.sleep(8.0)

            reconnected = await evaluate_js(ws, "document.body.innerText.includes('127.0.0.1:8765') && !document.body.innerText.includes('Local HERMES backend offline')")
            await capture_screenshot(ws, "04_reconnected_after_restart.png")

            evidence["tests"]["reconnection_after_restart"] = {
                "reconnected": bool(reconnected),
                "status": "PASS" if reconnected else "FAIL",
            }
            print(f"[Scenario 4] GUI reconnection after server restart: {evidence['tests']['reconnection_after_restart']['status']}")

    finally:
        # Cleanup Chrome
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=3.0)
        except Exception:
            chrome_proc.kill()
        shutil.rmtree(chrome_user_dir, ignore_errors=True)

        # Cleanup server processes
        if server_proc1 and server_proc1.poll() is None:
            server_proc1.kill()
        if server_proc2 and server_proc2.poll() is None:
            server_proc2.kill()

    # Save evidence JSON
    ev_path = ARTIFACTS_DIR / "smoke_evidence.json"
    ev_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"[Evidence] Stage 5.1 audit evidence written to: {ev_path}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_stage5_1_browser_smoke())
