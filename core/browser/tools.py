# core/browser/tools.py
"""
Browser Tools for HERMES AgentLoop (Prompt 17).
Provides browser_navigate, browser_click, browser_type, browser_inspect,
browser_screenshot, browser_console, and browser_network.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from core.browser.manager import BrowserManager
from core.browser.models import Viewport
from tools.base import BaseTool, ToolResult


def _run_async(coro):
    """Safely run async coroutine synchronously or in existing loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(coro)).result(timeout=30.0)
    else:
        return asyncio.run(coro)


class BrowserNavigateTool(BaseTool):
    name = "browser_navigate"
    description = "Navigate browser to a specified URL."
    risk_score = 0.2

    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or BrowserManager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        if isinstance(inp, dict):
            url = inp.get("url", "")
        else:
            url = str(inp)

        if not url:
            return ToolResult(success=False, error="Missing required parameter 'url'", exit_code=1)

        try:
            res = _run_async(self.manager.navigate(url))
            duration = time.monotonic() - start_time
            if res.success:
                return ToolResult(
                    success=True,
                    output=f"Navigated to {res.url} | Status: {res.status} | Title: {res.title} ({duration:.2f}s)",
                    duration_seconds=duration,
                    details=res.to_dict(),
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Navigation failed: {res.error} (Status: {res.status})",
                    exit_code=1,
                    duration_seconds=duration,
                    details=res.to_dict(),
                )
        except Exception as e:
            return ToolResult(success=False, error=f"Navigation error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class BrowserClickTool(BaseTool):
    name = "browser_click"
    description = "Click a button, link, or element by selector, text, or ID."
    risk_score = 0.3

    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or BrowserManager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        if isinstance(inp, dict):
            target = inp.get("target", "")
        else:
            target = str(inp)

        if not target:
            return ToolResult(success=False, error="Missing required parameter 'target'", exit_code=1)

        try:
            res = _run_async(self.manager.click(target))
            duration = time.monotonic() - start_time
            if res.success:
                return ToolResult(
                    success=True,
                    output=f"Click successful on '{target}' | {res.after_state or ''}",
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
            return ToolResult(success=False, error=f"Click error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class BrowserTypeTool(BaseTool):
    name = "browser_type"
    description = "Type text into an input field or textarea by selector, name, or placeholder."
    risk_score = 0.3

    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or BrowserManager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        if isinstance(inp, dict):
            target = inp.get("target", "")
            text = str(inp.get("text", ""))
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
                    output=f"Type successful into '{target}' | {res.after_state or ''}",
                    duration_seconds=duration,
                    details=res.to_dict(),
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Type failed: {res.error}",
                    exit_code=1,
                    duration_seconds=duration,
                    details=res.to_dict(),
                )
        except Exception as e:
            return ToolResult(success=False, error=f"Type error: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class BrowserInspectTool(BaseTool):
    name = "browser_inspect"
    description = "Inspect structured DOM elements, interactive controls, and visible page text."
    risk_score = 0.0

    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or BrowserManager()

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

            lines = [
                f"Page Title: {res.title}",
                f"URL: {res.url}",
                f"Interactive Elements ({res.interactive_count}):",
            ]
            for elem in res.elements:
                if elem.is_interactive:
                    lines.append(f"  • <{elem.tag_name}> {elem.text[:40]} {elem.attributes}")

            lines.append("\nVisible Text Preview:")
            lines.append(res.visible_text[:300] + ("..." if len(res.visible_text) > 300 else ""))

            return ToolResult(
                success=True,
                output="\n".join(lines),
                duration_seconds=duration,
                details=res.to_dict(),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"DOM inspection failed: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class BrowserScreenshotTool(BaseTool):
    name = "browser_screenshot"
    description = "Capture page screenshot with responsive viewport (desktop, tablet, mobile)."
    risk_score = 0.0

    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or BrowserManager()

    def execute(self, inp: Any) -> ToolResult:
        start_time = time.monotonic()
        name = "screenshot"
        vp_mode = "desktop"
        if isinstance(inp, dict):
            name = inp.get("name", "screenshot")
            vp_mode = inp.get("viewport", "desktop").lower()

        if vp_mode == "mobile":
            viewport = Viewport.mobile()
        elif vp_mode == "tablet":
            viewport = Viewport.tablet()
        else:
            viewport = Viewport.desktop()

        try:
            artifact = _run_async(self.manager.capture_screenshot(name=name, viewport=viewport))
            duration = time.monotonic() - start_time
            return ToolResult(
                success=True,
                output=f"Screenshot captured: {artifact.artifact_id} ({artifact.dimensions}) -> {artifact.file_path}",
                duration_seconds=duration,
                details=artifact.to_dict(),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Screenshot capture failed: {e}", exit_code=1, duration_seconds=time.monotonic() - start_time)


class BrowserConsoleTool(BaseTool):
    name = "browser_console"
    description = "Retrieve recorded console logs, warnings, and errors from the current browser session."
    risk_score = 0.0

    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or BrowserManager()

    def execute(self, inp: Any) -> ToolResult:
        messages = self.manager.get_console_messages()
        if not messages:
            return ToolResult(success=True, output="No console messages recorded.", details={"messages": []})

        lines = [f"Console Messages ({len(messages)}):"]
        for m in messages:
            lines.append(f"  [{m.msg_type.upper()}] {m.text}")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            details={"messages": [m.to_dict() for m in messages]},
        )


class BrowserNetworkTool(BaseTool):
    name = "browser_network"
    description = "Retrieve recorded network HTTP requests and responses (with credentials scrubbed)."
    risk_score = 0.0

    def __init__(self, manager: Optional[BrowserManager] = None) -> None:
        self.manager = manager or BrowserManager()

    def execute(self, inp: Any) -> ToolResult:
        records = self.manager.get_network_records()
        if not records:
            return ToolResult(success=True, output="No network requests recorded.", details={"requests": []})

        lines = [f"Network Requests ({len(records)}):"]
        for r in records:
            status_str = str(r.status) if r.status else "ERR"
            lines.append(f"  • {r.method} {r.url} -> {status_str} ({r.duration_seconds:.2f}s)")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            details={"requests": [r.to_dict() for r in records]},
        )
