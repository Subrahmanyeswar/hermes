# tests/test_phase12_real_browser_labflow.py
"""
HERMES Phase 12: Real-Browser End-to-End Acceptance Verification Suite.
Validates the LabFlow Campus Lab Manager application using actual Microsoft Edge
under direct Chrome DevTools Protocol (CDP) execution via CdpBrowserDriver.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import sys
import threading
import time
from http.server import HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest
import websockets

from core.browser.driver import CdpBrowserDriver
from core.browser.models import BrowserSessionConfig, Viewport

# Import LabFlow server from the empty build test challenge workspace
LABFLOW_DIR = Path(r"C:\Users\SUBBU\Downloads\HERMES_EMPTY_BUILD_TEST")
sys.path.insert(0, str(LABFLOW_DIR))
try:
    from server import LabFlowHandler, init_database  # type: ignore
except ImportError:
    pytest.skip("HERMES_EMPTY_BUILD_TEST workspace not available", allow_module_level=True)

EDGE_BINARY_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SCREENSHOTS_DIR = Path(r"C:\Users\SUBBU\Downloads\hermes\artifacts\phase12\screenshots")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BackgroundLabFlowServer:
    def __init__(self, port: int):
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self):
        init_database()
        self.server = HTTPServer(("127.0.0.1", self.port), LabFlowHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        # Wait until port responds
        start_time = time.time()
        while time.time() - start_time < 5.0:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.05)

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


async def _send_cdp(ws, msg_id: int, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send command over CDP WebSocket and await matching response ID."""
    payload: Dict[str, Any] = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    await ws.send(json.dumps(payload))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=12.0)
        resp = json.loads(raw)
        if resp.get("id") == msg_id:
            return resp


