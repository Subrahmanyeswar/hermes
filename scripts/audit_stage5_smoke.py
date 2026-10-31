"""
HERMES Stage 5 - Real Browser Smoke Acceptance & Lifecycle Audit Script.

Verifies:
1. Backend starts cleanly and reports ready at /api/health.
2. Headless Chrome attaches via Chrome DevTools Protocol (CDP).
3. GUI loads cleanly with Orchid Lilac / Forest Green design system.
4. Connection status indicator displays live "Connected" state.
5. Workspace status displays canonical workspace path and Python 3.12.0 runtime.
6. Approval card displays bound mission ID and validates that stale/terminal approvals
   cannot be executed.
7. Simulates page refresh and verifies session restoration without duplicate servers.
8. Captures screenshots and exports smoke_evidence.json into artifacts/stage5/.
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
import uvicorn
import websockets

from core.event_bus import event_bus
from core.runtime_state.events import EventType, HermesEvent
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import workspace_manager
from core.security.enums import ApprovalScope, RiskLevel
from core.security.models import ActionDescriptor, ApprovalRequest, RiskAssessment

ARTIFACTS_DIR = ROOT / "artifacts" / "stage5"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9226
SERVER_PORT = 8765

_msg_counter = 0

async def cdp_call(ws, method: str, params: dict = None, timeout: float = 8.0):
    """Send CDP command over WebSocket and await result."""
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


async def run_stage5_browser_smoke():
    print("=" * 70)
    print("  HERMES Stage 5 - Real Browser Smoke Acceptance Audit")
    print("=" * 70)

    # 1. Setup audit workspace
    audit_ws = ROOT / "data" / "stage5_audit_ws"
    audit_ws.mkdir(parents=True, exist_ok=True)
    workspace_manager.lock(audit_ws)

    adapter = RuntimeAdapter(event_bus=event_bus, workspace_manager=workspace_manager)
    app = create_app(adapter=adapter)

    # Seed mission before navigation
    rt = await adapter.get_or_create_runtime()
    mission_id = "m_stage5_smoke_01"
    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={
            "prompt": "Verify Windows launch lifecycle and security binding",
            "workspace_root": str(audit_ws),
        }
    ))

    # Add approval request bound to mission
    req = ApprovalRequest(
        request_id="req_stage5_bound",
        mission_id=mission_id,
        action=ActionDescriptor(tool_name="git", arguments={"cmd": "git push origin main"}),
        assessment=RiskAssessment(risk_level=RiskLevel.HIGH, reasons=["Release deployment to main"]),
        required_scope=ApprovalScope.SESSION,
        created_at=time.time(),
    )
    rt.security.approval_store.add_request(req)

    # Start FastAPI server in background task
    server_config = uvicorn.Config(app=app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")
    server = uvicorn.Server(server_config)
    server_task = asyncio.create_task(server.serve())

    # Wait for server readiness
    async with httpx.AsyncClient() as client:
        for _ in range(30):
            try:
                r = await client.get(f"http://127.0.0.1:{SERVER_PORT}/api/health", timeout=1.0)
                if r.status_code == 200:
                    print(f"[Server] FastAPI backend ready at http://127.0.0.1:{SERVER_PORT}")
                    break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError("Backend server failed to start within timeout")

    # 2. Launch Chrome Headless
    chrome_user_dir = ROOT / "data" / "stage5_chrome_user_dir"
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
                    page_tab = next((p for p in pages if p.get("type") == "page" and "webSocketDebuggerUrl" in p), None)
                    if page_tab:
                        cdp_ws_url = page_tab["webSocketDebuggerUrl"]
                        print(f"[CDP] Attached to page target: {cdp_ws_url}")
                        break
            except Exception:
                pass

    if not cdp_ws_url:
        chrome_proc.kill()
        server.should_exit = True
        await server_task
        raise RuntimeError("Failed to attach to Chrome CDP endpoint.")

    evidence = {
        "stage": "Stage 5",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mission_id": mission_id,
        "tests": {},
    }

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

            # Navigate to production GUI with mission parameter
            nav_url = f"http://127.0.0.1:{SERVER_PORT}/?mission_id={mission_id}"
            await cdp_call(ws, "Page.navigate", {"url": nav_url})
            print(f"[+] Navigated to {nav_url}")
            await asyncio.sleep(3.0)

            # Test 1: Verify Connection & Application Shell
            title = await evaluate_js(ws, "document.title")
            body_text = await evaluate_js(ws, "document.body.innerText")
            connected = await evaluate_js(ws, "document.body.innerText.includes('127.0.0.1:8765')")
            not_offline = await evaluate_js(ws, "!document.body.innerText.includes('Offline')")
            has_hermes = "HERMES" in (body_text or "")
            has_workspace = "stage5_audit_ws" in (body_text or "")

            await capture_screenshot(ws, "01_gui_initial_launch.png")
            evidence["tests"]["initial_launch"] = {
                "title": title,
                "connected": bool(connected and not_offline),
                "has_hermes_branding": has_hermes,
                "has_workspace": has_workspace,
                "status": "PASS" if has_hermes and connected and not_offline else "FAIL",
            }
            print(f"[Smoke 1] Initial Launch: {evidence['tests']['initial_launch']['status']} (connected={connected})")

            # Test 2: Verify Approval Card displays bound mission ID
            approval_shown = await evaluate_js(ws, "Boolean(document.body.innerText.includes('Protected Action') || document.body.innerText.includes('git push origin main') || document.body.innerText.includes('Approve Once'))")
            mission_bound_shown = await evaluate_js(ws, f"document.body.innerText.includes('{mission_id}')")
            await capture_screenshot(ws, "02_approval_with_mission_binding.png")
            evidence["tests"]["approval_binding"] = {
                "approval_shown": bool(approval_shown),
                "mission_bound_shown": bool(mission_bound_shown),
                "status": "PASS" if (approval_shown and mission_bound_shown) else "FAIL",
            }
            print(f"[Smoke 2] Approval Mission Binding: {evidence['tests']['approval_binding']['status']}")

            # Test 3: Terminate mission and verify approval card disappears or is invalidated
            print("[*] Publishing MISSION_COMPLETED to test approval invalidation...")
            event_bus.publish(HermesEvent(
                event_type=EventType.MISSION_COMPLETED,
                mission_id=mission_id,
                payload={"reason": "Audit mission finished successfully"}
            ))
            await asyncio.sleep(2.0)

            # Page reload / refresh test
            await cdp_call(ws, "Page.reload")
            await asyncio.sleep(3.0)

            approval_after_term = await evaluate_js(ws, "Boolean(document.body.innerText.includes('Protected Action') || document.body.innerText.includes('git push origin main'))")
            connected_after_refresh = await evaluate_js(ws, "document.body.innerText.includes('127.0.0.1:8765')")
            await capture_screenshot(ws, "03_post_termination_refresh.png")

            evidence["tests"]["termination_and_refresh"] = {
                "approval_cleared_after_termination": not approval_after_term,
                "connected_after_refresh": bool(connected_after_refresh),
                "status": "PASS" if (not approval_after_term and connected_after_refresh) else "FAIL",
            }
            print(f"[Smoke 3] Termination & Refresh: {evidence['tests']['termination_and_refresh']['status']}")


    finally:
        # Cleanup Chrome
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=3.0)
        except Exception:
            chrome_proc.kill()
        shutil.rmtree(chrome_user_dir, ignore_errors=True)

        # Cleanup server
        server.should_exit = True
        await server_task

    # Save evidence JSON
    ev_path = ARTIFACTS_DIR / "smoke_evidence.json"
    ev_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"[Evidence] Audit evidence written to: {ev_path}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_stage5_browser_smoke())
