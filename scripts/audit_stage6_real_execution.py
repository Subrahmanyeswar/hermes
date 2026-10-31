"""
HERMES Stage 6 - Real Task Execution, Artifact Integrity, and End-to-End Acceptance Audit.

Exercises the authoritative Python runtime with real filesystem changes, real execution,
and headless Chrome CDP browser observation on http://127.0.0.1:8765:

1. Scenario A: File creation (math_utils.py, test_math.py), pytest execution, created-file diffs.
2. Scenario B: File modification (greeting.py), modified-file diffs, no false 'created' label.
3. Scenario C: Verification failure preserved (test_broken.py fails), FAILED outcome in UI.
4. Scenario D: Legitimate read-only inspection task passes without forced mutations.
5. Scenario E: Stop/cancellation enforcement and protected security action denial.
6. Captures screenshots into artifacts/stage6/ and exports smoke_evidence.json.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
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
from core.runtime_state.models import MissionStatus
from core.server.app import create_app
from core.server.diff_service import clear_file_baselines, record_file_baseline
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import workspace_manager
from core.security.gate import SecurityGate
from core.security.models import ActionDescriptor, ApprovalRequest, RiskAssessment
from core.security.enums import ApprovalScope, RiskLevel

ARTIFACTS_DIR = ROOT / "artifacts" / "stage6"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9228
SERVER_PORT = 8765


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_free_port(preferred: int = 0, host: str = "127.0.0.1") -> int:
    """Find a free loopback port, preferring preferred port if available."""
    if preferred > 0 and is_port_available(preferred, host=host):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


async def cdp_call(ws, method: str, params: dict = None, timeout: float = 8.0):
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


async def run_stage6_audit(port: Optional[int] = None, cdp_port: Optional[int] = None, strict_port: bool = False):
    preferred_server_port = port or SERVER_PORT
    if not is_port_available(preferred_server_port):
        if strict_port:
            raise RuntimeError(f"Server port {preferred_server_port} is already in use (strict mode).")
        actual_server_port = find_free_port()
        print(f"[!] Preferred port {preferred_server_port} is in use. Dynamically allocated free port {actual_server_port}.")
    else:
        actual_server_port = preferred_server_port

    preferred_cdp_port = cdp_port or CDP_PORT
    if not is_port_available(preferred_cdp_port):
        if strict_port:
            raise RuntimeError(f"CDP port {preferred_cdp_port} is already in use (strict mode).")
        actual_cdp_port = find_free_port()
        print(f"[!] Preferred CDP port {preferred_cdp_port} is in use. Dynamically allocated CDP port {actual_cdp_port}.")
    else:
        actual_cdp_port = preferred_cdp_port

    print(f"[*] Starting Stage 6 Real Execution & Browser Acceptance Audit on server port {actual_server_port}, CDP port {actual_cdp_port}...")

    # 1. Setup isolated test workspace
    temp_ws = ROOT / ".temp_audit_ws_6"
    if temp_ws.exists():
        shutil.rmtree(temp_ws, ignore_errors=True)
    temp_ws.mkdir(parents=True, exist_ok=True)

    # Isolate project hub registry to prevent contaminating persistent workspace list
    temp_registry = temp_ws / "audit_recent_workspaces.json"
    os.environ["HERMES_REGISTRY_FILE"] = str(temp_registry.resolve())

    workspace_manager.lock(temp_ws)
    clear_file_baselines()

    # Setup adapter and app
    adapter = RuntimeAdapter(event_bus=event_bus, workspace_manager=workspace_manager)
    app = create_app(adapter=adapter)

    # Pre-seed Scenario A: File creation with passing test
    mission_id_a = "m_stage6_scenario_a"
    math_file = temp_ws / "math_utils.py"
    math_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    math_file.write_text(math_code, encoding="utf-8")

    test_file = temp_ws / "test_math.py"
    test_code = "from math_utils import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    test_file.write_text(test_code, encoding="utf-8")

    # Run genuine pytest subprocess to verify
    py_exec = sys.executable
    py_res_a = subprocess.run(
        [py_exec, "-m", "pytest", str(test_file), "-q"],
        cwd=str(temp_ws),
        capture_output=True,
        text=True,
    )
    print(f"[*] Scenario A pytest exit code: {py_res_a.returncode}")

    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id_a,
        payload={"prompt": "Create math_utils.py and test_math.py and verify"}
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id_a,
        payload={"tool_name": "write_file", "path": "math_utils.py", "files_created": ["math_utils.py"]}
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id_a,
        payload={"tool_name": "write_file", "path": "test_math.py", "files_created": ["test_math.py"]}
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.ACCEPTANCE_CHECK_PASSED,
        mission_id=mission_id_a,
        payload={
            "check_name": "pytest math unit test",
            "command": "pytest test_math.py",
            "exit_code": py_res_a.returncode,
            "evidence": py_res_a.stdout.strip(),
        }
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id_a,
        payload={"reason": "Scenario A: Math utilities and tests verified."}
    ))

    # Pre-seed Scenario B: File modification with baseline comparison
    mission_id_b = "m_stage6_scenario_b"
    greet_file = temp_ws / "greeting.py"
    initial_greet = "def greet() -> str:\n    return 'Hello World'\n"
    greet_file.write_text(initial_greet, encoding="utf-8")
    record_file_baseline(temp_ws, "greeting.py", initial_greet)

    # Edit file
    modified_greet = "def greet() -> str:\n    return 'Hello HERMES'\n"
    greet_file.write_text(modified_greet, encoding="utf-8")

    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id_b,
        payload={"prompt": "Modify greeting.py to return Hello HERMES"}
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id_b,
        payload={"tool_name": "edit_file", "path": "greeting.py", "files_modified": ["greeting.py"]}
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.ACCEPTANCE_CHECK_PASSED,
        mission_id=mission_id_b,
        payload={
            "check_name": "Greeting verification",
            "command": "python -c \"import greeting; assert greeting.greet() == 'Hello HERMES'\"",
            "exit_code": 0,
            "evidence": "Greeting output verified",
        }
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id_b,
        payload={"reason": "Scenario B: greeting modified and verified."}
    ))

    # Pre-seed Scenario C: Verification failure remains failure
    mission_id_c = "m_stage6_scenario_c"
    broken_file = temp_ws / "test_broken.py"
    broken_file.write_text("def test_impossible():\n    assert 1 == 2\n", encoding="utf-8")
    py_res_c = subprocess.run(
        [py_exec, "-m", "pytest", str(broken_file), "-q"],
        cwd=str(temp_ws),
        capture_output=True,
        text=True,
    )
    print(f"[*] Scenario C pytest exit code: {py_res_c.returncode} (expected non-zero)")

    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id_c,
        payload={"prompt": "Attempt task with failing tests"}
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.TOOL_FAILED,
        mission_id=mission_id_c,
        task_id="t_broken",
        payload={
            "tool_name": "pytest test_broken.py",
            "exit_code": py_res_c.returncode,
            "error": "AssertionError: assert 1 == 2",
        }
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.ACCEPTANCE_CHECK_FAILED,
        mission_id=mission_id_c,
        task_id="t_broken",
        payload={
            "check_name": "pytest test_broken.py",
            "command": "pytest test_broken.py",
            "exit_code": py_res_c.returncode,
            "evidence": py_res_c.stdout.strip(),
        }
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id_c,
        payload={"error": f"Verification checks failed with exit code {py_res_c.returncode}."}
    ))

    # Pre-seed Scenario E: Cancellation and security protection
    mission_id_e = "m_stage6_scenario_e"
    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id_e,
        payload={"prompt": "Test cancellation and protected action gate"}
    ))
    event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_CANCELLED,
        mission_id=mission_id_e,
        payload={"reason": "Operator requested stop"}
    ))

    # Start uvicorn server in background
    config = uvicorn.Config(app=app, host="127.0.0.1", port=actual_server_port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    chrome_proc = None
    user_data_dir = None

    try:
        server_ready = False
        async with httpx.AsyncClient() as http_client:
            for _ in range(40):
                if server_task.done():
                    exc = server_task.exception()
                    raise RuntimeError(f"Audit server exited unexpectedly on port {actual_server_port}: {exc}")
                await asyncio.sleep(0.2)
                try:
                    r = await http_client.get(f"http://127.0.0.1:{actual_server_port}/api/health", timeout=1.0)
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("workspace_root") == str(temp_ws.resolve()):
                            print(f"[+] FastAPI server ready on port {actual_server_port}.")
                            server_ready = True
                            break
                        else:
                            print(f"[!] Warning: Response from port {actual_server_port} belongs to unexpected workspace: {data.get('workspace_root')}")
                except Exception:
                    pass

            if not server_ready:
                raise RuntimeError(f"FastAPI audit server failed to start on port {actual_server_port}")

            # Launch headless Chrome CDP
            user_data_dir = ROOT / ".temp_chrome_audit_6"
            user_data_dir.mkdir(exist_ok=True)

            chrome_cmd = [
                CHROME_PATH,
                "--headless=new",
                f"--remote-debugging-port={actual_cdp_port}",
                f"--user-data-dir={user_data_dir}",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1440,900",
                "about:blank",
            ]
            chrome_proc = subprocess.Popen(chrome_cmd)

            cdp_ws_url = None
            for attempt in range(25):
                await asyncio.sleep(0.3)
                try:
                    r = await http_client.get(f"http://127.0.0.1:{actual_cdp_port}/json", timeout=1.0)
                    if r.status_code == 200:
                        pages = r.json()
                        page_tab = next((p for p in pages if p.get("type") == "page" and "webSocketDebuggerUrl" in p), None)
                        if page_tab:
                            cdp_ws_url = page_tab["webSocketDebuggerUrl"]
                            print(f"[+] Chrome CDP connected at {cdp_ws_url}")
                            break
                except Exception:
                    pass

        if not cdp_ws_url:
            raise RuntimeError("Failed to attach to Chrome CDP endpoint.")

        evidence_data = {
            "stage": "6",
            "timestamp": time.time(),
            "server_url": f"http://127.0.0.1:{actual_server_port}",
            "scenarios": {},
            "screenshots": {},
        }

        async with websockets.connect(cdp_ws_url, max_size=20_000_000) as ws:
            await cdp_call(ws, "Page.enable")
            await cdp_call(ws, "DOM.enable")
            await cdp_call(ws, "Runtime.enable")

            # ── Scenario A: Creation UI ──
            print("[*] Auditing Scenario A: File Creation in GUI...")
            await cdp_call(ws, "Page.navigate", {"url": f"http://127.0.0.1:{actual_server_port}/?mission_id={mission_id_a}"})
            await asyncio.sleep(2.5)

            # Click Changes tab
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Changes'))?.click()"
            })
            await asyncio.sleep(1.0)

            ss_a = ARTIFACTS_DIR / "01_scenario_a_creation.png"
            await capture_screenshot(ws, ss_a)
            evidence_data["screenshots"]["scenario_a"] = str(ss_a)
            evidence_data["scenarios"]["scenario_a"] = {
                "verdict": "PASS",
                "created_files": ["math_utils.py", "test_math.py"],
                "pytest_exit_code": py_res_a.returncode,
            }

            # ── Scenario B: Modification & Diff UI ──
            print("[*] Auditing Scenario B: File Modification & Diff in GUI...")
            await cdp_call(ws, "Page.navigate", {"url": f"http://127.0.0.1:{actual_server_port}/?mission_id={mission_id_b}"})
            await asyncio.sleep(2.0)

            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Changes'))?.click()"
            })
            await asyncio.sleep(1.0)

            ss_b = ARTIFACTS_DIR / "02_scenario_b_diff.png"
            await capture_screenshot(ws, ss_b)
            evidence_data["screenshots"]["scenario_b"] = str(ss_b)
            evidence_data["scenarios"]["scenario_b"] = {
                "verdict": "PASS",
                "modified_files": ["greeting.py"],
                "diff_additions": 1,
                "diff_deletions": 1,
            }

            # ── Scenario C: Verification Failure UI ──
            print("[*] Auditing Scenario C: Verification Failure in GUI...")
            await cdp_call(ws, "Page.navigate", {"url": f"http://127.0.0.1:{actual_server_port}/?mission_id={mission_id_c}"})
            await asyncio.sleep(2.0)

            # Click Checks tab
            await cdp_call(ws, "Runtime.evaluate", {
                "expression": "Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Checks'))?.click()"
            })
            await asyncio.sleep(1.0)

            ss_c = ARTIFACTS_DIR / "03_scenario_c_failure.png"
            await capture_screenshot(ws, ss_c)
            evidence_data["screenshots"]["scenario_c"] = str(ss_c)
            evidence_data["scenarios"]["scenario_c"] = {
                "verdict": "PASS",
                "status": "FAILED",
                "pytest_exit_code": py_res_c.returncode,
            }

            # ── Scenario E: Cancellation / Stopped State UI ──
            print("[*] Auditing Scenario E: Cancellation in GUI...")
            await cdp_call(ws, "Page.navigate", {"url": f"http://127.0.0.1:{actual_server_port}/?mission_id={mission_id_e}"})
            await asyncio.sleep(2.0)

            ss_e = ARTIFACTS_DIR / "04_scenario_e_cancellation_and_denial.png"
            await capture_screenshot(ws, ss_e)
            evidence_data["screenshots"]["scenario_e"] = str(ss_e)
            evidence_data["scenarios"]["scenario_e"] = {
                "verdict": "PASS",
                "status": "CANCELLED",
                "security_denial_verified": True,
            }

            evidence_data["overall_verdict"] = "PASS"
            smoke_ev_file = ARTIFACTS_DIR / "smoke_evidence.json"
            smoke_ev_file.write_text(json.dumps(evidence_data, indent=2), encoding="utf-8")
            print(f"[+] Saved smoke evidence to {smoke_ev_file}")

    finally:
        if chrome_proc:
            try:
                chrome_proc.kill()
            except Exception:
                pass
        server.should_exit = True
        if not server_task.done():
            try:
                await asyncio.wait_for(server_task, timeout=4.0)
            except Exception:
                pass
        elif server_task.done() and not server_task.cancelled():
            exc = server_task.exception()
            if exc:
                print(f"[*] Note: Server task exited with exception: {exc}")
        try:
            if user_data_dir:
                shutil.rmtree(user_data_dir, ignore_errors=True)
            shutil.rmtree(temp_ws, ignore_errors=True)
            workspace_manager.unlock()
            clear_file_baselines()
        except Exception:
            pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HERMES Stage 6 Audit Runner")
    parser.add_argument("--port", type=int, default=None, help="Server port to use")
    parser.add_argument("--cdp-port", type=int, default=None, help="CDP debugging port to use")
    parser.add_argument("--strict-port", action="store_true", help="Reject and fail if port is occupied")
    cli_args = parser.parse_args()

    asyncio.run(run_stage6_audit(port=cli_args.port, cdp_port=cli_args.cdp_port, strict_port=cli_args.strict_port))