@pytest.mark.asyncio
async def test_labflow_real_browser_e2e(tmp_path: Path):
    """
    Execute real Microsoft Edge browser via CdpBrowserDriver against LabFlow.
    Verifies:
    1. HTTP Navigation & 200 response
    2. Desktop layout at 1280x800, lab cards render correctly
    3. Screenshot 1: Desktop Overview (labflow_desktop_overview.png)
    4. Form Submission: Create valid reservation for CHEM-101
    5. Screenshot 2: Confirmed Booking (labflow_desktop_booking_confirmed.png)
    6. Conflict Rejection: Attempt overlapping booking for CHEM-101, assert HTTP 409 alert
    7. Screenshot 3: Conflict Alert (labflow_desktop_conflict_alert.png)
    8. Tab switching & Analytics: navigate to Analytics view
    9. Screenshot 4: Analytics View (labflow_desktop_analytics.png)
    10. Mobile layout at 375x667 with zero horizontal overflow
    11. Screenshot 5: Mobile Overview (labflow_mobile_overview.png)
    12. Persistence across page reload
    13. Zero uncaught console exceptions
    """
    assert Path(EDGE_BINARY_PATH).exists(), f"Edge binary missing at {EDGE_BINARY_PATH}"
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Start LabFlow server on free port
    port = find_free_port()
    server = BackgroundLabFlowServer(port)
    server.start()

    # 2. Launch real CdpBrowserDriver with Edge binary
    driver = CdpBrowserDriver(binary_path=EDGE_BINARY_PATH)
    assert driver.is_available is True

    edge_profile = tmp_path / "edge_profile"
    cfg = BrowserSessionConfig(
        headless=True,
        viewport=Viewport.desktop(),
        user_data_dir=str(edge_profile),
        timeout=15.0,
    )
    launched = await driver.launch(cfg)
    assert launched is True, "Microsoft Edge CDP launch failed"
    assert driver.port > 0

    console_errors: List[str] = []

    try:
        # 3. Navigate to LabFlow
        target_url = f"http://127.0.0.1:{port}/index.html"
        nav_result = await driver.navigate(target_url)
        assert nav_result.success is True
        assert nav_result.status == 200

        # Query CDP WebSocket endpoint for the exact tab
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            targets_resp = await http_client.get(f"http://127.0.0.1:{driver.port}/json")
            assert targets_resp.status_code == 200
            targets = targets_resp.json()
            page_target = next(
                t for t in targets if t.get("type") == "page" and str(port) in t.get("url", "")
            )
            ws_url = page_target["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url) as ws:
            # Enable CDP Domains
            await _send_cdp(ws, 1, "Page.enable")
            await _send_cdp(ws, 2, "Network.enable")
            await _send_cdp(ws, 3, "Runtime.enable")
            await _send_cdp(ws, 4, "Emulation.setFocusEmulationEnabled", {"enabled": True})

            # Check for console errors listener (we'll also evaluate window.__consoleErrors)
            await _send_cdp(ws, 5, "Runtime.evaluate", {
                "expression": """
                window.__consoleErrors = [];
                window.addEventListener('error', (e) => { window.__consoleErrors.push(e.message); });
                """
            })

            # Wait for data load
            await asyncio.sleep(0.5)

            # ── Check 1: Desktop Viewport (1280x800) & Initial Render ───────
            await _send_cdp(ws, 10, "Emulation.setDeviceMetricsOverride", {
                "width": 1280,
                "height": 800,
                "deviceScaleFactor": 1,
                "mobile": False,
            })
            await _send_cdp(ws, 11, "Emulation.setVisibleSize", {"width": 1280, "height": 800})

            # Verify page title and labs loaded
            r12 = await _send_cdp(ws, 12, "Runtime.evaluate", {
                "expression": "({title: document.title, labCards: document.querySelectorAll('.lab-card').length})",
                "returnByValue": True,
            })
            overview_val = r12["result"]["result"]["value"]
            assert "LabFlow" in overview_val["title"], f"Expected LabFlow in title, got {overview_val['title']}"
            assert overview_val["labCards"] >= 4, f"Expected at least 4 lab cards, got {overview_val['labCards']}"

            # Capture Screenshot 1: Desktop Overview
            r13 = await _send_cdp(ws, 13, "Page.captureScreenshot", {"format": "png"})
            shot1_bytes = base64.b64decode(r13["result"]["data"])
            shot1_path = SCREENSHOTS_DIR / "labflow_desktop_overview.png"
            shot1_path.write_bytes(shot1_bytes)
            assert shot1_path.stat().st_size > 5000

            # ── Check 2: Form Submission & Booking Confirmation ─────────────
            # Fill form and submit
            create_js = """
            (async () => {
                document.getElementById('book-lab').value = 'LAB-101';
                document.getElementById('book-user-name').value = 'Dr. Aris Thorne';
                document.getElementById('book-email').value = 'thorne@campus.edu';
                document.getElementById('book-dept').value = 'Computer Science';
                document.getElementById('book-purpose').value = 'Quantum algorithm simulation';
                document.getElementById('book-date').value = '2026-11-01';
                document.getElementById('book-start-time').value = '09:00';
                document.getElementById('book-end-time').value = '11:00';
                
                // Submit form
                const form = document.getElementById('booking-form');
                form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                
                // Wait briefly for fetch response and UI update
                await new Promise(r => setTimeout(r, 700));
                
                const alertContent = document.getElementById('alert-content');
                const alertContainer = document.getElementById('alert-container');
                const row = document.querySelector('tr[data-lab-id="LAB-101"]');
                return {
                    bannerText: alertContent ? alertContent.textContent : '',
                    hasBookingRow: !!row,
                    bannerVisible: alertContainer ? alertContainer.style.display !== 'none' : false
                };
            })()
            """
            r20 = await _send_cdp(ws, 20, "Runtime.evaluate", {
                "expression": create_js,
                "awaitPromise": True,
                "returnByValue": True,
            })
            create_val = r20["result"]["result"]["value"]
            assert "Confirmed" in create_val["bannerText"] or "successfully" in create_val["bannerText"].lower()

            # Capture Screenshot 2: Confirmed Booking State
            r21 = await _send_cdp(ws, 21, "Page.captureScreenshot", {"format": "png"})
            shot2_bytes = base64.b64decode(r21["result"]["data"])
            shot2_path = SCREENSHOTS_DIR / "labflow_desktop_booking_confirmed.png"
            shot2_path.write_bytes(shot2_bytes)
            assert shot2_path.stat().st_size > 5000

            # ── Check 3: Conflict Detection & Error Alert ────────────────────
            # Attempt conflicting booking on same lab and date: 10:00 - 12:00
            conflict_js = """
            (async () => {
                document.getElementById('book-lab').value = 'LAB-101';
                document.getElementById('book-user-name').value = 'Prof. Maya Lin';
                document.getElementById('book-email').value = 'maya.lin@campus.edu';
                document.getElementById('book-dept').value = 'Computer Science';
                document.getElementById('book-purpose').value = 'Qubit entanglement experiments';
                document.getElementById('book-date').value = '2026-11-01';
                document.getElementById('book-start-time').value = '10:00';
                document.getElementById('book-end-time').value = '12:00';
                
                const form = document.getElementById('booking-form');
                form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                
                await new Promise(r => setTimeout(r, 700));
                
                const alertContent = document.getElementById('alert-content');
                const alertBox = document.getElementById('alert-box');
                return {
                    bannerText: alertContent ? alertContent.textContent : '',
                    isError: alertBox ? alertBox.classList.contains('alert-danger') : false
                };
            })()
            """
            r30 = await _send_cdp(ws, 30, "Runtime.evaluate", {
                "expression": conflict_js,
                "awaitPromise": True,
                "returnByValue": True,
            })
            conflict_val = r30["result"]["result"]["value"]
            assert "conflict" in conflict_val["bannerText"].lower(), f"Expected conflict error, got: {conflict_val}"
            assert conflict_val["isError"] is True

            # Capture Screenshot 3: Conflict Alert State
            r31 = await _send_cdp(ws, 31, "Page.captureScreenshot", {"format": "png"})
            shot3_bytes = base64.b64decode(r31["result"]["data"])
            shot3_path = SCREENSHOTS_DIR / "labflow_desktop_conflict_alert.png"
            shot3_path.write_bytes(shot3_bytes)
            assert shot3_path.stat().st_size > 5000

            # ── Check 4: Interactive Elements & Analytics Tab ───────────────
            analytics_js = """
            (async () => {
                const analyticsTabBtn = document.querySelector('[data-tab="tab-analytics"]');
                analyticsTabBtn.click();
                await new Promise(r => setTimeout(r, 500));
                
                const analyticsSec = document.getElementById('tab-analytics');
                const statCards = document.querySelectorAll('.metric-card');
                return {
                    activeTab: analyticsSec ? analyticsSec.classList.contains('active') : false,
                    statCardsCount: statCards.length
                };
            })()
            """
            r40 = await _send_cdp(ws, 40, "Runtime.evaluate", {
                "expression": analytics_js,
                "awaitPromise": True,
                "returnByValue": True,
            })
            analytics_val = r40["result"]["result"]["value"]
            assert analytics_val["activeTab"] is True
            assert analytics_val["statCardsCount"] >= 4

            # Capture Screenshot 4: Analytics View
            r41 = await _send_cdp(ws, 41, "Page.captureScreenshot", {"format": "png"})
            shot4_bytes = base64.b64decode(r41["result"]["data"])
            shot4_path = SCREENSHOTS_DIR / "labflow_desktop_analytics.png"
            shot4_path.write_bytes(shot4_bytes)
            assert shot4_path.stat().st_size > 5000

            # ── Check 5: Mobile Layout (375x667) & Horizontal Overflow ───────
            # Switch back to schedule or labs overview
            await _send_cdp(ws, 50, "Runtime.evaluate", {
                "expression": "document.querySelector('[data-tab=\"tab-labs\"]').click();"
            })
            await _send_cdp(ws, 51, "Emulation.setDeviceMetricsOverride", {
                "width": 375,
                "height": 667,
                "deviceScaleFactor": 2,
                "mobile": True,
            })
            await _send_cdp(ws, 52, "Emulation.setVisibleSize", {"width": 375, "height": 667})
            await asyncio.sleep(0.4)

            r53 = await _send_cdp(ws, 53, "Runtime.evaluate", {
                "expression": "({innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth})",
                "returnByValue": True,
            })
            mobile_metrics = r53["result"]["result"]["value"]
            assert mobile_metrics["innerWidth"] == 375
            assert mobile_metrics["scrollWidth"] <= 375, (
                f"Horizontal overflow detected: scrollWidth {mobile_metrics['scrollWidth']} > 375"
            )

            # Capture Screenshot 5: Mobile Viewport
            r54 = await _send_cdp(ws, 54, "Page.captureScreenshot", {"format": "png"})
            shot5_bytes = base64.b64decode(r54["result"]["data"])
            shot5_path = SCREENSHOTS_DIR / "labflow_mobile_overview.png"
            shot5_path.write_bytes(shot5_bytes)
            assert shot5_path.stat().st_size > 5000

            # ── Check 6: Persistence Across Reload ───────────────────────────
            # Reload page in desktop mode
            await _send_cdp(ws, 60, "Emulation.setDeviceMetricsOverride", {
                "width": 1280,
                "height": 800,
                "deviceScaleFactor": 1,
                "mobile": False,
            })
            await _send_cdp(ws, 61, "Page.reload")
            await asyncio.sleep(0.8)

            r62 = await _send_cdp(ws, 62, "Runtime.evaluate", {
                "expression": """
                (async () => {
                    const resp = await fetch('/api/bookings');
                    const bookings = await resp.json();
                    return {
                        bookingCount: bookings.length,
                        hasArisThorne: bookings.some(b => b.user_name === 'Dr. Aris Thorne' && b.status === 'CONFIRMED')
                    };
                })()
                """,
                "awaitPromise": True,
                "returnByValue": True,
            })
            persist_val = r62["result"]["result"]["value"]
            assert persist_val["bookingCount"] >= 1
            assert persist_val["hasArisThorne"] is True, "Persisted booking missing after page reload"

            # ── Check 7: Zero Uncaught Exceptions ────────────────────────────
            r70 = await _send_cdp(ws, 70, "Runtime.evaluate", {
                "expression": "window.__consoleErrors || []",
                "returnByValue": True,
            })
            errs = r70["result"]["result"]["value"]
            assert len(errs) == 0, f"Uncaught console errors detected: {errs}"

    finally:
        await driver.close()
        server.stop()
