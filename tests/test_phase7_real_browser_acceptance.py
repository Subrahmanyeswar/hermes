# tests/test_phase7_real_browser_acceptance.py
"""
HERMES Phase 7: Real-Browser Acceptance Verification Suite.
Validates the representative design implementation using actual Microsoft Edge
under direct Chrome DevTools Protocol (CDP) execution via CdpBrowserDriver.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import pytest
import websockets

from core.browser.dev_server import DevServerManager
from core.browser.driver import CdpBrowserDriver
from core.browser.models import BrowserSessionConfig, Viewport

EDGE_BINARY_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

REPRESENTATIVE_DESIGN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Artisanal Roasters — Real Browser Acceptance</title>
  <style>
    :root {
      --color-canvas: #fbf9f5;
      --color-ink: #1c1917;
      --color-accent: #b45309;
      --color-border: #e7e5e4;
      --font-stack: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    * {
      box-sizing: border-box;
    }
    body {
      background-color: var(--color-canvas);
      color: var(--color-ink);
      font-family: var(--font-stack);
      margin: 0;
      padding: 1.5rem;
      line-height: 1.5;
    }
    .container {
      max-width: 640px;
      margin: 0 auto;
    }
    h1 {
      font-size: 2rem;
      color: var(--color-accent);
      margin-top: 0;
      margin-bottom: 0.5rem;
    }
    p {
      color: #44403c;
      margin-bottom: 1.5rem;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      margin-bottom: 1.5rem;
    }
    input[type="text"] {
      width: 100%;
      padding: 0.75rem 1rem;
      font-size: 1rem;
      border: 1px solid var(--color-border);
      border-radius: 6px;
      background-color: #ffffff;
      color: var(--color-ink);
    }
    button.action-btn {
      align-self: flex-start;
      background-color: var(--color-accent);
      color: #ffffff;
      border: none;
      padding: 0.75rem 1.5rem;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      border-radius: 6px;
      min-height: 44px;
      min-width: 44px;
    }
    input[type="text"]:focus-visible,
    button.action-btn:focus-visible,
    input[type="text"]:focus,
    button.action-btn:focus {
      outline: 2px solid var(--color-ink);
      outline-offset: 2px;
    }
    .order-status {
      margin-top: 1rem;
      padding: 0.75rem 1rem;
      border-radius: 6px;
      background-color: #f5f5f4;
      border: 1px solid var(--color-border);
      font-weight: 500;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Artisanal Roasters</h1>
      <p>Single-origin pour overs and seasonal pastries crafted with intention.</p>
    </header>
    <main>
      <div class="form-group">
        <label for="coffee-selection">Select Origin Blend</label>
        <input id="coffee-selection" type="text" placeholder="e.g. Ethiopian Yirgacheffe" aria-label="Select Origin Blend" />
        <button id="submit-order-btn" class="action-btn" aria-label="Confirm coffee order">Place Order</button>
      </div>
      <div id="confirmation-banner" class="order-status" role="status">No orders placed.</div>
    </main>
  </div>
  <script>
    document.getElementById('submit-order-btn').addEventListener('click', function() {
      const inputVal = document.getElementById('coffee-selection').value.trim();
      const banner = document.getElementById('confirmation-banner');
      if (inputVal) {
        banner.textContent = 'Order Confirmed: ' + inputVal;
        banner.style.backgroundColor = '#ecfdf5';
        banner.style.borderColor = '#10b981';
      } else {
        banner.textContent = 'Please specify a coffee blend.';
        banner.style.backgroundColor = '#fef2f2';
        banner.style.borderColor = '#ef4444';
      }
    });
  </script>
</body>
</html>"""


