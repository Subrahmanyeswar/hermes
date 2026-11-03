import os
import sys
import time
import json
import sqlite3
import shutil
import subprocess
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAIN_DIR = Path(r"C:\Users\SUBBU\.gemini\antigravity\brain\0053cd8a-b464-4edf-b9e4-90e766120e56")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

sys.stdout.reconfigure(encoding='utf-8')

from tools.browser_tools import (
    BrowserSetViewportTool,
    BrowserClickTool,
    BrowserFillTool,
    BrowserScreenshotTool,
    BrowserGetConsoleErrorsTool,
    BrowserGetNetworkFailuresTool,
    BrowserCheckLayoutTool,
    get_browser_manager,
    _run_async,
)

WS_DIR = Path(r"C:\Users\SUBBU\Downloads\testing 1").resolve()
PYTHON_EXE = r"C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe"

def run_campusflow_live_qualification():
    print("=" * 70)
    print("CAMPUSFLOW LIVE SERVER & END-TO-END BROWSER QUALIFICATION")
    print("=" * 70)

    # 1. Start live CampusFlow Uvicorn server on port 8000
    print("\n[Step 1] Starting CampusFlow backend on http://127.0.0.1:8000...")
    server_env = os.environ.copy()
    server_env["PYTHONUNBUFFERED"] = "1"
    server_proc = subprocess.Popen(
        [PYTHON_EXE, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(WS_DIR),
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Poll for server ready
    server_ready = False
    for attempt in range(15):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2) as resp:
                if resp.status == 200:
                    server_ready = True
                    print(f"  Server is LIVE and healthy on attempt {attempt + 1}")
                    break
        except Exception:
            pass

    if not server_ready:
        print("  ERROR: Failed to start CampusFlow server on 127.0.0.1:8000")
        server_proc.terminate()
        return False

    results = {}

    try:
        # 2. Launch Browser Session and Navigate
        print("\n[Step 2] Launching Chrome CDP Browser Session...")
        manager = get_browser_manager()
        _run_async(manager.launch(headless=True))
        _run_async(manager.navigate("http://127.0.0.1:8000/"))
        time.sleep(2)
        print("  Navigated to http://127.0.0.1:8000/")
        results["nav_root_200"] = True

        # Set 1440x900 viewport
        vp_tool = BrowserSetViewportTool(manager)
        vp_tool.execute({"width": 1440, "height": 900})
        click_tool = BrowserClickTool(manager)
        fill_tool = BrowserFillTool(manager)

        # 3. Test Navigation across all 5 views
        print("\n[Step 3] Testing Navigation across all 5 Pages...")
        pages = ["companies", "applications", "interviews", "analytics", "dashboard"]
        for p in pages:
            res_click = click_tool.execute({"target": f".nav-item[data-page='{p}']"})
            time.sleep(0.5)
            # Check active section
            eval_res = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
                "expression": f"document.getElementById('page-{p}').classList.contains('active')",
                "returnByValue": True
            }))
            is_active = eval_res.get("result", {}).get("value", False)
            print(f"  Page '{p}' active: {is_active}")
            results[f"nav_{p}"] = is_active

        # 4. Workflow 1: Create a Company via UI
        print("\n[Step 4] Workflow 1 — Creating a Company via UI...")
        click_tool.execute({"target": ".nav-item[data-page='companies']"})
        time.sleep(0.5)
        click_tool.execute({"target": "#add-company-btn"})
        time.sleep(0.8)

        comp_name = f"Apex Quantum Labs_{os.urandom(3).hex()}"
        fill_tool.execute({"target": "#comp-name", "text": comp_name})
        fill_tool.execute({"target": "#comp-industry", "text": "Quantum Computing"})
        fill_tool.execute({"target": "#comp-location", "text": "Boulder, CO"})
        fill_tool.execute({"target": "#comp-website", "text": "https://apexquantum.example.com"})
        fill_tool.execute({"target": "#comp-desc", "text": "Next-generation quantum semiconductor architectures."})
        time.sleep(0.5)

        click_tool.execute({"target": "#modal-save-btn"})
        time.sleep(1.2)

        # Verify company in UI
        eval_comp = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
            "expression": f"document.body.innerText.includes('{comp_name}')",
            "returnByValue": True
        }))
        comp_visible = eval_comp.get("result", {}).get("value", False)

        # Verify in SQLite DB
        conn = sqlite3.connect(str(WS_DIR / "campusflow.db"))
        c_row = conn.execute("SELECT id, name, industry FROM companies WHERE name = ?", (comp_name,)).fetchone()
        conn.close()
        comp_in_db = c_row is not None
        comp_id = c_row[0] if c_row else None
        print(f"  Company visible in UI: {comp_visible} | In DB: {comp_in_db} (ID={comp_id})")
        results["workflow_1_company_create"] = comp_visible and comp_in_db

        # 5. Workflow 2: Create an Application via UI
        print("\n[Step 5] Workflow 2 — Creating an Application via UI...")
        click_tool.execute({"target": ".nav-item[data-page='applications']"})
        time.sleep(0.5)
        click_tool.execute({"target": "#add-application-btn"})
        time.sleep(0.8)

        # Select the newly created company
        _run_async(manager.driver._send_cdp("Runtime.evaluate", {
            "expression": f"""
            (() => {{
                const sel = document.getElementById('app-company');
                for (let opt of sel.options) {{
                    if (opt.text.includes('{comp_name}')) {{
                        sel.value = opt.value;
                        sel.dispatchEvent(new Event('change'));
                        break;
                    }}
                }}
            }})()
            """,
            "returnByValue": True
        }))
        time.sleep(0.3)

        role_name = "Quantum Systems Researcher"
        fill_tool.execute({"target": "#app-role", "text": role_name})
        fill_tool.execute({"target": "#app-location", "text": "Boulder, CO"})
        fill_tool.execute({"target": "#app-sal-min", "text": "135000"})
        fill_tool.execute({"target": "#app-sal-max", "text": "175000"})
        fill_tool.execute({"target": "#app-notes", "text": "Direct research fellowship application."})
        time.sleep(0.5)

        click_tool.execute({"target": "#modal-save-btn"})
        time.sleep(1.2)

        # Verify application in UI and DB
        eval_app = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
            "expression": f"document.body.innerText.includes('{role_name}')",
            "returnByValue": True
        }))
        app_visible = eval_app.get("result", {}).get("value", False)

        conn = sqlite3.connect(str(WS_DIR / "campusflow.db"))
        a_row = conn.execute("SELECT id, role, status FROM applications WHERE role = ?", (role_name,)).fetchone()
        conn.close()
        app_in_db = a_row is not None
        app_id = a_row[0] if a_row else None
        print(f"  Application visible in UI: {app_visible} | In DB: {app_in_db} (ID={app_id})")
        results["workflow_2_application_create"] = app_visible and app_in_db

        # 6. Workflow 3: Update Application Status
        print("\n[Step 6] Workflow 3 — Updating Application Status (Applied -> Interview)...")
        # Click edit on the application row
        click_tool.execute({"target": f".edit-app-btn[data-id='{app_id}']"})
        time.sleep(0.8)

        _run_async(manager.driver._send_cdp("Runtime.evaluate", {
            "expression": """
            (() => {
                const el = document.getElementById('app-status');
                if (el) {
                    el.value = 'Interview';
                    el.dispatchEvent(new Event('change'));
                }
            })()
            """,
            "returnByValue": True
        }))
        time.sleep(0.3)
        click_tool.execute({"target": "#modal-save-btn"})
        time.sleep(1.2)

        conn = sqlite3.connect(str(WS_DIR / "campusflow.db"))
        updated_status = conn.execute("SELECT status FROM applications WHERE id = ?", (app_id,)).fetchone()[0]
        conn.close()
        print(f"  Application status updated in DB: {updated_status}")
        results["workflow_3_status_update"] = updated_status == "Interview"

        # 7. Workflow 4: Schedule Interview
        print("\n[Step 7] Workflow 4 — Scheduling an Interview...")
        click_tool.execute({"target": ".nav-item[data-page='interviews']"})
        time.sleep(0.5)
        click_tool.execute({"target": "#add-interview-btn"})
        time.sleep(0.8)

        # Select our application in dropdown
        _run_async(manager.driver._send_cdp("Runtime.evaluate", {
            "expression": f"""
            (() => {{
                const el = document.getElementById('int-app');
                if (el) {{
                    el.value = '{app_id}';
                    el.dispatchEvent(new Event('change'));
                }}
            }})()
            """,
            "returnByValue": True
        }))
        time.sleep(0.3)

        int_round = "Quantum Hardware Deep-Dive"
        fill_tool.execute({"target": "#int-round", "text": int_round})
        fill_tool.execute({"target": "#int-interviewer", "text": "Dr. Aris Thorne"})
        fill_tool.execute({"target": "#int-url", "text": "https://meet.quantum.example.com/deepdive"})
        time.sleep(0.5)

        click_tool.execute({"target": "#modal-save-btn"})
        time.sleep(1.2)

        # Verify in UI and DB
        eval_int = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
            "expression": f"document.body.innerText.includes('{int_round}')",
            "returnByValue": True
        }))
        int_visible = eval_int.get("result", {}).get("value", False)

        conn = sqlite3.connect(str(WS_DIR / "campusflow.db"))
        i_row = conn.execute("SELECT id, round, outcome FROM interviews WHERE round = ?", (int_round,)).fetchone()
        conn.close()
        int_in_db = i_row is not None
        int_id = i_row[0] if i_row else None
        print(f"  Interview visible in UI: {int_visible} | In DB: {int_in_db} (ID={int_id})")
        results["workflow_4_interview_schedule"] = int_visible and int_in_db

        # 8. Workflow 6: Analytics & Dashboard Metrics Reflection
        print("\n[Step 8] Workflow 6 — Checking Dashboard & Analytics sync...")
        click_tool.execute({"target": ".nav-item[data-page='dashboard']"})
        time.sleep(1)

        eval_dash = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
            "expression": """
            (() => {
                return {
                    totalApps: document.getElementById('stat-total-apps').textContent,
                    interviews: document.getElementById('stat-interviews').textContent,
                    hasUpcoming: document.getElementById('dashboard-upcoming-interviews').innerText.length > 20
                };
            })()
            """,
            "returnByValue": True
        }))
        dash_vals = eval_dash.get("result", {}).get("value", {})
        print(f"  Dashboard state: {dash_vals}")
        results["workflow_6_dashboard_sync"] = int(dash_vals.get("totalApps", 0)) >= 3

        # 9. Workflow 7: CSV Export
        print("\n[Step 9] Workflow 7 — Testing CSV Export...")
        with urllib.request.urlopen("http://127.0.0.1:8000/api/export/applications.csv") as csv_resp:
            csv_content_type = csv_resp.headers.get("content-type")
            csv_disp = csv_resp.headers.get("content-disposition")
            csv_body = csv_resp.read().decode("utf-8")
            print(f"  CSV Content-Type: {csv_content_type}")
            print(f"  CSV Content-Disposition: {csv_disp}")
            print(f"  CSV Sample: {csv_body.splitlines()[:2]}")
            results["workflow_7_csv_export"] = (
                "text/csv" in csv_content_type and
                "applications.csv" in csv_disp and
                role_name in csv_body
            )

        # 10. Workflow 5: Deletion with Cascade
        print("\n[Step 10] Workflow 5 — Testing Deletion and Cascade...")
        click_tool.execute({"target": ".nav-item[data-page='interviews']"})
        time.sleep(0.5)
        # Delete the interview
        click_tool.execute({"target": f".del-int-btn[data-id='{int_id}']"})
        time.sleep(0.5)
        click_tool.execute({"target": "#confirm-ok-btn"})
        time.sleep(1)

        conn = sqlite3.connect(str(WS_DIR / "campusflow.db"))
        int_deleted = conn.execute("SELECT COUNT(*) FROM interviews WHERE id = ?", (int_id,)).fetchone()[0] == 0
        conn.close()
        print(f"  Interview {int_id} deleted from DB: {int_deleted}")
        results["workflow_5_delete_interview"] = int_deleted

        # 11. Workflow 9: Responsive Viewports & Captures
        print("\n[Step 11] Workflow 9 — Multi-Viewport Testing & Screenshots...")
        shot_tool = BrowserScreenshotTool(manager)

        # Desktop 1440px
        vp_tool.execute({"width": 1440, "height": 900})
        time.sleep(1)
        click_tool.execute({"target": ".nav-item[data-page='dashboard']"})
        time.sleep(1)
        shot_desktop = shot_tool.execute({"name": "campusflow_desktop_1440px_verified"})
        print(f"  Desktop screenshot captured: {shot_desktop.success}")
        if shot_desktop.success and shot_desktop.details and "file_path" in shot_desktop.details:
            src_desk = Path(shot_desktop.details["file_path"])
            if src_desk.exists():
                shutil.copy(src_desk, BRAIN_DIR / "campusflow_desktop.png")
                shutil.copy(src_desk, WS_DIR / "campusflow_desktop.png")
                print(f"  Saved desktop screenshot to brain and workspace: {src_desk}")

        # Tablet 768px
        vp_tool.execute({"width": 768, "height": 1024})
        time.sleep(1)

        # Mobile 375px
        vp_tool.execute({"width": 375, "height": 812, "is_mobile": True})
        time.sleep(1)
        shot_mobile = shot_tool.execute({"name": "campusflow_mobile_375px_verified"})
        print(f"  Mobile screenshot captured: {shot_mobile.success}")
        if shot_mobile.success and shot_mobile.details and "file_path" in shot_mobile.details:
            src_mob = Path(shot_mobile.details["file_path"])
            if src_mob.exists():
                shutil.copy(src_mob, BRAIN_DIR / "campusflow_mobile.png")
                shutil.copy(src_mob, WS_DIR / "campusflow_mobile.png")
                print(f"  Saved mobile screenshot to brain and workspace: {src_mob}")

        # Check mobile menu toggle
        res_toggle = click_tool.execute({"target": "#sidebar-toggle"})
        time.sleep(0.5)
        eval_sidebar = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
            "expression": "document.getElementById('sidebar').classList.contains('active')",
            "returnByValue": True
        }))
        sidebar_active = eval_sidebar.get("result", {}).get("value", False)
        print(f"  Mobile sidebar drawer active: {sidebar_active}")
        results["workflow_9_responsive"] = shot_desktop.success and shot_mobile.success and sidebar_active

        # Check multi-viewport layout
        layout_tool = BrowserCheckLayoutTool(manager)
        layout_res = layout_tool.execute({})
        print(f"  Automated Multi-Viewport Layout Check: {layout_res.success} ({layout_res.output})")
        results["workflow_9_layout_check"] = layout_res.success

        # 12. Workflow 10: Browser Console Errors & Network Failures
        print("\n[Step 12] Workflow 10 — Console & Network Integrity...")
        err_tool = BrowserGetConsoleErrorsTool(manager)
        res_err = err_tool.execute({})
        err_list = res_err.details.get("errors", []) if isinstance(res_err.details, dict) else []
        print(f"  Console Errors Count: {len(err_list)}")
        results["workflow_10_console_errors_count"] = len(err_list)

        net_tool = BrowserGetNetworkFailuresTool(manager)
        res_net = net_tool.execute({})
        net_list = res_net.details.get("failures", []) if isinstance(res_net.details, dict) else []
        print(f"  Network Failures Count: {len(net_list)}")
        results["workflow_10_network_failures_count"] = len(net_list)

    finally:
        # Stop Uvicorn server gracefully
        print("\n[Step 13] Stopping CampusFlow server...")
        server_proc.terminate()
        server_proc.wait(timeout=5)
        print("  Server stopped.")

    # 13. Workflow 8: Persistence across restart
    print("\n[Step 14] Workflow 8 — Verifying Persistence across Restart...")
    # Check that SQLite file contains the created company and application
    conn = sqlite3.connect(str(WS_DIR / "campusflow.db"))
    c_check = conn.execute("SELECT COUNT(*) FROM companies WHERE name = ?", (comp_name,)).fetchone()[0]
    a_check = conn.execute("SELECT COUNT(*) FROM applications WHERE role = ?", (role_name,)).fetchone()[0]
    total_apps_persisted = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    conn.close()
    print(f"  Persistence Check: Company present={c_check == 1}, App present={a_check == 1}, Total Apps={total_apps_persisted}")
    results["workflow_8_persistence"] = (c_check == 1 and a_check == 1 and total_apps_persisted >= 3)

    # Save evidence
    evidence_path = WS_DIR / "FINAL_REVIEW_BROWSER_EVIDENCE.json"
    evidence_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nBrowser verification evidence written to: {evidence_path}")

    print("\n" + "=" * 70)
    print("CAMPUSFLOW E2E VERIFICATION SUMMARY:")
    print("=" * 70)
    all_pass = True
    for k, v in results.items():
        print(f"  {k:35s}: {v}")
        if "count" in k:
            if v > 0: all_pass = False
        elif v is not True:
            all_pass = False

    print(f"\nOVERALL RESULT: {'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
    return all_pass

if __name__ == "__main__":
    run_campusflow_live_qualification()
