"""
HERMES Phase 4G - Independent Browser Acceptance & Visual Quality Audit
Executes headless Chrome CDP across all 3 generated applications:
1. hermes_phase4f_simple (Expense Tracker)
2. hermes_phase4f_medium (Inventory Management Console)
3. hermes_phase4f_complex (Developer Portfolio)

Outputs:
- artifacts/phase4g/screenshots/{app}_{viewport}.png
- artifacts/phase4g/browser_functional_evidence.json
- artifacts/phase4g/visual_quality_evidence.json
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
SCREENSHOTS_DIR = ROOT / "artifacts" / "phase4g" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

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
        self.httpd.shutdown()
        self.httpd.server_close()

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

async def audit_application(app_key: str, app_name: str, app_dir: Path, port: int, cdp_port: int):
    print(f"\n=======================================================")
    print(f"AUDITING APPLICATION: {app_name} ({app_key})")
    print(f"Directory: {app_dir} | Port: {port}")
    print(f"=======================================================")

    server = ThreadedHTTPServer(app_dir, port)
    server.start()

    user_data_dir = tempfile.mkdtemp(prefix=f"chrome_p4g_{app_key}_")
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
    
    app_results = {
        "app_key": app_key,
        "app_name": app_name,
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

            # Collect uncaught errors
            errors_expr = """(() => {
                window.__p4g_errors = window.__p4g_errors || [];
                window.addEventListener('error', e => window.__p4g_errors.push(e.message || String(e)));
                return true;
            })()"""
            await cdp_eval(ws, errors_expr)

            # ── 1. Viewport Screenshots & Responsive Reflow ───────────────────
            viewports = [
                {"name": "desktop", "w": 1280, "h": 800, "mobile": False},
                {"name": "tablet", "w": 768, "h": 1024, "mobile": True},
                {"name": "mobile", "w": 375, "h": 667, "mobile": True},
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

                ss_path = SCREENSHOTS_DIR / f"{app_key}_{vp['name']}.png"
                captured = await capture_screenshot(ws, ss_path)

                app_results["viewports"][vp["name"]] = {
                    "width": vp["w"],
                    "height": vp["h"],
                    "scrollWidth": sw,
                    "innerWidth": iw,
                    "overflow_px": overflow,
                    "responsive_pass": (overflow <= 5),
                    "screenshot_path": str(ss_path),
                    "screenshot_captured": captured,
                    "screenshot_bytes": ss_path.stat().st_size if ss_path.exists() else 0
                }
                print(f"  [Viewport {vp['name']}] Reflow: overflow={overflow}px | Screenshot={captured} ({ss_path.name})")

            # Reset to Desktop for Functional Flows
            await cdp_call(ws, "Emulation.setDeviceMetricsOverride", {
                "width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False
            })
            await asyncio.sleep(0.3)

            # ── 2. Functional Application Testing ─────────────────────────────
            if app_key == "simple":
                # Expense Tracker flows
                initial_count = await cdp_eval(ws, "document.querySelectorAll('#transactions-tbody tr').length")
                initial_balance = await cdp_eval(ws, "document.getElementById('total-balance') ? document.getElementById('total-balance').textContent : null")
                
                # Add transaction flow
                await cdp_eval(ws, "document.getElementById('add-transaction-btn').click()")
                await asyncio.sleep(0.3)
                
                add_expr = """(() => {
                    document.getElementById('desc-input').value = 'Test Team Dinner';
                    document.getElementById('category-input').value = 'Food';
                    document.getElementById('amount-input').value = '65.50';
                    document.getElementById('type-input').value = 'expense';
                    document.getElementById('date-input').value = '2026-10-09';
                    document.getElementById('transaction-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                    return true;
                })()"""
                await cdp_eval(ws, add_expr)
                await asyncio.sleep(0.5)

                post_count = await cdp_eval(ws, "document.querySelectorAll('#transactions-tbody tr').length")
                post_balance = await cdp_eval(ws, "document.getElementById('total-balance').textContent")
                row_added = (post_count is not None and initial_count is not None and post_count > initial_count)
                balance_updated = (post_balance != initial_balance)

                # Filter flow
                await cdp_eval(ws, """(() => {
                    const sel = document.getElementById('category-filter');
                    sel.value = 'Food';
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                })()""")
                await asyncio.sleep(0.3)
                food_rows = await cdp_eval(ws, "document.querySelectorAll('#transactions-tbody tr:not(.hidden)').length")

                # Persistence reload flow
                await cdp_call(ws, "Page.reload")
                await asyncio.sleep(1.0)
                reloaded_count = await cdp_eval(ws, "document.querySelectorAll('#transactions-tbody tr').length")
                persisted = (reloaded_count == post_count)

                app_results["flows"] = {
                    "initial_rows": initial_count,
                    "post_add_rows": post_count,
                    "row_added_verified": row_added,
                    "initial_balance": initial_balance,
                    "post_balance": post_balance,
                    "balance_updated_verified": balance_updated,
                    "category_filtered_rows": food_rows,
                    "reload_persisted_verified": persisted
                }

            elif app_key == "medium":
                # Inventory Management flows
                initial_skus = await cdp_eval(ws, "document.querySelectorAll('#inventory-table tbody tr').length")
                kpi_skus = await cdp_eval(ws, "document.querySelector('[data-metric=\"totalSkus\"]').textContent")
                initial_val = await cdp_eval(ws, "document.querySelector('[data-metric=\"totalValue\"]').textContent")

                # Increase stock flow on first product
                stock_before = await cdp_eval(ws, "document.querySelector('.stock-value') ? parseInt(document.querySelector('.stock-value').textContent) : 0")
                await cdp_eval(ws, "document.querySelector('[data-action=\"increase-stock\"]').click()")
                await asyncio.sleep(0.3)
                stock_after = await cdp_eval(ws, "document.querySelector('.stock-value') ? parseInt(document.querySelector('.stock-value').textContent) : 0")
                stock_incremented = (stock_after == stock_before + 1)

                # Search flow
                await cdp_eval(ws, """(() => {
                    const inp = document.getElementById('search-input');
                    inp.value = 'Mouse';
                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                })()""")
                await asyncio.sleep(0.3)
                search_rows = await cdp_eval(ws, "document.querySelectorAll('#inventory-table tbody tr').length")

                # Reset search
                await cdp_eval(ws, """(() => {
                    const inp = document.getElementById('search-input');
                    inp.value = '';
                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                })()""")
                await asyncio.sleep(0.3)

                # Add product modal flow
                await cdp_eval(ws, "document.getElementById('add-product-btn').click()")
                await asyncio.sleep(0.3)
                add_prod_expr = """(() => {
                    document.getElementById('new-sku').value = 'ELEC-999';
                    document.getElementById('new-name').value = 'Macro Keypad';
                    document.getElementById('new-category').value = 'Electronics';
                    document.getElementById('new-stock').value = '25';
                    document.getElementById('new-price').value = '49.99';
                    document.getElementById('new-threshold').value = '5';
                    document.getElementById('add-product-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                    return true;
                })()"""
                await cdp_eval(ws, add_prod_expr)
                await asyncio.sleep(0.5)

                post_skus = await cdp_eval(ws, "document.querySelectorAll('#inventory-table tbody tr').length")
                post_kpi_skus = await cdp_eval(ws, "document.querySelector('[data-metric=\"totalSkus\"]').textContent")
                prod_added = (post_skus == initial_skus + 1)

                # Reload persistence flow
                await cdp_call(ws, "Page.reload")
                await asyncio.sleep(1.0)
                reloaded_skus = await cdp_eval(ws, "document.querySelectorAll('#inventory-table tbody tr').length")
                sku_found = await cdp_eval(ws, "document.body.innerText.includes('ELEC-999')")
                persisted = (reloaded_skus == post_skus and sku_found)

                app_results["flows"] = {
                    "initial_items": initial_skus,
                    "stock_incremented_verified": stock_incremented,
                    "search_filtering_verified": (search_rows >= 1 and search_rows < initial_skus),
                    "product_added_verified": prod_added,
                    "reload_persisted_verified": persisted,
                    "kpi_skus_initial": kpi_skus,
                    "kpi_skus_post": post_kpi_skus
                }

            elif app_key == "complex":
                # Developer Portfolio flows
                initial_cards = await cdp_eval(ws, "document.querySelectorAll('.project-card').length")
                
                # Filter flow
                await cdp_eval(ws, "document.querySelector('.filter-btn[data-category=\"ai-ml\"]').click()")
                await asyncio.sleep(0.3)
                aiml_cards = await cdp_eval(ws, "document.querySelectorAll('.project-card').length")

                # Reset filter
                await cdp_eval(ws, "document.querySelector('.filter-btn[data-category=\"all\"]').click()")
                await asyncio.sleep(0.3)
                all_cards = await cdp_eval(ws, "document.querySelectorAll('.project-card').length")

                # Modal details flow
                await cdp_eval(ws, "document.querySelector('[data-action=\"view-details\"]').click()")
                await asyncio.sleep(0.3)
                modal_visible = await cdp_eval(ws, "!document.getElementById('project-modal').classList.contains('hidden')")
                modal_title = await cdp_eval(ws, "document.getElementById('modal-title') ? document.getElementById('modal-title').textContent : ''")

                # Close modal
                await cdp_eval(ws, "document.querySelector('.modal-close').click()")
                await asyncio.sleep(0.3)
                modal_closed = await cdp_eval(ws, "document.getElementById('project-modal').classList.contains('hidden')")

                app_results["flows"] = {
                    "initial_projects_count": initial_cards,
                    "aiml_filtered_count": aiml_cards,
                    "filtering_verified": (initial_cards > 0 and aiml_cards > 0 and aiml_cards < initial_cards),
                    "all_projects_restored": (all_cards == initial_cards),
                    "modal_opened_verified": modal_visible,
                    "modal_title": modal_title,
                    "modal_closed_verified": modal_closed
                }

            # Check console errors
            errs = await cdp_eval(ws, "window.__p4g_errors || []")
            app_results["console_errors"] = errs or []
            
            flows_all_pass = all(v is True for k, v in app_results["flows"].items() if "verified" in k)
            viewports_pass = all(vp["responsive_pass"] for vp in app_results["viewports"].values())
            app_results["overall_success"] = (flows_all_pass and viewports_pass and len(app_results["console_errors"]) == 0)

            print(f"  Result: Flows={'PASS' if flows_all_pass else 'FAIL'} | Viewports={'PASS' if viewports_pass else 'FAIL'} | Errors={len(app_results['console_errors'])}")

    finally:
        try:
            chrome_proc.terminate()
            chrome_proc.wait(timeout=2.0)
        except Exception:
            try: chrome_proc.kill()
            except Exception: pass
        shutil.rmtree(user_data_dir, ignore_errors=True)
        server.stop()

    return app_results

async def main():
    apps = [
        {"key": "simple", "name": "Personal Expense Tracker", "dir": Path(r"C:\Users\SUBBU\Downloads\hermes_phase4f_simple"), "port": 8101, "cdp_port": 9301},
        {"key": "medium", "name": "Inventory & Stock Management Console", "dir": Path(r"C:\Users\SUBBU\Downloads\hermes_phase4f_medium"), "port": 8102, "cdp_port": 9302},
        {"key": "complex", "name": "Developer Portfolio & Tech Showcase", "dir": Path(r"C:\Users\SUBBU\Downloads\hermes_phase4f_complex"), "port": 8103, "cdp_port": 9303},
    ]

    all_evidence = {}
    visual_evidence = {}

    for app in apps:
        res = await audit_application(app["key"], app["name"], app["dir"], app["port"], app["cdp_port"])
        all_evidence[app["key"]] = res
        visual_evidence[app["key"]] = {
            "app_name": app["name"],
            "viewports": res["viewports"]
        }

    # Save outputs
    func_out = ROOT / "artifacts" / "phase4g" / "browser_functional_evidence.json"
    vis_out = ROOT / "artifacts" / "phase4g" / "visual_quality_evidence.json"

    with open(func_out, "w", encoding="utf-8") as f:
        json.dump(all_evidence, f, indent=2)

    with open(vis_out, "w", encoding="utf-8") as f:
        json.dump(visual_evidence, f, indent=2)

    print("\n=======================================================")
    print("BROWSER ACCEPTANCE AUDIT COMPLETE:")
    for k, v in all_evidence.items():
        print(f"  {v['app_name']}: {'PASS' if v['overall_success'] else 'FAIL'}")
    print(f"Artifacts saved to {func_out} and {vis_out}")
    print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(main())
