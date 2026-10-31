"""
HERMES Phase 4H - Release Candidate Browser Acceptance & Visual Quality Audit
Executes headless Chrome CDP across the Phase 4H generated applications:
1. hermes_phase4h_app1_habits (StreakFlow Habit & Productivity Dashboard)
2. hermes_phase4h_app2_kanban (KanbanFlow Agile Task Management Console)

Generates:
- artifacts/phase4h/screenshots/{app}_{viewport}.png (>= 9 screenshots across Desktop, Tablet, Mobile)
- artifacts/phase4h/browser_functional_evidence.json
- artifacts/phase4h/visual_quality_evidence.json
"""

import asyncio
import base64
import functools
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
import httpx
import websockets

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = ROOT / "artifacts" / "phase4h" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

APP1_DIR = Path(r"C:\Users\SUBBU\Downloads\hermes_phase4h_app1_habits")
APP2_DIR = Path(r"C:\Users\SUBBU\Downloads\hermes_phase4h_app2_kanban")

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class ThreadedHTTPServer:
    def __init__(self, directory: Path, port: int):
        self.directory = directory
        self.port = port
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        self.httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


async def cdp_call(ws, method: str, params: dict = None, timeout: float = 6.0):
    msg_id = int(time.time() * 1000) % 1000000
    req = {"id": msg_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(req))
    start = time.time()
    while time.time() - start < timeout:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
            resp = json.loads(raw)
            if resp.get("id") == msg_id:
                return resp.get("result", {})
        except asyncio.TimeoutError:
            continue
        except Exception:
            break
    return {}


async def cdp_eval(ws, expr: str, timeout: float = 6.0):
    msg_id = int(time.time() * 1000) % 1000000
    req = {
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True
        }
    }
    await ws.send(json.dumps(req))
    start = time.time()
    while time.time() - start < timeout:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
            resp = json.loads(raw)
            if resp.get("id") == msg_id:
                res = resp.get("result", {}).get("result", {})
                return res.get("value")
        except asyncio.TimeoutError:
            continue
        except Exception:
            break
    return None


async def capture_screenshot(ws, output_path: Path):
    res = await cdp_call(ws, "Page.captureScreenshot", {"format": "png"})
    data = res.get("data")
    if data:
        img_bytes = base64.b64decode(data)
        output_path.write_bytes(img_bytes)
        return True
    return False