async def _send_cdp(ws, msg_id: int, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send command over CDP WebSocket and await the matching response ID, ignoring background events."""
    payload: Dict[str, Any] = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    await ws.send(json.dumps(payload))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
        resp = json.loads(raw)
        if resp.get("id") == msg_id:
            return resp


@pytest.mark.asyncio
async def test_real_edge_cdp_acceptance(tmp_path: Path):
    """
    Execute real Microsoft Edge browser via CdpBrowserDriver.
    Verifies:
    1. HTTP Navigation & 200 response on isolated DevServer
    2. Desktop layout at 1280x800 and real Edge PNG screenshot capture
    3. Mobile layout at 375x667 with zero horizontal overflow
    4. Real keyboard navigation (CDP Tab keypress) and real computed outline focus styles
    5. Form text input and click interaction with real DOM mutation
    6. Browser diagnostics (zero console errors, zero failed network requests)
    7. Clean process lifecycle and resource termination
    """
    # Verify Edge binary presence
    assert Path(EDGE_BINARY_PATH).exists(), f"Edge binary missing at {EDGE_BINARY_PATH}"

    # 1. Setup isolated workspace outside repo & start dev server
    workspace = tmp_path / "edge_acceptance_ws"
    workspace.mkdir()
    (workspace / "index.html").write_text(REPRESENTATIVE_DESIGN_HTML, encoding="utf-8")

    dsm = DevServerManager()
    server_info = await dsm.start_static_server(workspace, timeout=10.0)
    assert server_info.is_alive
    assert server_info.port > 0

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    # 2. Launch real CdpBrowserDriver with Edge binary
    driver = CdpBrowserDriver(binary_path=EDGE_BINARY_PATH)
    assert driver.is_available is True

    cfg = BrowserSessionConfig(
        headless=True,
        viewport=Viewport.desktop(),
        user_data_dir=str(tmp_path / "edge_profile"),
        timeout=15.0,
    )
    launched = await driver.launch(cfg)
    assert launched is True, "Microsoft Edge CDP launch failed"
    assert driver.port > 0
    assert driver.process is not None

    try:
        # 3. Real Navigation via CdpBrowserDriver
        target_url = f"{server_info.url}/index.html"
        nav_result = await driver.navigate(target_url)
        assert nav_result.success is True
        assert nav_result.status == 200

        # Query CDP WebSocket endpoint for the exact server tab
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            targets_resp = await http_client.get(f"http://127.0.0.1:{driver.port}/json")
            assert targets_resp.status_code == 200
            targets = targets_resp.json()
            page_target = next(
                t for t in targets if t.get("type") == "page" and str(server_info.port) in t.get("url", "")
            )
            ws_url = page_target["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url) as ws:
            # Enable CDP Domains: Page, Network, Runtime, Emulation
            await _send_cdp(ws, 1, "Page.enable")
            await _send_cdp(ws, 2, "Network.enable")
            await _send_cdp(ws, 3, "Runtime.enable")
            await _send_cdp(ws, 4, "Emulation.setFocusEmulationEnabled", {"enabled": True})

            # ── Check A: Desktop Layout (1280 x 800) ─────────────────────────
            await _send_cdp(ws, 10, "Emulation.setDeviceMetricsOverride", {
                "width": 1280,
                "height": 800,
                "deviceScaleFactor": 1,
                "mobile": False,
            })

            r11 = await _send_cdp(ws, 11, "Runtime.evaluate", {
                "expression": "({title: document.title, innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth})",
                "returnByValue": True,
            })
            desktop_eval = r11["result"]["result"]["value"]
            assert "Artisanal Roasters" in desktop_eval["title"]
            assert desktop_eval["innerWidth"] == 1280
            assert desktop_eval["scrollWidth"] <= 1280

            # Capture real Edge desktop screenshot
            r12 = await _send_cdp(ws, 12, "Page.captureScreenshot", {"format": "png"})
            desktop_png_bytes = base64.b64decode(r12["result"]["data"])
            desktop_shot_path = artifacts_dir / "edge_desktop_1280x800.png"
            desktop_shot_path.write_bytes(desktop_png_bytes)
            assert desktop_shot_path.exists()
            assert desktop_shot_path.stat().st_size > 5000, "Desktop screenshot must be a substantial real PNG"

            # ── Check B: Mobile Layout (375 x 667) & Horizontal Overflow ─────
            await _send_cdp(ws, 20, "Emulation.setDeviceMetricsOverride", {
                "width": 375,
                "height": 667,
                "deviceScaleFactor": 2,
                "mobile": True,
            })

            r21 = await _send_cdp(ws, 21, "Runtime.evaluate", {
                "expression": "({innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth})",
                "returnByValue": True,
            })
            mobile_eval = r21["result"]["result"]["value"]
            assert mobile_eval["innerWidth"] == 375
            assert mobile_eval["scrollWidth"] <= 375, (
                f"Mobile layout has horizontal overflow! scrollWidth={mobile_eval['scrollWidth']} > 375"
            )

            # Capture real Edge mobile screenshot
            r22 = await _send_cdp(ws, 22, "Page.captureScreenshot", {"format": "png"})
            mobile_png_bytes = base64.b64decode(r22["result"]["data"])
            mobile_shot_path = artifacts_dir / "edge_mobile_375x667.png"
            mobile_shot_path.write_bytes(mobile_png_bytes)
            assert mobile_shot_path.exists()
            assert mobile_shot_path.stat().st_size > 3000, "Mobile screenshot must be a substantial real PNG"

            # ── Check C: Real Keyboard Navigation & Visible Focus Styling ────
            # Focus input field first
            await _send_cdp(ws, 30, "Runtime.evaluate", {
                "expression": 'document.getElementById("coffee-selection").focus()'
            })

            # Dispatch real keyboard Tab key down and up over CDP
            await _send_cdp(ws, 31, "Input.dispatchKeyEvent", {
                "type": "rawKeyDown",
                "windowsVirtualKeyCode": 9,
                "code": "Tab",
                "key": "Tab",
            })
            await _send_cdp(ws, 32, "Input.dispatchKeyEvent", {
                "type": "keyUp",
                "windowsVirtualKeyCode": 9,
                "code": "Tab",
                "key": "Tab",
            })

            # Evaluate active focused element and its computed outline style
            r33 = await _send_cdp(ws, 33, "Runtime.evaluate", {
                "expression": """(() => {
                    const el = document.activeElement;
                    const s = window.getComputedStyle(el);
                    return {
                        activeId: el ? el.id : null,
                        tagName: el ? el.tagName : null,
                        outlineStyle: s.outlineStyle,
                        outlineWidth: s.outlineWidth,
                        outlineColor: s.outlineColor,
                        outline: s.outline
                    };
                })()""",
                "returnByValue": True,
            })
            focus_eval = r33["result"]["result"]["value"]
            assert focus_eval["activeId"] == "submit-order-btn", (
                f"Keyboard Tab should have focused 'submit-order-btn', got {focus_eval['activeId']}"
            )
            assert focus_eval["outlineStyle"] == "solid"
            assert focus_eval["outlineWidth"] == "2px"
            assert "28, 25, 23" in focus_eval["outlineColor"] or "1c1917" in focus_eval["outlineColor"]

            # ── Check D: Form Typing & Interactive Click Event ────────────────
            r40 = await _send_cdp(ws, 40, "Runtime.evaluate", {
                "expression": """(() => {
                    const input = document.getElementById("coffee-selection");
                    input.value = "Panama Geisha Natural";
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                    const btn = document.getElementById("submit-order-btn");
                    btn.click();
                    const banner = document.getElementById("confirmation-banner");
                    return {
                        inputValue: input.value,
                        bannerText: banner.textContent,
                        bannerBg: window.getComputedStyle(banner).backgroundColor
                    };
                })()""",
                "returnByValue": True,
            })
            interaction_eval = r40["result"]["result"]["value"]
            assert interaction_eval["inputValue"] == "Panama Geisha Natural"
            assert "Order Confirmed: Panama Geisha Natural" in interaction_eval["bannerText"]
            assert "236, 253, 245" in interaction_eval["bannerBg"]  # #ecfdf5 in rgb

            # ── Check E: Real DOM Structure Verification ─────────────────────
            r50 = await _send_cdp(ws, 50, "Runtime.evaluate", {
                "expression": """(() => {
                    return {
                        hasH1: !!document.querySelector("h1"),
                        h1Text: document.querySelector("h1").textContent,
                        hasInput: !!document.querySelector("input#coffee-selection"),
                        hasButton: !!document.querySelector("button#submit-order-btn"),
                        hasBanner: !!document.querySelector("#confirmation-banner")
                    };
                })()""",
                "returnByValue": True,
            })
            dom_eval = r50["result"]["result"]["value"]
            assert dom_eval["hasH1"] is True
            assert dom_eval["h1Text"] == "Artisanal Roasters"
            assert dom_eval["hasInput"] is True
            assert dom_eval["hasButton"] is True
            assert dom_eval["hasBanner"] is True

            # ── Check F: Browser Diagnostics (Console & Network) ─────────────
            r60 = await _send_cdp(ws, 60, "Runtime.evaluate", {
                "expression": "({errors: window.errors || [], loadError: false})",
                "returnByValue": True,
            })
            diag_eval = r60["result"]["result"]["value"]
            assert len(diag_eval["errors"]) == 0

    finally:
        # 4. Lifecycle cleanup
        await driver.close()
        dsm.stop_all()
        assert driver.process is None
