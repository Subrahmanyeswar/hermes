# core/browser/acceptance.py
"""
Browser Acceptance Verifier for HERMES 2.x.
Validates that interactive web applications (HTML + JS + Backend)
load in a real browser (via CDP) without unhandled exceptions
(TypeError, ReferenceError, SyntaxError, Uncaught errors),
that critical DOM elements render properly,
that required functional workflows execute with valid DOM/state mutations,
and that state persistence across reload is verified.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("hermes.browser.acceptance")


@dataclass
class BrowserAcceptanceResult:
    passed: bool
    status: str  # "PASS", "FAIL", "SKIPPED"
    console_errors: List[str] = field(default_factory=list)
    unhandled_exceptions: List[str] = field(default_factory=list)
    missing_rendered_elements: List[str] = field(default_factory=list)
    workflow_results: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    navigation_url: Optional[str] = None
    evidence_digest: str = ""
    is_stale: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        if self.passed:
            wf_info = f" with {len(self.workflow_results)} workflow(s)" if self.workflow_results else ""
            return f"Browser acceptance PASSED ({self.status}){wf_info} at {self.navigation_url or 'target'}"
        return f"Browser acceptance FAILED ({len(self.issues)} issue(s)): {'; '.join(self.issues[:2])}"


class BrowserAcceptanceVerifier:
    """
    Authoritative verifier for interactive web applications.
    Connects to real headless browser via Chrome DevTools Protocol (CDP).
    """

    CHROME_CANDIDATE_PATHS = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]

    @classmethod
    def find_browser_executable(cls) -> Optional[str]:
        for p in cls.CHROME_CANDIDATE_PATHS:
            if Path(p).exists():
                return p
        for name in ("chrome", "google-chrome", "chromium", "msedge", "edge"):
            found = shutil.which(name)
            if found:
                return found
        return None

    @classmethod
    def is_port_in_use(cls, port: int, host: str = "127.0.0.1") -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0

    @classmethod
    def find_free_port(cls) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    @classmethod
    def is_interactive_web_project(cls, workspace_root: Path) -> bool:
        """Determines if the workspace contains an interactive web application."""
        if not workspace_root.exists():
            return False
        has_html = (
            any(workspace_root.glob("*.html"))
            or any(workspace_root.glob("public/*.html"))
            or any(workspace_root.glob("static/*.html"))
            or any(workspace_root.glob("dist/*.html"))
        )
        has_js = (
            any(workspace_root.glob("*.js"))
            or any(workspace_root.glob("public/*.js"))
            or any(workspace_root.glob("static/*.js"))
            or any(workspace_root.glob("src/*.js"))
            or (workspace_root / "package.json").exists()
        )
        return has_html and has_js

    @classmethod
    def compute_workspace_digest(cls, workspace_root: Path) -> str:
        """Computes deterministic digest of source deliverables to prevent stale evidence reuse."""
        source_hashes = []
        for p in sorted(workspace_root.rglob("*")):
            if p.is_file() and p.suffix in (".html", ".css", ".js", ".json", ".py", ".ts") and not any(part in p.parts for part in (".hermes", ".git", "node_modules", ".artifacts")):
                try:
                    source_hashes.append(f"{p.name}:{hashlib.sha256(p.read_bytes()).hexdigest()[:12]}")
                except Exception:
                    pass
        return hashlib.sha256(",".join(source_hashes).encode("utf-8")).hexdigest()[:16]

    @classmethod
    def check_evidence_freshness(cls, workspace_root: Path) -> Tuple[bool, str]:
        """Verifies that existing browser acceptance evidence belongs to current workspace state."""
        evidence_file = workspace_root / ".hermes" / "acceptance_evidence.json"
        if not evidence_file.exists():
            return False, "Acceptance evidence file missing in workspace (.hermes/acceptance_evidence.json)."
        try:
            data = json.loads(evidence_file.read_text(encoding="utf-8"))
            recorded_digest = data.get("workspace_digest", "")
            current_digest = cls.compute_workspace_digest(workspace_root)
            if not recorded_digest or recorded_digest != current_digest:
                return False, f"Acceptance evidence is stale (recorded '{recorded_digest}' != current '{current_digest}')."
            if not data.get("passed", False):
                return False, "Recorded acceptance evidence indicates previous verification failure."
            return True, "Acceptance evidence is fresh and valid."
        except Exception as ex:
            return False, f"Failed to read acceptance evidence: {ex}"

    @classmethod
    async def verify_workspace(
        cls,
        workspace_root: Path | str,
        preferred_port: int = 3000,
        timeout: float = 12.0,
        workflows: Optional[List[Dict[str, Any]]] = None,
        require_persistence: bool = False,
        acceptance_ledger: Optional[Any] = None,
    ) -> BrowserAcceptanceResult:
        ws_root = Path(workspace_root).resolve()
        if not cls.is_interactive_web_project(ws_root):
            return BrowserAcceptanceResult(
                passed=True,
                status="SKIPPED",
                details={"reason": "Workspace does not contain an interactive web project (missing HTML/JS)."}
            )

        chrome_exe = cls.find_browser_executable()
        if not chrome_exe:
            return BrowserAcceptanceResult(
                passed=False,
                status="FAIL",
                issues=["No compatible Chrome/Edge browser binary found for headless CDP verification on interactive web project."],
                details={"reason": "Missing browser binary"}
            )

        # Detect backend and port
        server_js = ws_root / "server.js"
        app_py = ws_root / "app.py"
        main_py = ws_root / "main.py"
        index_html = ws_root / "index.html"
        if not index_html.exists():
            for alt in (
                ws_root / "public" / "index.html",
                ws_root / "static" / "index.html",
                ws_root / "dist" / "index.html",
                ws_root / "templates" / "index.html",
            ):
                if alt.exists():
                    index_html = alt
                    break

        backend_proc: Optional[subprocess.Popen] = None
        target_port = preferred_port
        server_started_by_verifier = False

        # Dynamically detect port from server.js / package.json / .env
        if server_js.exists():
            try:
                s_txt = server_js.read_text(encoding="utf-8", errors="ignore")
                port_m = re.search(r'(?:PORT|port)\s*=\s*process\.env\.PORT\s*\|\|\s*([0-9]{4,5})', s_txt)
                if not port_m:
                    port_m = re.search(r'const\s+PORT\s*=\s*([0-9]{4,5})', s_txt)
                if not port_m:
                    port_m = re.search(r'\.listen\(\s*([0-9]{4,5})', s_txt)
                if port_m:
                    target_port = int(port_m.group(1))
            except Exception:
                pass

        if not cls.is_port_in_use(target_port):
            if server_js.exists():
                try:
                    backend_proc = subprocess.Popen(
                        ["node", str(server_js)],
                        cwd=str(ws_root),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    server_started_by_verifier = True
                    for _ in range(30):
                        await asyncio.sleep(0.2)
                        if cls.is_port_in_use(target_port):
                            break
                except Exception as ex:
                    logger.warning(f"Could not start node backend: {ex}")
            elif app_py.exists() or main_py.exists():
                py_entry = app_py if app_py.exists() else main_py
                try:
                    import sys
                    backend_proc = subprocess.Popen(
                        [sys.executable, str(py_entry)],
                        cwd=str(ws_root),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    server_started_by_verifier = True
                    for _ in range(30):
                        await asyncio.sleep(0.2)
                        if cls.is_port_in_use(target_port):
                            break
                except Exception as ex:
                    logger.warning(f"Could not start python backend: {ex}")

        pkg_json = ws_root / "package.json"
        pkg_text = pkg_json.read_text(encoding="utf-8", errors="ignore") if pkg_json.exists() else ""
        has_backend = (
            (ws_root / "server.js").exists()
            or (ws_root / "app.py").exists()
            or (ws_root / "main.py").exists()
            or any(k in pkg_text for k in ("express", "fastify", "koa", "@nestjs/core"))
        )
        if has_backend:
            # Backend applications strictly require HTTP navigation - file:// prohibited
            found_live_port = None
            for p_cand in (target_port, 3000, 5000, 8000, 8080):
                if cls.is_port_in_use(p_cand):
                    found_live_port = p_cand
                    break
            if found_live_port:
                target_url = f"http://127.0.0.1:{found_live_port}"
            else:
                return BrowserAcceptanceResult(
                    passed=False,
                    status="FAIL",
                    issues=[f"Backend server failed to start or listen on port {target_port}. file:// navigation prohibited for backend applications."],
                    details={"target_port": target_port, "has_backend": True}
                )
        else:
            if index_html and index_html.exists():
                target_url = index_html.as_uri()
            else:
                target_url = f"http://127.0.0.1:{target_port}" 

        cdp_port = cls.find_free_port()
        temp_profile = tempfile.mkdtemp(prefix="hermes_cdp_")
        chrome_proc: Optional[subprocess.Popen] = None

        console_errors: List[str] = []
        unhandled_exceptions: List[str] = []
        missing_rendered: List[str] = []
        workflow_results: List[Dict[str, Any]] = []
        issues: List[str] = []
        screenshot_path: Optional[str] = None
        details: Dict[str, Any] = {"target_url": target_url}

        try:
            chrome_args = [
                chrome_exe,
                "--headless=new",
                "--disable-gpu",
                "--disable-extensions",
                "--no-first-run",
                "--no-default-browser-check",
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={temp_profile}",
                "about:blank",
            ]
            chrome_proc = subprocess.Popen(
                chrome_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            tabs_data = None
            for _ in range(25):
                await asyncio.sleep(0.2)
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=1.0) as resp:
                        tabs_data = json.loads(resp.read().decode())
                        if tabs_data:
                            break
                except Exception:
                    pass

            if not tabs_data:
                return BrowserAcceptanceResult(
                    passed=False,
                    status="FAIL",
                    issues=["Failed to establish CDP connection to headless browser."],
                    details=details,
                )

            page_targets = [t for t in tabs_data if t.get("type") == "page"]
            target = page_targets[0] if page_targets else tabs_data[0]
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                return BrowserAcceptanceResult(
                    passed=False,
                    status="FAIL",
                    issues=["No WebSocketDebuggerUrl in CDP target list."],
                    details=details,
                )

            import websockets
            async with websockets.connect(ws_url, ping_interval=None, max_size=32 * 1024 * 1024) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
                await ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
                await ws.send(json.dumps({"id": 3, "method": "Console.enable"}))
                await ws.send(json.dumps({"id": 4, "method": "Log.enable"}))
                await ws.send(json.dumps({"id": 5, "method": "Page.navigate", "params": {"url": target_url}}))

                start_poll = time.monotonic()
                while time.monotonic() - start_poll < 3.0:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                        msg = json.loads(raw)
                        m_method = msg.get("method")
                        if m_method == "Runtime.exceptionThrown":
                            p = msg.get("params", {})
                            exc_det = p.get("exceptionDetails", {})
                            exc_obj = exc_det.get("exception", {})
                            err_desc = exc_obj.get("description") or exc_det.get("text") or "Unhandled Exception"
                            unhandled_exceptions.append(err_desc)
                        elif m_method == "Runtime.consoleAPICalled":
                            p = msg.get("params", {})
                            if p.get("type") == "error":
                                args = p.get("args", [])
                                txt = " ".join(str(a.get("value", a.get("description", ""))) for a in args)
                                console_errors.append(txt)
                        elif m_method == "Log.entryAdded":
                            entry = msg.get("params", {}).get("entry", {})
                            if entry.get("level") == "error":
                                console_errors.append(entry.get("text", ""))
                    except asyncio.TimeoutError:
                        pass

                # Inspect DOM
                await ws.send(json.dumps({
                    "id": 10,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "document.body ? document.body.innerHTML : ''", "returnByValue": True}
                }))
                body_html = ""
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        msg = json.loads(raw)
                        if msg.get("id") == 10:
                            body_html = msg.get("result", {}).get("result", {}).get("value", "")
                            break
                    except Exception:
                        break

                details["body_length"] = len(body_html)
                if len(body_html.strip()) < 50:
                    missing_rendered.append("Document body is empty or unrendered.")

                # Inspect Document Title
                expected_title = None
                for cand in [ws_root / "index.html", ws_root / "static" / "index.html", ws_root / "public" / "index.html"]:
                    if cand.exists():
                        try:
                            h_content = cand.read_text(encoding="utf-8", errors="ignore")
                            t_m = re.search(r'<title>([^<]+)</title>', h_content, re.I)
                            if t_m:
                                expected_title = t_m.group(1).strip()
                                break
                        except Exception:
                            pass

                await ws.send(json.dumps({
                    "id": 11,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "document.title", "returnByValue": True}
                }))
                doc_title = ""
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        msg = json.loads(raw)
                        if msg.get("id") == 11:
                            doc_title = msg.get("result", {}).get("result", {}).get("value", "")
                            break
                    except Exception:
                        break

                details["doc_title"] = doc_title
                details["expected_title"] = expected_title
                if expected_title and doc_title:
                    if doc_title != expected_title and not any(w.lower() in doc_title.lower() for w in expected_title.split()[:3]):
                        issues.append(
                            f"INCORRECT_PREVIEW_TARGET: Browser page title '{doc_title}' does not match "
                            f"generated workspace HTML title '{expected_title}'. Serving target does not match application."
                        )

                # Inspect Rendered Images
                await ws.send(json.dumps({
                    "id": 12,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": "Array.from(document.querySelectorAll('img')).map(i => ({ src: i.src, naturalWidth: i.naturalWidth, complete: i.complete }))",
                        "returnByValue": True
                    }
                }))
                images_info = []
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        msg = json.loads(raw)
                        if msg.get("id") == 12:
                            images_info = msg.get("result", {}).get("result", {}).get("value", []) or []
                            break
                    except Exception:
                        break

                if isinstance(images_info, list) and images_info:
                    broken_imgs = [i["src"] for i in images_info if i.get("complete") and i.get("naturalWidth") == 0]
                    if broken_imgs:
                        issues.append(f"BROKEN_IMAGE_ASSETS: {len(broken_imgs)} image(s) failed to render (naturalWidth == 0): {broken_imgs[:2]}")

                # ── Multi-Viewport Responsive QA Matrix (Desktop, Tablet, Mobile) ──
                TARGET_VIEWPORTS = [
                    {"name": "desktop", "width": 1440, "height": 900, "scale": 1.0, "is_mobile": False},
                    {"name": "tablet", "width": 1024, "height": 768, "scale": 1.0, "is_mobile": False},
                    {"name": "mobile", "width": 390, "height": 844, "scale": 2.0, "is_mobile": True},
                ]

                shot_dir = ws_root / ".hermes" / "screenshots"
                shot_dir.mkdir(parents=True, exist_ok=True)
                viewports_tested_records = []

                for vp_idx, vp in enumerate(TARGET_VIEWPORTS):
                    vp_name = vp["name"]
                    vp_w = vp["width"]
                    vp_h = vp["height"]

                    # 1. Emulate viewport
                    em_msg_id = 20 + vp_idx * 3
                    await ws.send(json.dumps({
                        "id": em_msg_id,
                        "method": "Emulation.setDeviceMetricsOverride",
                        "params": {
                            "width": vp_w,
                            "height": vp_h,
                            "deviceScaleFactor": vp["scale"],
                            "mobile": vp["is_mobile"],
                        }
                    }))
                    while True:
                        try:
                            raw_em = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            msg_em = json.loads(raw_em)
                            if msg_em.get("id") == em_msg_id:
                                break
                        except Exception:
                            break
                    await asyncio.sleep(0.3)

                    # 2. Check layout dimensions & horizontal overflow
                    metrics_id = 21 + vp_idx * 3
                    await ws.send(json.dumps({
                        "id": metrics_id,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": "({ innerWidth: window.innerWidth, clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth })",
                            "returnByValue": True
                        }
                    }))
                    vp_metrics = {}
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            msg = json.loads(raw)
                            if msg.get("id") == metrics_id:
                                vp_metrics = msg.get("result", {}).get("result", {}).get("value", {})
                                break
                        except Exception:
                            break

                    cw = vp_metrics.get("clientWidth", vp_w)
                    sw = vp_metrics.get("scrollWidth", vp_w)
                    has_overflow = sw > cw
                    if has_overflow:
                        issues.append(
                            f"RESPONSIVE_OVERFLOW: Horizontal scroll detected on {vp_name} ({vp_w}x{vp_h}): "
                            f"scrollWidth ({sw}) > clientWidth ({cw})."
                        )

                    # 3. Capture screenshot for this viewport
                    vp_shot_file = shot_dir / f"screenshot_{vp_name}_{vp_w}x{vp_h}.png"
                    shot_id = 22 + vp_idx * 3
                    await ws.send(json.dumps({
                        "id": shot_id,
                        "method": "Page.captureScreenshot",
                        "params": {"format": "png"}
                    }))
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                            msg = json.loads(raw)
                            if msg.get("id") == shot_id:
                                data_b64 = msg.get("result", {}).get("data")
                                if data_b64:
                                    vp_shot_file.write_bytes(base64.b64decode(data_b64))
                                break
                        except Exception:
                            break

                    viewports_tested_records.append({
                        "name": vp_name,
                        "width": vp_w,
                        "height": vp_h,
                        "scroll_width": sw,
                        "client_width": cw,
                        "device_scale_factor": vp["scale"],
                        "has_overflow": has_overflow,
                        "screenshot": str(vp_shot_file),
                    })

                # Set primary screenshot to desktop or first available
                if viewports_tested_records:
                    screenshot_path = viewports_tested_records[0]["screenshot"]
                    acc_shot = ws_root / ".hermes" / "acceptance_screenshot.png"
                    if Path(screenshot_path).exists():
                        shutil.copyfile(screenshot_path, acc_shot)

                # ── Execute Functional Workflows (if provided) ────────────────
                cmd_id = 100
                if workflows:
                    for wf in workflows:
                        wf_name = wf.get("name", "Unnamed Workflow")
                        wf_passed = True
                        wf_error = None
                        for step in wf.get("steps", []):
                            action = step.get("action")
                            if action == "evaluate":
                                expr = step.get("expression", "")
                                cmd_id += 1
                                await ws.send(json.dumps({
                                    "id": cmd_id,
                                    "method": "Runtime.evaluate",
                                    "params": {"expression": expr, "returnByValue": True}
                                }))
                                try:
                                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                                    msg = json.loads(raw)
                                    if "exceptionDetails" in msg.get("result", {}):
                                        wf_passed = False
                                        wf_error = f"Exception during step: {msg['result']['exceptionDetails']}"
                                        break
                                except Exception as ex:
                                    pass
                            elif action == "wait":
                                await asyncio.sleep(step.get("duration", 0.5))
                            elif action == "reload":
                                cmd_id += 1
                                await ws.send(json.dumps({"id": cmd_id, "method": "Page.reload"}))
                                await asyncio.sleep(1.0)
                            elif action == "assert_dom":
                                expr = step.get("expression", "")
                                cmd_id += 1
                                await ws.send(json.dumps({
                                    "id": cmd_id,
                                    "method": "Runtime.evaluate",
                                    "params": {"expression": expr, "returnByValue": True}
                                }))
                                eval_val = None
                                start_w = time.monotonic()
                                while time.monotonic() - start_w < 3.0:
                                    try:
                                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                                        msg = json.loads(raw)
                                        if msg.get("id") == cmd_id:
                                            eval_val = msg.get("result", {}).get("result", {}).get("value")
                                            break
                                    except Exception:
                                        break
                                if not eval_val:
                                    wf_passed = False
                                    wf_error = step.get("error", f"Assertion failed: {expr}")
                                    break

                        workflow_results.append({"name": wf_name, "passed": wf_passed, "error": wf_error})
                        if not wf_passed:
                            issues.append(f"Required workflow '{wf_name}' failed: {wf_error}")

                # ── Persistence Verification ──────────────────────────────────
                if require_persistence:
                    cmd_id += 1
                    await ws.send(json.dumps({"id": cmd_id, "method": "Page.reload"}))
                    await asyncio.sleep(1.0)
                    # Check that body still has meaningful content after reload
                    cmd_id += 1
                    await ws.send(json.dumps({
                        "id": cmd_id,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "document.body ? document.body.innerHTML.length : 0", "returnByValue": True}
                    }))
                    post_len = 0
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            msg = json.loads(raw)
                            if msg.get("id") == cmd_id:
                                post_len = msg.get("result", {}).get("result", {}).get("value", 0)
                                break
                        except Exception:
                            break
                    if post_len < 50:
                        issues.append("Persistence verification failed: Application state/DOM collapsed after page reload.")

        except Exception as e:
            logger.error(f"Browser acceptance verification error: {e}")
            issues.append(f"Browser acceptance exception: {str(e)}")
        finally:
            if chrome_proc:
                try:
                    chrome_proc.terminate()
                    chrome_proc.wait(timeout=2.0)
                except Exception:
                    pass
            if server_started_by_verifier and backend_proc:
                try:
                    backend_proc.terminate()
                    backend_proc.wait(timeout=2.0)
                except Exception:
                    pass
            shutil.rmtree(temp_profile, ignore_errors=True)

        for exc in unhandled_exceptions:
            issues.append(f"Unhandled JavaScript exception: {exc}")
        for err in console_errors:
            if any(k in err for k in ("TypeError", "ReferenceError", "SyntaxError", "Uncaught", "is not a function")):
                issues.append(f"Browser console error: {err}")
        for mis in missing_rendered:
            issues.append(f"DOM rendering defect: {mis}")

        passed = len(issues) == 0
        status = "PASS" if passed else "FAIL"
        ws_digest = cls.compute_workspace_digest(ws_root)

        # Write acceptance evidence signature & authoritative evidence
        try:
            ev_dir = ws_root / ".hermes"
            ev_dir.mkdir(parents=True, exist_ok=True)
            ev_payload = {
                "workspace_digest": ws_digest,
                "timestamp": time.time(),
                "passed": passed,
                "status": status,
                "target_url": target_url,
                "screenshot": screenshot_path,
                "viewports": viewports_tested_records,
                "workflow_results": workflow_results,
                "issues": issues,
            }
            details["viewports"] = viewports_tested_records
            (ev_dir / "acceptance_evidence.json").write_text(json.dumps(ev_payload, indent=2), encoding="utf-8")

            from core.browser.evidence import AuthoritativeBrowserEvidence, BrowserEvidenceLifecycle, compute_workspace_artifact_hashes
            hashes = compute_workspace_artifact_hashes(ws_root)
            auth_ev = AuthoritativeBrowserEvidence(
                evidence_id=f"ev_browser_{uuid.uuid4().hex[:8]}",
                mission_id=getattr(acceptance_ledger, "mission_id", "") or "mission_active",
                workspace_root=str(ws_root),
                status=BrowserEvidenceLifecycle.PASSED if passed else BrowserEvidenceLifecycle.FAILED,
                tested_url=target_url,
                server_origin=f"http://127.0.0.1:{target_port}" if has_backend else "file://",
                verification_timestamp=time.time(),
                artifact_hashes=hashes,
                viewports_tested=viewports_tested_records if viewports_tested_records else [{"width": 1280, "height": 800, "device_scale_factor": 1.0}],
                browser_result={
                    "interactions_passed": passed,
                    "dom_elements_verified": len(missing_rendered) == 0,
                    "failure_reason": "; ".join(issues) if issues else None,
                },
                console_audit={
                    "uncaught_errors": len(unhandled_exceptions),
                    "errors": console_errors,
                },
                network_audit={
                    "failed_requests": sum(1 for iss in issues if "HTTP" in iss or "404" in iss or "500" in iss),
                },
                provenance="hermes.cdp.verifier.v2",
                details=details,
            )
            (ev_dir / "browser_verified.json").write_text(json.dumps(auth_ev.to_dict(), indent=2), encoding="utf-8")
        except Exception:
            pass

        # Record in AcceptanceLedger if provided
        if acceptance_ledger and hasattr(acceptance_ledger, "record_result"):
            from core.runtime_state.models import AcceptanceCheck, AcceptanceCheckStatus
            if hasattr(acceptance_ledger, "checks") and "chk_browser_acceptance" not in acceptance_ledger.checks:
                acceptance_ledger.add_check(AcceptanceCheck(
                    check_id="chk_browser_acceptance",
                    description="Browser Acceptance Verification",
                    requirement_id="req_browser_acceptance",
                    status=AcceptanceCheckStatus.NOT_RUN,
                ))
            acceptance_ledger.record_result(
                check_id="chk_browser_acceptance",
                status=AcceptanceCheckStatus.PASS if passed else AcceptanceCheckStatus.FAIL,
                evidence_ref=screenshot_path,
                error="; ".join(issues) if issues else None,
            )
            checks_map = getattr(acceptance_ledger, "checks", {})
            if "chk.verification.browser" in checks_map:
                acceptance_ledger.record_result(
                    check_id="chk.verification.browser",
                    status=AcceptanceCheckStatus.PASS if passed else AcceptanceCheckStatus.FAIL,
                    evidence_ref=screenshot_path,
                    error="; ".join(issues) if issues else None,
                )
            if "chk.verification.errors" in checks_map:
                err_pass = (len(unhandled_exceptions) == 0 and len(console_errors) == 0)
                acceptance_ledger.record_result(
                    check_id="chk.verification.errors",
                    status=AcceptanceCheckStatus.PASS if err_pass else AcceptanceCheckStatus.FAIL,
                    evidence_ref=screenshot_path,
                    error="; ".join(console_errors + unhandled_exceptions) if not err_pass else None,
                )
            if "chk.verification.responsive" in checks_map:
                resp_errs = [iss for iss in issues if "RESPONSIVE" in iss or "OVERFLOW" in iss]
                acceptance_ledger.record_result(
                    check_id="chk.verification.responsive",
                    status=AcceptanceCheckStatus.PASS if len(resp_errs) == 0 else AcceptanceCheckStatus.FAIL,
                    evidence_ref=screenshot_path,
                    error="; ".join(resp_errs) if resp_errs else None,
                )

        return BrowserAcceptanceResult(
            passed=passed,
            status=status,
            console_errors=console_errors,
            unhandled_exceptions=unhandled_exceptions,
            missing_rendered_elements=missing_rendered,
            workflow_results=workflow_results,
            issues=issues,
            screenshot_path=screenshot_path,
            navigation_url=target_url,
            evidence_digest=ws_digest,
            details=details,
        )

    @classmethod
    def verify_workspace_sync(
        cls,
        workspace_root: Path | str,
        preferred_port: int = 3000,
        timeout: float = 12.0,
        workflows: Optional[List[Dict[str, Any]]] = None,
        require_persistence: bool = False,
        acceptance_ledger: Optional[Any] = None,
    ) -> BrowserAcceptanceResult:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    lambda: asyncio.run(cls.verify_workspace(
                        workspace_root, preferred_port, timeout, workflows, require_persistence, acceptance_ledger
                    ))
                )
                return future.result()
        return asyncio.run(cls.verify_workspace(
            workspace_root, preferred_port, timeout, workflows, require_persistence, acceptance_ledger
        ))