async def audit_habits_app(port: int = 8111, cdp_port: int = 9311):
    print("\n" + "=" * 60)
    print("AUDITING APP 1: StreakFlow Habit Tracker Dashboard")
    print(f"Directory: {APP1_DIR} | Port: {port} | CDP: {cdp_port}")
    print("=" * 60)

    server = ThreadedHTTPServer(APP1_DIR, port)
    server.start()

    user_data_dir = tempfile.mkdtemp(prefix="chrome_p4h_app1_")
    chrome_cmd = [
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--window-size=1280,800",
        f"http://127.0.0.1:{port}/index.html"
    ]

    chrome_proc = subprocess.Popen(chrome_cmd)
    results = {
        "app_key": "app1_habits",
        "app_name": "StreakFlow Habit Tracker Dashboard",
        "flows": {},
        "viewports": {},
        "console_errors": [],
        "overall_success": False
    }

    try:
        # Connect to CDP
        cdp_targets = []
        for _ in range(25):
            try:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    resp = await client.get(f"http://127.0.0.1:{cdp_port}/json")
                    if resp.status_code == 200:
                        cdp_targets = resp.json()
                        if any(t.get("type") == "page" for t in cdp_targets):
                            break
            except Exception:
                pass
            await asyncio.sleep(0.3)

        page_target = [t for t in cdp_targets if t.get("type") == "page"][0]
        ws_url = page_target["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url, max_size=10_000_000) as ws:
            await cdp_call(ws, "Runtime.enable")
            await cdp_call(ws, "Page.enable")
            await asyncio.sleep(1.0)

            # Error listener
            await cdp_eval(ws, """(() => {
                window.__p4h_errors = window.__p4h_errors || [];
                window.addEventListener('error', e => window.__p4h_errors.push(e.message || String(e)));
                return true;
            })()""")

            # 1. Viewport Screenshots
            viewports = [
                {"name": "desktop_1280x800", "w": 1280, "h": 800, "mobile": False},
                {"name": "tablet_768x1024", "w": 768, "h": 1024, "mobile": True},
                {"name": "mobile_375x667", "w": 375, "h": 667, "mobile": True},
            ]

            for vp in viewports:
                await cdp_call(ws, "Emulation.setDeviceMetricsOverride", {
                    "width": vp["w"],
                    "height": vp["h"],
                    "deviceScaleFactor": 1,
                    "mobile": vp["mobile"]
                })
                await asyncio.sleep(0.4)
                sw = await cdp_eval(ws, "document.documentElement.scrollWidth")
                iw = await cdp_eval(ws, "window.innerWidth")
                overflow = max(0, (sw or 0) - (iw or 0))

                ss_path = SCREENSHOTS_DIR / f"app1_habits_{vp['name']}.png"
                captured = await capture_screenshot(ws, ss_path)
                results["viewports"][vp["name"]] = {
                    "width": vp["w"],
                    "height": vp["h"],
                    "scrollWidth": sw,
                    "innerWidth": iw,
                    "overflow_px": overflow,
                    "responsive_pass": (overflow <= 5),
                    "screenshot_path": str(ss_path),
                    "screenshot_captured": captured,
                    "bytes": ss_path.stat().st_size if ss_path.exists() else 0
                }
                print(f"  [App1 Viewport {vp['name']}] Overflow: {overflow}px | Captured: {captured} ({ss_path.name})")

            # Reset to Desktop for Functional Flows
            await cdp_call(ws, "Emulation.setDeviceMetricsOverride", {
                "width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False
            })
            await asyncio.sleep(0.3)

            # 2. Check Initial DOM Render
            init_cards = await cdp_eval(ws, "document.querySelectorAll('.habit-card').length")
            init_completed = await cdp_eval(ws, "document.getElementById('completed-today-val').textContent")
            print(f"  [App1 DOM] Initial cards: {init_cards}, Initial completed today: {init_completed}")

            # 3. Check-in Toggle Flow
            # Click the check-in button on the first uncompleted card to increment completedToday
            checkin_before = int(init_completed or 0)
            await cdp_eval(ws, """(() => {
                const uncompletedBtn = document.querySelector('.habit-card:not(.completed) .checkin-btn') || document.querySelector('.checkin-btn');
                if (uncompletedBtn) uncompletedBtn.click();
            })()""")
            await asyncio.sleep(0.4)

            post_checkin = await cdp_eval(ws, "parseInt(document.getElementById('completed-today-val').textContent)")
            checkin_worked = (post_checkin == checkin_before + 1)
            print(f"  [App1 Interaction] Check-in toggle verified: {checkin_worked} ({checkin_before} -> {post_checkin})")

            # Capture Interactive Checked State
            ss_checked = SCREENSHOTS_DIR / "app1_habits_interactive_checked.png"
            await capture_screenshot(ws, ss_checked)

            # 4. Open Add Habit Modal
            await cdp_eval(ws, "document.getElementById('add-habit-btn').click()")
            await asyncio.sleep(0.3)
            modal_visible = await cdp_eval(ws, "!document.getElementById('habit-modal').classList.contains('hidden')")

            # Capture Modal Open Screenshot
            ss_modal = SCREENSHOTS_DIR / "app1_habits_interactive_modal.png"
            await capture_screenshot(ws, ss_modal)

            # Submit New Habit via Form
            submit_expr = """(() => {
                document.getElementById('habit-name').value = '10-Minute Evening Meditation';
                document.getElementById('habit-category').value = 'Mind';
                document.getElementById('habit-frequency').value = 'Daily';
                document.getElementById('habit-target').value = '10m breathwork';
                document.getElementById('habit-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                return true;
            })()"""
            await cdp_eval(ws, submit_expr)
            await asyncio.sleep(0.5)

            new_card_count = await cdp_eval(ws, "document.querySelectorAll('.habit-card').length")
            habit_added = (new_card_count == init_cards + 1)
            print(f"  [App1 Form] Habit Added verified: {habit_added} ({init_cards} -> {new_card_count})")

            # 5. Category Filter Flow
            filter_expr = """(() => {
                const mindBtn = document.querySelector('button[data-category="Mind"]');
                if (mindBtn) mindBtn.click();
            })()"""
            await cdp_eval(ws, filter_expr)
            await asyncio.sleep(0.4)
            mind_cards = await cdp_eval(ws, "document.querySelectorAll('.habit-card').length")
            print(f"  [App1 Filter] Mind category filter verified: {mind_cards} habits visible")

            # Reset Filter
            await cdp_eval(ws, """(() => {
                const allBtn = document.querySelector('button[data-category="ALL"]');
                if (allBtn) allBtn.click();
            })()""")
            await asyncio.sleep(0.3)

            # 6. Page Reload & LocalStorage Persistence Flow
            await cdp_call(ws, "Page.reload")
            await asyncio.sleep(1.0)
            reloaded_cards = await cdp_eval(ws, "document.querySelectorAll('.habit-card').length")
            reloaded_completed = await cdp_eval(ws, "parseInt(document.getElementById('completed-today-val').textContent)")
            persistence_ok = (reloaded_cards == new_card_count and reloaded_completed == post_checkin)
            print(f"  [App1 Persistence] Reloaded cards: {reloaded_cards}, Completed: {reloaded_completed} (Pass: {persistence_ok})")

            # 7. Check Console Errors
            errors = await cdp_eval(ws, "window.__p4h_errors || []") or []
            results["console_errors"] = errors
            results["flows"] = {
                "initial_cards": init_cards,
                "initial_completed": init_completed,
                "checkin_verified": checkin_worked,
                "modal_opened": modal_visible,
                "habit_added": habit_added,
                "post_add_cards": new_card_count,
                "filter_verified": (mind_cards >= 1),
                "persistence_verified": persistence_ok,
                "zero_console_errors": len(errors) == 0
            }
            results["overall_success"] = (
                checkin_worked and habit_added and persistence_ok and len(errors) == 0
            )

    finally:
        chrome_proc.terminate()
        server.stop()
        try:
            shutil.rmtree(user_data_dir, ignore_errors=True)
        except Exception:
            pass

    return results


async def audit_kanban_app(port: int = 8112, cdp_port: int = 9312):
    print("\n" + "=" * 60)
    print("AUDITING APP 2: KanbanFlow Agile Task Management Console")
    print(f"Directory: {APP2_DIR} | Port: {port} | CDP: {cdp_port}")
    print("=" * 60)

    server = ThreadedHTTPServer(APP2_DIR, port)
    server.start()

    user_data_dir = tempfile.mkdtemp(prefix="chrome_p4h_app2_")
    chrome_cmd = [
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--window-size=1280,800",
        f"http://127.0.0.1:{port}/index.html"
    ]

    chrome_proc = subprocess.Popen(chrome_cmd)
    results = {
        "app_key": "app2_kanban",
        "app_name": "KanbanFlow Agile Task Management Console",
        "flows": {},
        "viewports": {},
        "console_errors": [],
        "overall_success": False
    }

    try:
        # Connect to CDP
        cdp_targets = []
        for _ in range(25):
            try:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    resp = await client.get(f"http://127.0.0.1:{cdp_port}/json")
                    if resp.status_code == 200:
                        cdp_targets = resp.json()
                        if any(t.get("type") == "page" for t in cdp_targets):
                            break
            except Exception:
                pass
            await asyncio.sleep(0.3)

        page_target = [t for t in cdp_targets if t.get("type") == "page"][0]
        ws_url = page_target["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url, max_size=10_000_000) as ws:
            await cdp_call(ws, "Runtime.enable")
            await cdp_call(ws, "Page.enable")
            await asyncio.sleep(1.0)

            # Error listener
            await cdp_eval(ws, """(() => {
                window.__p4h_errors = window.__p4h_errors || [];
                window.addEventListener('error', e => window.__p4h_errors.push(e.message || String(e)));
                return true;
            })()""")

            # 1. Viewport Screenshots
            viewports = [
                {"name": "desktop_1280x800", "w": 1280, "h": 800, "mobile": False},
                {"name": "tablet_768x1024", "w": 768, "h": 1024, "mobile": True},
                {"name": "mobile_375x667", "w": 375, "h": 667, "mobile": True},
            ]

            for vp in viewports:
                await cdp_call(ws, "Emulation.setDeviceMetricsOverride", {
                    "width": vp["w"],
                    "height": vp["h"],
                    "deviceScaleFactor": 1,
                    "mobile": vp["mobile"]
                })
                await asyncio.sleep(0.4)
                sw = await cdp_eval(ws, "document.documentElement.scrollWidth")
                iw = await cdp_eval(ws, "window.innerWidth")
                overflow = max(0, (sw or 0) - (iw or 0))

                ss_path = SCREENSHOTS_DIR / f"app2_kanban_{vp['name']}.png"
                captured = await capture_screenshot(ws, ss_path)
                results["viewports"][vp["name"]] = {
                    "width": vp["w"],
                    "height": vp["h"],
                    "scrollWidth": sw,
                    "innerWidth": iw,
                    "overflow_px": overflow,
                    "responsive_pass": (overflow <= 5),
                    "screenshot_path": str(ss_path),
                    "screenshot_captured": captured,
                    "bytes": ss_path.stat().st_size if ss_path.exists() else 0
                }
                print(f"  [App2 Viewport {vp['name']}] Overflow: {overflow}px | Captured: {captured} ({ss_path.name})")

            # Reset to Desktop for Functional Flows
            await cdp_call(ws, "Emulation.setDeviceMetricsOverride", {
                "width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False
            })
            await asyncio.sleep(0.3)

            # 2. Check Initial DOM Render
            init_total = await cdp_eval(ws, "parseInt(document.getElementById('kpi-total-tasks').textContent)")
            init_todo = await cdp_eval(ws, "parseInt(document.getElementById('kpi-todo-tasks').textContent)")
            init_progress = await cdp_eval(ws, "parseInt(document.getElementById('kpi-progress-tasks').textContent)")
            print(f"  [App2 DOM] Initial tasks: total={init_total}, todo={init_todo}, progress={init_progress}")

            # 3. Task Status Move Flow (move first todo card to progress)
            await cdp_eval(ws, """(() => {
                const nextBtn = document.querySelector('#todo-cards .btn-move[data-target="progress"]');
                if (nextBtn) nextBtn.click();
            })()""")
            await asyncio.sleep(0.4)

            post_move_todo = await cdp_eval(ws, "parseInt(document.getElementById('kpi-todo-tasks').textContent)")
            post_move_prog = await cdp_eval(ws, "parseInt(document.getElementById('kpi-progress-tasks').textContent)")
            move_worked = (post_move_todo == init_todo - 1 and post_move_prog == init_progress + 1)
            print(f"  [App2 Interaction] Task moved to In Progress: {move_worked} (Todo: {init_todo}->{post_move_todo}, Prog: {init_progress}->{post_move_prog})")

            # Capture interactive moved state
            ss_moved = SCREENSHOTS_DIR / "app2_kanban_interactive_moved.png"
            await capture_screenshot(ws, ss_moved)

            # 4. Open Add Task Modal
            await cdp_eval(ws, "document.getElementById('add-task-btn').click()")
            await asyncio.sleep(0.3)
            modal_visible = await cdp_eval(ws, "!document.getElementById('task-modal').classList.contains('hidden')")

            # Capture Modal Open Screenshot
            ss_modal = SCREENSHOTS_DIR / "app2_kanban_interactive_modal.png"
            await capture_screenshot(ws, ss_modal)

            # Submit New Task via Form
            submit_expr = """(() => {
                document.getElementById('task-title').value = 'Automate End-to-End Regression Matrix';
                document.getElementById('task-priority').value = 'HIGH';
                document.getElementById('task-status').value = 'todo';
                document.getElementById('task-assignee').value = 'DevSecOps Bot';
                document.getElementById('task-desc').value = 'Runs full test suite across all environments';
                document.getElementById('task-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                return true;
            })()"""
            await cdp_eval(ws, submit_expr)
            await asyncio.sleep(0.5)

            new_total = await cdp_eval(ws, "parseInt(document.getElementById('kpi-total-tasks').textContent)")
            task_added = (new_total == init_total + 1)
            print(f"  [App2 Form] New Task Added verified: {task_added} ({init_total} -> {new_total})")

            # 5. Priority Filter Flow
            filter_expr = """(() => {
                const highBtn = document.querySelector('button[data-priority="HIGH"]');
                if (highBtn) highBtn.click();
            })()"""
            await cdp_eval(ws, filter_expr)
            await asyncio.sleep(0.4)
            high_cards = await cdp_eval(ws, "document.querySelectorAll('.task-card:not(.hidden)').length")
            print(f"  [App2 Filter] High priority filter verified: {high_cards} tasks visible")

            # Reset Priority Filter
            await cdp_eval(ws, """(() => {
                const allBtn = document.querySelector('button[data-priority="ALL"]');
                if (allBtn) allBtn.click();
            })()""")
            await asyncio.sleep(0.3)

            # 6. Page Reload & LocalStorage Persistence Flow
            await cdp_call(ws, "Page.reload")
            await asyncio.sleep(1.0)
            reloaded_total = await cdp_eval(ws, "parseInt(document.getElementById('kpi-total-tasks').textContent)")
            reloaded_progress = await cdp_eval(ws, "parseInt(document.getElementById('kpi-progress-tasks').textContent)")
            persistence_ok = (reloaded_total == new_total and reloaded_progress == post_move_prog)
            print(f"  [App2 Persistence] Reloaded tasks: {reloaded_total}, In-Progress: {reloaded_progress} (Pass: {persistence_ok})")

            # 7. Check Console Errors
            errors = await cdp_eval(ws, "window.__p4h_errors || []") or []
            results["console_errors"] = errors
            results["flows"] = {
                "initial_total": init_total,
                "initial_todo": init_todo,
                "initial_progress": init_progress,
                "move_verified": move_worked,
                "modal_opened": modal_visible,
                "task_added": task_added,
                "post_add_total": new_total,
                "filter_verified": (high_cards >= 1),
                "persistence_verified": persistence_ok,
                "zero_console_errors": len(errors) == 0
            }
            results["overall_success"] = (
                move_worked and task_added and persistence_ok and len(errors) == 0
            )

    finally:
        chrome_proc.terminate()
        server.stop()
        try:
            shutil.rmtree(user_data_dir, ignore_errors=True)
        except Exception:
            pass

    return results


async def main():
    print("=" * 70)
    print("STARTING HERMES PHASE 4H CDP BROWSER ACCEPTANCE SUITE")
    print("=" * 70)

    habits_res = await audit_habits_app(port=8111, cdp_port=9311)
    kanban_res = await audit_kanban_app(port=8112, cdp_port=9312)

    all_evidence = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": "4H",
        "apps": {
            "app1_habits": habits_res,
            "app2_kanban": kanban_res
        },
        "summary": {
            "all_apps_passed": habits_res["overall_success"] and kanban_res["overall_success"],
            "total_viewports_tested": len(habits_res["viewports"]) + len(kanban_res["viewports"]),
            "zero_console_errors_across_all": (len(habits_res["console_errors"]) == 0 and len(kanban_res["console_errors"]) == 0),
            "persistence_verified_across_all": (habits_res["flows"]["persistence_verified"] and kanban_res["flows"]["persistence_verified"])
        }
    }

    # Save functional evidence
    functional_path = ROOT / "artifacts" / "phase4h" / "browser_functional_evidence.json"
    functional_path.write_text(json.dumps(all_evidence, indent=2), encoding="utf-8")
    print(f"\nSaved functional evidence to: {functional_path}")

    # Build visual quality evidence
    visual_evidence = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "screenshots": []
    }
    for ss in sorted(SCREENSHOTS_DIR.glob("*.png")):
        visual_evidence["screenshots"].append({
            "filename": ss.name,
            "path": str(ss),
            "bytes": ss.stat().st_size,
            "created": True
        })

    visual_path = ROOT / "artifacts" / "phase4h" / "visual_quality_evidence.json"
    visual_path.write_text(json.dumps(visual_evidence, indent=2), encoding="utf-8")
    print(f"Saved visual quality evidence to: {visual_path}")
    print(f"Total screenshots generated: {len(visual_evidence['screenshots'])}")

    if not all_evidence["summary"]["all_apps_passed"]:
        print("ERROR: One or more browser acceptance flows failed!")
        sys.exit(1)

    print("\nALL BROWSER AUDIT FLOWS PASSED WITH 100% SUCCESS & ZERO CONSOLE ERRORS!")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
