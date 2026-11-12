# core/browser/manager.py
"""
Browser Manager for HERMES 2.x (Prompt 17).
Orchestrates browser automation, driver selection (CDP vs Simulated),
dev server management, screenshot artifact persistence, and security enforcement.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from core.browser.dev_server import DevServerInfo, DevServerManager
from core.browser.driver import BrowserDriver, CdpBrowserDriver, SimulatedBrowserDriver
from core.browser.models import (
    AccessibilityAuditResult,
    ActionResult,
    BrowserSessionConfig,
    ConsoleMessage,
    ImageIntegrityResult,
    InspectResult,
    LayoutCheckResult,
    NavigationResult,
    NetworkRequestRecord,
    ScreenshotArtifact,
    Viewport,
)
from core.browser.security import BrowserSecurityManager, BrowserSecurityViolation

logger = logging.getLogger("hermes.browser.manager")


class BrowserManager:
    """Canonical manager for browser sessions and web testing."""

    def __init__(
        self,
        artifacts_dir: Optional[Path | str] = None,
        security_manager: Optional[BrowserSecurityManager] = None,
        prefer_cdp: bool = True,
    ) -> None:
        if artifacts_dir:
            self.artifacts_dir = Path(artifacts_dir).resolve()
        elif os.environ.get("HERMES_BROWSER_ARTIFACTS_DIR"):
            self.artifacts_dir = Path(os.environ["HERMES_BROWSER_ARTIFACTS_DIR"]).resolve()
        elif os.environ.get("HERMES_ARTIFACTS_DIR"):
            self.artifacts_dir = (Path(os.environ["HERMES_ARTIFACTS_DIR"]) / "browser").resolve()
        else:
            self.artifacts_dir = Path("artifacts/browser").resolve()
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.security = security_manager or BrowserSecurityManager()
        self.dev_servers = DevServerManager()

        self.driver: Optional[BrowserDriver] = None
        self._prefer_cdp = prefer_cdp
        self._is_active: bool = False
        self._generation: int = 1

    @property
    def is_active(self) -> bool:
        return self._is_active and self.driver is not None

    async def launch(
        self,
        headless: bool = True,
        viewport: Optional[Viewport] = None,
        timeout: float = 30.0,
    ) -> bool:
        """Launch a fresh browser session."""
        if self.is_active:
            await self.close()

        cfg = BrowserSessionConfig(
            headless=headless,
            viewport=viewport or Viewport.desktop(),
            timeout=timeout,
        )

        # Driver selection
        cdp_driver = CdpBrowserDriver(security_manager=self.security)
        if self._prefer_cdp and cdp_driver.is_available:
            try:
                launched = await cdp_driver.launch(cfg)
                if launched:
                    self.driver = cdp_driver
                    self._is_active = True
                    logger.info("BrowserManager: launched real CDP browser driver")
                    return True
            except Exception as e:
                logger.warning(f"Failed to launch CDP browser driver, falling back to Simulated: {e}")

        # Fallback to simulated in-memory browser
        sim_driver = SimulatedBrowserDriver(security_manager=self.security)
        await sim_driver.launch(cfg)
        self.driver = sim_driver
        self._is_active = True
        logger.info("BrowserManager: launched Simulated browser driver")
        return True

    async def _ensure_active_session(self) -> None:
        """Bounded session recovery: reinitialize browser driver and restore URL if session dropped."""
        if not self.is_active or self.driver is None:
            logger.info("BrowserManager: recovering inactive browser session...")
            await self.launch()
            last_url = getattr(self, "_last_navigated_url", None)
            if last_url and self.driver is not None:
                try:
                    await self.driver.navigate(last_url)
                except Exception as e:
                    logger.warning(f"BrowserManager: re-navigating to {last_url} after session recovery failed: {e}")

    async def navigate(self, url: str) -> NavigationResult:
        """Navigate active browser session to URL."""
        if not self.is_active:
            await self.launch()
        assert self.driver is not None
        self._last_navigated_url = url
        return await self.driver.navigate(url)

    async def click(self, target: str) -> ActionResult:
        """Click an element identified by selector, ID, or visible text."""
        if not self.is_active:
            await self._ensure_active_session()
        if not self.is_active or self.driver is None:
            raise RuntimeError("Browser session is not active")
        return await self.driver.click(target)

    async def type_text(self, target: str, text: str, is_secret: bool = False) -> ActionResult:
        """Type text into an input field or textarea."""
        if not self.is_active:
            await self._ensure_active_session()
        if not self.is_active or self.driver is None:
            raise RuntimeError("Browser session is not active")
        return await self.driver.type_text(target, text, is_secret=is_secret)

    type = type_text

    async def inspect(self, selector: Optional[str] = None) -> InspectResult:
        """Inspect visible DOM tree and interactive elements."""
        if not self.is_active:
            await self._ensure_active_session()
        if not self.is_active or self.driver is None:
            raise RuntimeError("Browser session is not active")
        return await self.driver.inspect_dom(selector)

    async def capture_screenshot(
        self,
        name: str = "screenshot",
        viewport: Optional[Viewport] = None,
    ) -> ScreenshotArtifact:
        """Capture screenshot and store it in artifacts directory with SHA-256 digest."""
        if not self.is_active:
            await self._ensure_active_session()
        if not self.is_active or self.driver is None:
            raise RuntimeError("Browser session is not active")
        assert self.driver is not None

        timestamp = int(time.time() * 1000)
        file_path = self.artifacts_dir / f"{name}_{timestamp}.png"
        artifact = await self.driver.capture_screenshot(file_path, viewport=viewport)
        artifact.generation = self._generation
        return artifact

    def get_console_messages(self) -> List[ConsoleMessage]:
        """Fetch all recorded console messages."""
        if not self.driver:
            return []
        return self.driver.get_console_messages()

    async def open_preview(
        self,
        workspace_dir: Optional[Union[Path, str]] = None,
        port: Optional[int] = None,
        url_path: str = "index.html",
        mission_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Safely spawn or attach to a preview server strictly scoped to workspace_dir,
        enforce preview server identity, and navigate the active browser to it.
        """
        if workspace_dir is None:
            # Fallback to current working directory
            target_ws = Path.cwd()
        else:
            target_ws = Path(workspace_dir).resolve()

        if not target_ws.exists():
            raise FileNotFoundError(f"Target preview workspace does not exist: {target_ws}")

        # Stop any stale server serving a different workspace
        self.dev_servers.stop_stale_servers_not_matching(target_ws)

        # Start or reuse static server for this directory
        server = await self.dev_servers.start_static_server(
            directory=target_ws,
            name=f"preview_{target_ws.name}",
            port=port,
        )

        # Identity check: verify server serves the requested directory
        if Path(server.workspace_dir).resolve() != target_ws:
            raise RuntimeError(
                f"Preview identity mismatch: server serves {server.workspace_dir}, expected {target_ws}"
            )

        # Check expected workspace entrypoint title
        expected_title = None
        for cand in [target_ws / "index.html", target_ws / "static" / "index.html", target_ws / "public" / "index.html"]:
            if cand.exists():
                try:
                    h_txt = cand.read_text(encoding="utf-8", errors="ignore")
                    t_match = re.search(r'<title>([^<]+)</title>', h_txt, re.I)
                    if t_match:
                        expected_title = t_match.group(1).strip()
                        break
                except Exception:
                    pass

        clean_path = url_path.lstrip("/\\")
        target_url = f"{server.url}/{clean_path}" if clean_path else server.url

        if not self.is_active:
            await self.launch()

        nav_res = await self.navigate(target_url)

        # Verify preview target correctness
        preview_success = nav_res.success
        preview_error = nav_res.error
        if preview_success and expected_title and nav_res.title:
            actual_t = nav_res.title.strip()
            # If actual title is completely different (e.g. "Hello 2", "Document", "Webpack App")
            if actual_t != expected_title and not any(w.lower() in actual_t.lower() for w in expected_title.split()[:3]):
                preview_success = False
                preview_error = (
                    f"INCORRECT_PREVIEW_TARGET: Preview loaded page with title '{actual_t}', "
                    f"but generated HTML specifies '{expected_title}'. "
                    f"Serving target is invalid or belongs to an unmanaged stale process."
                )

        return {
            "success": preview_success,
            "url": target_url,
            "port": server.port,
            "workspace_dir": str(target_ws),
            "title": nav_res.title,
            "status": nav_res.status,
            "error": preview_error,
            "mission_id": mission_id,
        }

    async def set_viewport(
        self,
        width: int,
        height: int,
        is_mobile: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Set responsive viewport dimensions on active browser session."""
        if not self.is_active:
            await self.launch()
        assert self.driver is not None

        mobile = is_mobile if is_mobile is not None else (width < 500)
        vp = Viewport(width=width, height=height, is_mobile=mobile)
        ok = await self.driver.set_viewport(vp)
        return {
            "success": ok,
            "viewport": vp.to_dict(),
        }

    async def press_key(self, key: str) -> ActionResult:
        """Dispatch a keyboard key press on the active browser session."""
        if not self.is_active:
            await self._ensure_active_session()
        if not self.is_active or self.driver is None:
            raise RuntimeError("Browser session is not active")
        return await self.driver.press_key(key)

    async def check_layout(
        self,
        viewports: Optional[List[Viewport]] = None,
        tolerance: float = 2.0,
    ) -> LayoutCheckResult:
        """Automated layout verification across standard or custom viewports."""
        if not self.is_active:
            await self.launch()
        assert self.driver is not None
        return await self.driver.check_layout(viewports=viewports, tolerance=tolerance)

    async def check_images(self, scroll_first: bool = True) -> ImageIntegrityResult:
        """Check all <img> tags to verify loading, natural dimensions, and decoding."""
        if not self.is_active:
            await self.launch()
        assert self.driver is not None
        return await self.driver.check_images(scroll_first=scroll_first)

    async def check_accessibility(self) -> AccessibilityAuditResult:
        """Audit baseline semantic accessibility, landmarks, and accessible names."""
        if not self.is_active:
            await self.launch()
        assert self.driver is not None
        return await self.driver.check_accessibility()

    def get_console_errors(self) -> List[ConsoleMessage]:
        """Fetch only console messages with error or exception severity."""
        msgs = self.get_console_messages()
        return [m for m in msgs if m.msg_type in ("error", "exception")]

    def get_network_failures(self) -> List[NetworkRequestRecord]:
        """Fetch network requests that failed or responded with HTTP >= 400."""
        recs = self.get_network_records()
        return [r for r in recs if r.error or (r.status and r.status >= 400)]

    def get_network_records(self) -> List[NetworkRequestRecord]:
        """Fetch all recorded network requests/responses."""
        if not self.driver:
            return []
        return self.driver.get_network_records()

    async def close(self) -> None:
        """Cleanly terminate browser session and stop managed dev servers."""
        if self.driver:
            try:
                await self.driver.close()
            except Exception as e:
                logger.warning(f"Error closing browser driver: {e}")
            self.driver = None

        self.dev_servers.stop_all()
        self._is_active = False
        self._generation += 1
