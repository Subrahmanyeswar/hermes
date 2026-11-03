import sys
import os
import time
import json
import sqlite3
import subprocess
from pathlib import Path

REPO_ROOT = Path(r"C:\Users\SUBBU\Downloads\hermes")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.stdout.reconfigure(encoding='utf-8')

from tools.browser_tools import get_browser_manager, _run_async, BrowserClickTool, BrowserFillTool

WS_DIR = Path(r"C:\Users\SUBBU\Downloads\testing 1")
PYTHON_EXE = r"C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe"

server_proc = subprocess.Popen(
    [PYTHON_EXE, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
    cwd=str(WS_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(2)

try:
    manager = get_browser_manager()
    _run_async(manager.launch(headless=True))
    _run_async(manager.navigate("http://127.0.0.1:8000/"))
    time.sleep(2)
    click_tool = BrowserClickTool(manager)
    fill_tool = BrowserFillTool(manager)

    # 1. Add company
    click_tool.execute({"target": ".nav-item[data-page='companies']"})
    time.sleep(0.5)
    click_tool.execute({"target": "#add-company-btn"})
    time.sleep(0.8)
    comp_name = f"Debug Corp_{int(time.time())}"
    fill_tool.execute({"target": "#comp-name", "text": comp_name})
    click_tool.execute({"target": "#modal-save-btn"})
    time.sleep(1.5)

    # 2. Add application
    click_tool.execute({"target": ".nav-item[data-page='applications']"})
    time.sleep(0.5)
    r_btn = click_tool.execute({"target": "#add-application-btn"})
    print("add-app-btn click:", r_btn.output, r_btn.error)
    time.sleep(0.8)

    # Check select options
    opts = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
        "expression": "Array.from(document.getElementById('app-company').options).map(o => ({text: o.text, val: o.value}))",
        "returnByValue": True
    }))
    print("Options in app-company:", opts.get("result", {}).get("value"))

    # Set company
    set_res = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
        "expression": f"""
        (() => {{
            const sel = document.getElementById('app-company');
            for (let opt of sel.options) {{
                if (opt.text.includes('{comp_name}')) {{
                    sel.value = opt.value;
                    sel.dispatchEvent(new Event('change'));
                    return {{ found: true, val: opt.value }};
                }}
            }}
            return {{ found: false, count: sel.options.length }};
        }})()
        """,
        "returnByValue": True
    }))
    print("set_res:", set_res.get("result", {}).get("value"))

    role_res = fill_tool.execute({"target": "#app-role", "text": "Debug Engineer"})
    print("fill role:", role_res.output, role_res.error)

    # Check fields before click
    fields = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
        "expression": """
        ({
            company: document.getElementById('app-company').value,
            role: document.getElementById('app-role').value,
            btn: !!document.getElementById('modal-save-btn')
        })
        """,
        "returnByValue": True
    }))
    print("fields before save:", fields.get("result", {}).get("value"))

    # Click save
    save_res = click_tool.execute({"target": "#modal-save-btn"})
    print("save click:", save_res.output, save_res.error)
    time.sleep(3)

    # Check toast or alert message in DOM
    toast = _run_async(manager.driver._send_cdp("Runtime.evaluate", {
        "expression": "Array.from(document.querySelectorAll('.toast, .alert, .modal, .toast-container')).map(el => el.innerText)",
        "returnByValue": True
    }))
    print("Toasts / Alerts in DOM:", toast.get("result", {}).get("value"))

    # Check console messages
    for msg in manager.get_console_messages():
        print("CONSOLE:", msg.level, msg.text)

    # Check network failures / records
    net_records = manager.driver.get_network_records()
    print("NETWORK RECORDS:")
    for nr in net_records[-10:]:
        print(f"  {nr.method} {nr.url} -> {nr.status} ({nr.error or 'ok'})")

    # Check DB
    conn = sqlite3.connect(str(WS_DIR / "campusflow.db"))
    c_rows = conn.execute("SELECT id, name FROM companies").fetchall()
    print("DB companies:", c_rows)
    row = conn.execute("SELECT * FROM applications WHERE role = ?", ("Debug Engineer",)).fetchone()
    conn.close()
    print("DB application row:", row)

finally:
    server_proc.terminate()
    out, err = server_proc.communicate()
    print("\nSERVER STDOUT:\n", out)
    print("\nSERVER STDERR:\n", err)

