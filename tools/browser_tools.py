# tools/browser_tools.py
"""
Universal Browser Quality Assurance, Defect Detection, and Verification Tools for HERMES.
Registered directly in HERMES ToolRegistry for autonomous browser evaluation, responsive
layout analysis, interaction testing, console/network error capture, and accessibility checks.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from core.browser.manager import BrowserManager
from core.browser.models import Viewport
from tools.base import BaseTool, ToolResult
from tools.registry import tool

_GLOBAL_BROWSER_MANAGER: Optional[BrowserManager] = None


def get_browser_manager() -> BrowserManager:
    """Return shared or singleton BrowserManager instance."""
    global _GLOBAL_BROWSER_MANAGER
    if _GLOBAL_BROWSER_MANAGER is None:
        _GLOBAL_BROWSER_MANAGER = BrowserManager()
    return _GLOBAL_BROWSER_MANAGER


def reset_browser_manager() -> None:
    """Reset shared BrowserManager instance."""
    global _GLOBAL_BROWSER_MANAGER
    if _GLOBAL_BROWSER_MANAGER is not None:
        try:
            _run_async(_GLOBAL_BROWSER_MANAGER.close())
        except Exception:
            pass
        _GLOBAL_BROWSER_MANAGER = None


import threading

_BRIDGE: Optional[_PersistentAsyncBridge] = None


class _PersistentAsyncBridge:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="HERMES_Browser_Loop")
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Any, timeout: float = 60.0) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)


def _run_async(coro: Any, timeout: float = 60.0) -> Any:
    """Safely execute coroutine on the persistent browser event loop."""
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = _PersistentAsyncBridge()
    return _BRIDGE.run(coro, timeout=timeout)


@tool(
    name="browser_open_preview",
    description="Launch or attach to local preview server strictly scoped to workspace, verify server identity, and navigate browser.",
    permissions=["net_local", "proc_spawn"],
    risk_score=0.2,
)
class BrowserOpenPreviewTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        ws_dir = None
        port = None
        url_path = "index.html"
        mission_id = None

        if isinstance(inp, dict):
            ws_dir = inp.get("workspace_dir") or inp.get("directory")
            raw_path = inp.get("path") or inp.get("file_path") or inp.get("url")
            if raw_path and not ws_dir:
                if str(raw_path).startswith(("http://", "https://", "file://")):
                    try:
                        res = _run_async(self.manager.navigate(str(raw_path)))
                        duration = time.monotonic() - start_time
                        return ToolResult(
                            success=res.success,
                            output=f"Navigated to {res.url} | Status: {res.status} | Title: {res.title}",
                            duration_seconds=duration,
                            details=res.to_dict(),
                        )
                    except Exception as e:
                        return ToolResult(success=False, error=str(e), exit_code=1, duration_seconds=time.monotonic() - start_time)
                p_obj = Path(raw_path)
                if p_obj.is_file() or p_obj.suffix in (".html", ".htm"):
                    ws_dir = str(p_obj.parent)
                    url_path = p_obj.name
                else:
                    ws_dir = str(p_obj)
            port = inp.get("port")
            url_path = inp.get("url_path", url_path)
            mission_id = inp.get("mission_id")
        elif isinstance(inp, str) and inp:
            if inp.startswith("http://") or inp.startswith("https://") or inp.startswith("file://"):
                # Direct URL navigation
                try:
                    res = _run_async(self.manager.navigate(inp))
                    duration = time.monotonic() - start_time
                    return ToolResult(
                        success=res.success,
                        output=f"Navigated to {res.url} | Status: {res.status} | Title: {res.title}",
                        duration_seconds=duration,
                        details=res.to_dict(),
                    )
                except Exception as e:
                    return ToolResult(success=False, error=str(e), exit_code=1, duration_seconds=time.monotonic() - start_time)
            ws_dir = inp

        try:
            info = _run_async(
                self.manager.open_preview(
                    workspace_dir=ws_dir,
                    port=port,
                    url_path=url_path,
                    mission_id=mission_id,
                )
            )
            duration = time.monotonic() - start_time
            if info.get("success"):
                return ToolResult(
                    success=True,
                    output=f"Preview open at {info['url']} (Port: {info['port']}, Title: '{info['title']}', Status: {info['status']})",
                    duration_seconds=duration,
                    details=info,
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Preview failed: {info.get('error')} (Status: {info.get('status')})",
                    exit_code=1,
                    duration_seconds=duration,
                    details=info,
                )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_open_preview error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


@tool(
    name="browser_inspect_page",
    description="Inspect visible DOM structure, interactive elements, text content, and document scroll metrics.",
    permissions=["net_local"],
    risk_score=0.0,
)
class BrowserInspectPageTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        selector = None
        if isinstance(inp, dict):
            selector = inp.get("selector")
        elif isinstance(inp, str) and inp:
            selector = inp

        try:
            res = _run_async(self.manager.inspect(selector))
            duration = time.monotonic() - start_time

            title = getattr(res, "title", None) or (res.get("title") if isinstance(res, dict) else "")
            url = getattr(res, "url", None) or (res.get("url") if isinstance(res, dict) else "")
            elements = getattr(res, "elements", None) or (res.get("elements", []) if isinstance(res, dict) else [])
            inter_count = getattr(res, "interactive_count", None) or (res.get("interactive_count", 0) if isinstance(res, dict) else 0)
            vis_text = getattr(res, "visible_text", "") or (res.get("visible_text", "") if isinstance(res, dict) else "")

            lines = [
                f"Page Title: {title}",
                f"URL: {url}",
                f"Interactive Elements ({inter_count}):",
            ]
            for elem in elements:
                tag = getattr(elem, "tag_name", None) or (elem.get("tag") if isinstance(elem, dict) else "")
                text = getattr(elem, "text", "") or (elem.get("text", "") if isinstance(elem, dict) else "")
                attrs = getattr(elem, "attributes", {}) or (elem.get("attributes", {}) if isinstance(elem, dict) else {})
                is_inter = getattr(elem, "is_interactive", False) or (tag in ("button", "a", "input", "select", "textarea"))
                if is_inter:
                    lines.append(f"  • <{tag}> text='{text[:30]}' attrs={attrs}")

            lines.append("\nVisible Text Preview:")
            lines.append(vis_text[:300] + ("..." if len(vis_text) > 300 else ""))

            details = res.to_dict() if hasattr(res, "to_dict") else res
            return ToolResult(
                success=True,
                output="\n".join(lines),
                duration_seconds=duration,
                details=details,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_inspect_page error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


@tool(
    name="browser_set_viewport",
    description="Resize browser viewport to specific width and height or standard preset (mobile, tablet, desktop, 375x812).",
    permissions=["net_local"],
    risk_score=0.1,
)
class BrowserSetViewportTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        width = 1280
        height = 720
        is_mobile = None

        if isinstance(inp, dict):
            preset = inp.get("preset", "").lower()
            if preset in ("mobile", "375x812", "iphone"):
                width, height, is_mobile = 375, 812, True
            elif preset in ("mobile_large", "390x844"):
                width, height, is_mobile = 390, 844, True
            elif preset in ("tablet", "768x1024"):
                width, height, is_mobile = 768, 1024, False
            elif preset in ("desktop", "1280x720"):
                width, height, is_mobile = 1280, 720, False
            elif preset in ("desktop_large", "1440x900"):
                width, height, is_mobile = 1440, 900, False
            else:
                width = int(inp.get("width", 1280))
                height = int(inp.get("height", 720))
                is_mobile = inp.get("is_mobile")
        elif isinstance(inp, str):
            p = inp.lower().strip()
            if p in ("mobile", "375"):
                width, height, is_mobile = 375, 812, True
            elif p in ("tablet", "768"):
                width, height, is_mobile = 768, 1024, False
            elif "x" in p:
                parts = p.split("x")
                width, height = int(parts[0]), int(parts[1])

        try:
            res = _run_async(self.manager.set_viewport(width, height, is_mobile=is_mobile))
            duration = time.monotonic() - start_time
            return ToolResult(
                success=res.get("success", True),
                output=f"Viewport resized to {width}x{height} (mobile={res.get('viewport', {}).get('is_mobile')})",
                duration_seconds=duration,
                details=res,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_set_viewport error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


@tool(
    name="browser_click",
    description="Click a button, link, tab, or element by CSS selector, visible text, or ARIA label.",
    permissions=["net_local"],
    risk_score=0.2,
)
class BrowserClickTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        target = ""
        if isinstance(inp, dict):
            target = inp.get("target") or inp.get("selector") or ""
        elif isinstance(inp, str):
            target = inp

        if not target:
            return ToolResult(success=False, error="Missing required parameter 'target'", exit_code=1)

        try:
            res = _run_async(self.manager.click(target))
            duration = time.monotonic() - start_time
            if res.success:
                return ToolResult(
                    success=True,
                    output=f"Click succeeded on '{target}' | {res.after_state or ''}",
                    duration_seconds=duration,
                    details=res.to_dict(),
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Click failed: {res.error}",
                    exit_code=1,
                    duration_seconds=duration,
                    details=res.to_dict(),
                )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_click error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


@tool(
    name="browser_fill",
    description="Fill or type text into an input field or textarea by selector, name, placeholder, or ID.",
    permissions=["net_local"],
    risk_score=0.2,
)
class BrowserFillTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        target = ""
        text = ""
        is_secret = False

        if isinstance(inp, dict):
            target = inp.get("target") or inp.get("selector") or inp.get("field") or ""
            text = str(inp.get("text", inp.get("value", "")))
            is_secret = bool(inp.get("is_secret", False))
        else:
            return ToolResult(success=False, error="Input must be a dictionary with 'target' and 'text'", exit_code=1)

        if not target:
            return ToolResult(success=False, error="Missing required parameter 'target'", exit_code=1)

        try:
            res = _run_async(self.manager.type_text(target, text, is_secret=is_secret))
            duration = time.monotonic() - start_time
            if res.success:
                return ToolResult(
                    success=True,
                    output=f"Filled '{target}' successfully | {res.after_state or ''}",
                    duration_seconds=duration,
                    details=res.to_dict(),
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Fill failed: {res.error}",
                    exit_code=1,
                    duration_seconds=duration,
                    details=res.to_dict(),
                )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_fill error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


@tool(
    name="browser_press_key",
    description="Dispatch keyboard key events (Enter, Escape, Tab, ArrowDown, etc.) to the active element or document.",
    permissions=["net_local"],
    risk_score=0.1,
)
class BrowserPressKeyTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        key = "Enter"
        if isinstance(inp, dict):
            key = inp.get("key", "Enter")
        elif isinstance(inp, str) and inp:
            key = inp

        try:
            res = _run_async(self.manager.press_key(key))
            duration = time.monotonic() - start_time
            return ToolResult(
                success=res.success,
                output=f"Pressed key '{key}': {res.after_state or ''}",
                duration_seconds=duration,
                details=res.to_dict(),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_press_key error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


@tool(
    name="browser_screenshot",
    description="Capture full rendered page screenshot at current or specified viewport and save to artifacts.",
    permissions=["fs_write"],
    risk_score=0.0,
)
class BrowserScreenshotTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        name = "screenshot"
        vp = None

        if isinstance(inp, dict):
            name = inp.get("name", "screenshot")
            mode = inp.get("viewport", "desktop").lower()
            if mode == "mobile":
                vp = Viewport.mobile()
            elif mode == "tablet":
                vp = Viewport.tablet()
            elif mode == "desktop":
                vp = Viewport.desktop()
            elif "x" in mode:
                parts = mode.split("x")
                vp = Viewport(width=int(parts[0]), height=int(parts[1]))
        elif isinstance(inp, str) and inp:
            name = inp

        try:
            artifact = _run_async(self.manager.capture_screenshot(name=name, viewport=vp))
            duration = time.monotonic() - start_time
            return ToolResult(
                success=True,
                output=f"Screenshot saved: {artifact.file_path} ({artifact.dimensions}, SHA: {artifact.sha256[:12]})",
                duration_seconds=duration,
                details=artifact.to_dict(),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_screenshot error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


@tool(
    name="browser_get_console_errors",
    description="Retrieve all JavaScript console errors, uncaught exceptions, and warnings recorded during session.",
    permissions=["net_local"],
    risk_score=0.0,
)
class BrowserGetConsoleErrorsTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any = None) -> ToolResult:
        errors = self.manager.get_console_errors()
        all_msgs = self.manager.get_console_messages()
        if not errors:
            return ToolResult(
                success=True,
                output=f"No console errors recorded ({len(all_msgs)} total messages).",
                details={"errors": [], "total_messages": len(all_msgs)},
            )

        lines = [f"Recorded Console Errors ({len(errors)}):"]
        for err in errors:
            lines.append(f"  • [{err.msg_type.upper()}] {err.text}")

        return ToolResult(
            success=False,
            output="\n".join(lines),
            error=f"{len(errors)} console error(s) detected",
            exit_code=1,
            details={"errors": [e.to_dict() for e in errors]},
        )


@tool(
    name="browser_get_network_failures",
    description="Retrieve failed network HTTP requests (status >= 400 or aborted requests).",
    permissions=["net_local"],
    risk_score=0.0,
)
class BrowserGetNetworkFailuresTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any = None) -> ToolResult:
        failures = self.manager.get_network_failures()
        all_recs = self.manager.get_network_records()
        if not failures:
            return ToolResult(
                success=True,
                output=f"No network failures recorded ({len(all_recs)} total requests).",
                details={"failures": [], "total_requests": len(all_recs)},
            )

        lines = [f"Failed Network Requests ({len(failures)}):"]
        for f in failures:
            lines.append(f"  • {f.method} {f.url} -> {f.status or 'ERR'} ({f.error or 'Failed'})")

        return ToolResult(
            success=False,
            output="\n".join(lines),
            error=f"{len(failures)} network request(s) failed",
            exit_code=1,
            details={"failures": [f.to_dict() for f in failures]},
        )


@tool(
    name="browser_check_layout",
    description="Run automated responsive layout checks across 6 canonical viewports to detect horizontal overflow, clipping, or overlapping controls.",
    permissions=["net_local"],
    risk_score=0.1,
)
class BrowserCheckLayoutTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any = None) -> ToolResult:
        start_time = time.monotonic()
        vps = None
        tolerance = 2.0

        if isinstance(inp, dict):
            tolerance = float(inp.get("tolerance", 2.0))
            custom = inp.get("viewports")
            if isinstance(custom, list):
                vps = []
                for item in custom:
                    if isinstance(item, dict):
                        vps.append(Viewport(width=int(item["width"]), height=int(item["height"])))
                    elif isinstance(item, str) and "x" in item:
                        p = item.split("x")
                        vps.append(Viewport(width=int(p[0]), height=int(p[1])))

        try:
            res = _run_async(self.manager.check_layout(viewports=vps, tolerance=tolerance))
            duration = time.monotonic() - start_time
            lines = [f"Layout Verification: {'PASSED' if res.passed else 'FAILED'} ({res.total_viewports} viewports checked)"]
            for vp_name, data in res.viewports.items():
                status_str = "FAIL (OVERFLOW)" if data.get("hasOverflow") else "PASS"
                cw = data.get("clientWidth")
                sw = data.get("scrollWidth")
                lines.append(f"  • {vp_name}: {status_str} | clientWidth={cw}px, scrollWidth={sw}px")
                for off in data.get("offendingElements", []):
                    lines.append(f"      Offending element: {off.get('element')} width={off.get('width')}px right={off.get('right')}px")

            return ToolResult(
                success=res.passed,
                output="\n".join(lines),
                error=None if res.passed else res.summary,
                exit_code=0 if res.passed else 1,
                duration_seconds=duration,
                details=res.to_dict(),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_check_layout error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


@tool(
    name="browser_check_images",
    description="Verify all rendered <img> tags on page have loaded, have positive naturalWidth/Height, and decode successfully.",
    permissions=["net_local"],
    risk_score=0.0,
)
class BrowserCheckImagesTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any = None) -> ToolResult:
        start_time = time.monotonic()
        scroll_first = True
        if isinstance(inp, dict):
            scroll_first = inp.get("scroll_first", True)

        try:
            res = _run_async(self.manager.check_images(scroll_first=scroll_first))
            duration = time.monotonic() - start_time
            lines = [f"Image Verification: {'PASSED' if res.passed else 'FAILED'} ({res.loaded_images}/{res.total_images} loaded)"]
            for img in res.details:
                st = "LOADED" if img.get("isLoaded") else "BROKEN"
                nw = img.get("naturalWidth")
                nh = img.get("naturalHeight")
                lines.append(f"  • [{st}] src='{img.get('src')}' ({nw}x{nh}) alt='{img.get('alt')}'")

            return ToolResult(
                success=res.passed,
                output="\n".join(lines),
                error=None if res.passed else f"{res.broken_images} broken image(s) detected",
                exit_code=0 if res.passed else 1,
                duration_seconds=duration,
                details=res.to_dict(),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_check_images error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


@tool(
    name="browser_check_accessibility",
    description="Run automated accessibility audit checking headings hierarchy, button/link accessible names, image alt attributes, and form labels.",
    permissions=["net_local"],
    risk_score=0.0,
)
class BrowserCheckAccessibilityTool(BaseTool):
    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or get_browser_manager()

    def execute(self, inp: Any = None) -> ToolResult:
        start_time = time.monotonic()
        try:
            res = _run_async(self.manager.check_accessibility())
            duration = time.monotonic() - start_time
            lines = [f"Accessibility Audit: {'PASSED' if res.passed else 'FAILED'} (Score: {res.score}/100, Issues: {res.total_issues})"]
            for issue in res.issues:
                lines.append(f"  • [{issue.get('severity', 'info').upper()}] {issue.get('type')}: {issue.get('message')}")

            return ToolResult(
                success=res.passed,
                output="\n".join(lines),
                error=None if res.passed else f"Accessibility audit failed with {len(res.issues)} issues",
                exit_code=0 if res.passed else 1,
                duration_seconds=duration,
                details=res.to_dict(),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"browser_check_accessibility error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)
