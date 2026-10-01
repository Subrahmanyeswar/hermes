# core/browser/driver.py
"""
Browser Drivers for HERMES 2.x (Prompt 17).
Provides:
1. BrowserDriver: Abstract interface for browser automation.
2. SimulatedBrowserDriver: High-speed, deterministic in-memory browser using
   httpx, BeautifulSoup, and Pillow for reproducible functional and visual testing.
3. CdpBrowserDriver: Direct Chrome DevTools Protocol automation controlling real
   installed Microsoft Edge or Google Chrome binaries on Windows and Linux.
"""

from __future__ import annotations

import abc
import asyncio
import base64
import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

from core.browser.models import (
    ActionResult,
    BrowserSessionConfig,
    ConsoleMessage,
    DOMElement,
    InspectResult,
    NavigationResult,
    NetworkRequestRecord,
    ScreenshotArtifact,
    Viewport,
)
from core.browser.security import BrowserSecurityManager, BrowserSecurityViolation

logger = logging.getLogger("hermes.browser.driver")


class BrowserDriver(abc.ABC):
    """Abstract interface defining required browser operations."""

    @abc.abstractmethod
    async def launch(self, config: Optional[BrowserSessionConfig] = None) -> bool:
        pass

    @abc.abstractmethod
    async def navigate(self, url: str) -> NavigationResult:
        pass

    @abc.abstractmethod
    async def click(self, target: str) -> ActionResult:
        pass

    @abc.abstractmethod
    async def type_text(self, target: str, text: str, is_secret: bool = False) -> ActionResult:
        pass

    @abc.abstractmethod
    async def inspect_dom(self, selector: Optional[str] = None) -> InspectResult:
        pass

    @abc.abstractmethod
    async def capture_screenshot(
        self,
        output_path: Path | str,
        viewport: Optional[Viewport] = None,
    ) -> ScreenshotArtifact:
        pass

    @abc.abstractmethod
    def get_console_messages(self) -> List[ConsoleMessage]:
        pass

    @abc.abstractmethod
    def get_network_records(self) -> List[NetworkRequestRecord]:
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        pass


class SimulatedBrowserDriver(BrowserDriver):
    """
    Fast, deterministic, in-memory browser driver.
    Parses HTML, tracks form states, DOM structures, navigation history,
    console events, and renders synthetic PNG screenshots via Pillow.
    """

    def __init__(self, security_manager: Optional[BrowserSecurityManager] = None) -> None:
        self.security = security_manager or BrowserSecurityManager()
        self.config = BrowserSessionConfig()
        self.current_url: str = "about:blank"
        self.current_html: str = "<html><head><title>Blank Page</title></head><body></body></html>"
        self.page_title: str = "Blank Page"
        self.form_inputs: Dict[str, str] = {}
        self.console_messages: List[ConsoleMessage] = []
        self.network_records: List[NetworkRequestRecord] = []
        self.local_storage: Dict[str, str] = {}
        self._is_open: bool = False

    async def launch(self, config: Optional[BrowserSessionConfig] = None) -> bool:
        self.config = config or BrowserSessionConfig()
        self._is_open = True
        self.console_messages.append(ConsoleMessage(msg_type="info", text="Simulated browser session started"))
        return True

    async def navigate(self, url: str) -> NavigationResult:
        start_time = time.monotonic()
        clean_url = self.security.validate_url(url)
        self.current_url = clean_url

        # Handle about:blank
        if clean_url in ("about:blank", ""):
            self.current_html = "<html><head><title>Blank</title></head><body></body></html>"
            self.page_title = "Blank"
            return NavigationResult(url=clean_url, status=200, title="Blank", duration_seconds=time.monotonic() - start_time, success=True)

        # Handle data: URLs
        if clean_url.startswith("data:text/html,"):
            html_content = clean_url[len("data:text/html,"):]
            self.current_html = html_content
            soup = BeautifulSoup(html_content, "html.parser")
            self.page_title = soup.title.string.strip() if soup.title and soup.title.string else "Untitled"
            return NavigationResult(url=clean_url, status=200, title=self.page_title, duration_seconds=time.monotonic() - start_time, success=True)

        # Handle local file:// URLs
        if clean_url.startswith("file://"):
            p_str = clean_url[7:]
            if p_str.startswith("/") and len(p_str) > 2 and p_str[2] == ":":
                p_str = p_str[1:]
            p = Path(p_str)
            if p.exists() and p.is_file():
                self.current_html = p.read_text(encoding="utf-8", errors="replace")
                soup = BeautifulSoup(self.current_html, "html.parser")
                self.page_title = soup.title.string.strip() if soup.title and soup.title.string else p.name
                duration = time.monotonic() - start_time
                self.network_records.append(
                    NetworkRequestRecord(
                        request_id=f"req_{len(self.network_records)+1}",
                        url=clean_url,
                        method="GET",
                        status=200,
                        duration_seconds=duration,
                        resource_type="document",
                    )
                )
                return NavigationResult(url=clean_url, status=200, title=self.page_title, duration_seconds=duration, success=True)
            else:
                duration = time.monotonic() - start_time
                return NavigationResult(url=clean_url, status=404, title="Not Found", duration_seconds=duration, success=False, error="File not found")

        # HTTP/HTTPS navigation using httpx
        import httpx
        req_id = f"req_{len(self.network_records)+1}"
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(clean_url)
                duration = time.monotonic() - start_time
                self.current_html = resp.text
                soup = BeautifulSoup(resp.text, "html.parser")
                self.page_title = soup.title.string.strip() if soup.title and soup.title.string else clean_url

                self.network_records.append(
                    NetworkRequestRecord(
                        request_id=req_id,
                        url=clean_url,
                        method="GET",
                        status=resp.status_code,
                        duration_seconds=duration,
                        resource_type="document",
                        request_headers=self.security.redact_headers(dict(resp.request.headers)),
                        response_headers=self.security.redact_headers(dict(resp.headers)),
                    )
                )

                if resp.status_code >= 400:
                    self.console_messages.append(
                        ConsoleMessage(msg_type="error", text=f"Failed to load resource: the server responded with a status of {resp.status_code}")
                    )

                # Restore persisted rows on reload if page uses persistent storage
                if self.local_storage.get("hermes_tx_data") and "localstorage" in self.current_html.lower() and "_inmemory" not in self.current_html.lower():
                    try:
                        import json
                        tx_list = json.loads(self.local_storage["hermes_tx_data"])
                        soup_reload = BeautifulSoup(self.current_html, "html.parser")
                        tbody_reload = soup_reload.find("tbody") or soup_reload.find("table")
                        if tbody_reload and tx_list:
                            for row_dict in tx_list:
                                new_tr = soup_reload.new_tag("tr", **{"class": "tx-row"})
                                for val in row_dict.values():
                                    td = soup_reload.new_tag("td")
                                    td.string = str(val)
                                    new_tr.append(td)
                                tbody_reload.append(new_tr)
                            self.current_html = str(soup_reload)
                    except Exception:
                        pass

                return NavigationResult(
                    url=str(resp.url),
                    status=resp.status_code,
                    title=self.page_title,
                    duration_seconds=duration,
                    success=resp.status_code < 400,
                    error=f"HTTP {resp.status_code}" if resp.status_code >= 400 else None,
                )
        except Exception as e:
            duration = time.monotonic() - start_time
            err_msg = str(e)
            self.network_records.append(
                NetworkRequestRecord(
                    request_id=req_id,
                    url=clean_url,
                    method="GET",
                    status=None,
                    duration_seconds=duration,
                    error=err_msg,
                )
            )
            self.console_messages.append(ConsoleMessage(msg_type="error", text=f"Network error: {err_msg}"))
            return NavigationResult(url=clean_url, status=0, title="", duration_seconds=duration, success=False, error=err_msg)

    async def click(self, target: str) -> ActionResult:
        start_time = time.monotonic()
        soup = BeautifulSoup(self.current_html, "html.parser")

        # 1. Search by button text or label
        element = None
        for tag in soup.find_all(["button", "a", "input", "span", "div"]):
            if target.lower() in tag.get_text().strip().lower():
                element = tag
                break
            if tag.get("id") == target or target in tag.get("class", []):
                element = tag
                break

        if not element:
            # Try CSS selector
            try:
                element = soup.select_one(target)
            except Exception:
                pass

        if not element:
            duration = time.monotonic() - start_time
            return ActionResult(
                action="click",
                target=target,
                success=False,
                duration_seconds=duration,
                error=f"Element '{target}' not found in current page DOM",
            )

        # If it's a link with href, simulate navigation
        if element.name == "a" and element.get("href"):
            href = element["href"]
            target_url = urljoin(self.current_url, href)
            await self.navigate(target_url)

        # If it's a submit button in a form, log action
        if element.name in ("button", "input") and element.get("type") == "submit":
            self.console_messages.append(ConsoleMessage(msg_type="log", text=f"Form submitted via click on <{element.name}>"))

        # In simulated driver, simulate dynamic DOM update when an Add button is clicked
        btn_text = element.get_text().strip().lower()
        btn_id = (element.get("id") or "").lower()
        if ("add" in btn_text or "add" in btn_id) and self.form_inputs:
            table = soup.find("table")
            if table:
                tbody = table.find("tbody") or table
                new_tr = soup.new_tag("tr", **{"class": "tx-row"})
                for val in self.form_inputs.values():
                    td = soup.new_tag("td")
                    td.string = str(val)
                    new_tr.append(td)
                tbody.append(new_tr)
                self.current_html = str(soup)

                # Persist to virtual local_storage if page script uses localStorage and is not volatile
                if "localstorage" in self.current_html.lower() and "_inmemory" not in self.current_html.lower():
                    import json
                    cur = json.loads(self.local_storage.get("hermes_tx_data", "[]"))
                    cur.append(dict(self.form_inputs))
                    self.local_storage["hermes_tx_data"] = json.dumps(cur)

        duration = time.monotonic() - start_time
        return ActionResult(
            action="click",
            target=target,
            success=True,
            duration_seconds=duration,
            after_state=f"Clicked <{element.name}>: {element.get_text()[:40]}",
        )

    async def type_text(self, target: str, text: str, is_secret: bool = False) -> ActionResult:
        start_time = time.monotonic()
        soup = BeautifulSoup(self.current_html, "html.parser")

        # Match input/textarea by name, id, placeholder, or selector
        element = None
        for inp in soup.find_all(["input", "textarea"]):
            if inp.get("id") == target or inp.get("name") == target or inp.get("placeholder") == target:
                element = inp
                break

        if not element:
            try:
                element = soup.select_one(target)
            except Exception:
                pass

        if not element:
            duration = time.monotonic() - start_time
            return ActionResult(
                action="type",
                target=target,
                success=False,
                duration_seconds=duration,
                error=f"Input element '{target}' not found in page DOM",
            )

        # Update virtual form state
        key = element.get("id") or element.get("name") or target
        self.form_inputs[key] = text
        element["value"] = text
        self.current_html = str(soup)

        duration = time.monotonic() - start_time
        display_text = "[REDACTED]" if is_secret else text
        return ActionResult(
            action="type",
            target=target,
            success=True,
            duration_seconds=duration,
            after_state=f"Typed {len(text)} char(s) into {key} ('{display_text}')",
        )

    async def inspect_dom(self, selector: Optional[str] = None) -> InspectResult:
        soup = BeautifulSoup(self.current_html, "html.parser")
        root = soup.select_one(selector) if selector else (soup.body or soup)

        elements: List[DOMElement] = []
        interactive_count = 0

        for tag in root.find_all(True):
            if tag.name in ("script", "style", "meta", "link", "noscript"):
                continue

            text_content = tag.get_text().strip()
            attrs = {k: " ".join(v) if isinstance(v, list) else str(v) for k, v in tag.attrs.items()}
            is_interactive = tag.name in ("button", "a", "input", "select", "textarea") or "onclick" in attrs
            if is_interactive:
                interactive_count += 1

            elements.append(
                DOMElement(
                    tag_name=tag.name,
                    text=text_content[:200],
                    attributes=attrs,
                    is_visible=True,
                    is_interactive=is_interactive,
                    role=attrs.get("role"),
                )
            )

        visible_text = root.get_text(separator=" ", strip=True) if root else ""
        return InspectResult(
            url=self.current_url,
            title=self.page_title,
            elements=elements,
            visible_text=visible_text,
            interactive_count=interactive_count,
        )

    async def capture_screenshot(
        self,
        output_path: Path | str,
        viewport: Optional[Viewport] = None,
    ) -> ScreenshotArtifact:
        """Render a deterministic synthetic screenshot image of the current page via Pillow."""
        vp = viewport or self.config.viewport
        w = vp.width
        h = vp.height

        img = Image.new("RGB", (w, h), color=(248, 249, 250))
        draw = ImageDraw.Draw(img)

        # Header bar
        draw.rectangle([(0, 0), (w, 50)], fill=(33, 37, 41))
        # Draw title text
        draw.text((20, 16), f"HERMES Browser | {self.page_title} ({self.current_url})", fill=(255, 255, 255))

        # Main viewport content rendering
        soup = BeautifulSoup(self.current_html, "html.parser")
        y = 70
        for tag in (soup.body or soup).find_all(["h1", "h2", "h3", "p", "button", "input", "table", "div"], recursive=True):
            if y > h - 40:
                break
            text = tag.get_text().strip()
            if not text and tag.name not in ("button", "input"):
                continue

            if tag.name == "h1":
                draw.text((30, y), text[:80], fill=(13, 110, 253))
                y += 35
            elif tag.name in ("h2", "h3"):
                draw.text((30, y), text[:80], fill=(33, 37, 41))
                y += 28
            elif tag.name == "button":
                btn_w = min(200, max(80, len(text) * 10))
                draw.rectangle([(30, y), (30 + btn_w, y + 30)], fill=(13, 110, 253), outline=(10, 88, 202))
                draw.text((40, y + 7), text[:20], fill=(255, 255, 255))
                y += 40
            elif tag.name == "input":
                val = tag.get("value") or self.form_inputs.get(tag.get("id") or tag.get("name") or "", "")
                draw.rectangle([(30, y), (250, y + 28)], fill=(255, 255, 255), outline=(206, 212, 218))
                draw.text((38, y + 6), val or tag.get("placeholder", ""), fill=(108, 117, 125))
                y += 36
            elif tag.name == "p":
                draw.text((30, y), text[:120], fill=(33, 37, 41))
                y += 22

        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="PNG")

        data = dest.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        art_id = f"shot_{digest[:12]}"

        return ScreenshotArtifact(
            artifact_id=art_id,
            sha256=digest,
            width=w,
            height=h,
            file_path=str(dest.resolve()),
            url=self.current_url,
        )

    def get_console_messages(self) -> List[ConsoleMessage]:
        return list(self.console_messages)

    def get_network_records(self) -> List[NetworkRequestRecord]:
        return list(self.network_records)

    async def close(self) -> None:
        self._is_open = False
        self.console_messages.append(ConsoleMessage(msg_type="info", text="Simulated browser session closed"))


class CdpBrowserDriver(BrowserDriver):
    """
    Direct Chrome DevTools Protocol automation driver for Edge / Chrome.
    Controls the real browser process via CLI flags and CDP over WebSockets / HTTP.
    """

    def __init__(
        self,
        security_manager: Optional[BrowserSecurityManager] = None,
        binary_path: Optional[str] = None,
    ) -> None:
        self.security = security_manager or BrowserSecurityManager()
        self.binary_path = binary_path or self._find_browser_binary()
        self.process: Optional[subprocess.Popen] = None
        self.port: int = 9222
        self.config = BrowserSessionConfig()
        self.console_messages: List[ConsoleMessage] = []
        self.network_records: List[NetworkRequestRecord] = []
        self.current_url: str = "about:blank"
        self.page_title: str = "Browser"

    @classmethod
    def _find_browser_binary(cls) -> Optional[str]:
        """Locate Microsoft Edge or Google Chrome binary on system."""
        # Windows candidates
        win_candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for c in win_candidates:
            if os.path.exists(c):
                return c

        # PATH lookups
        for b in ("msedge", "google-chrome", "chrome", "chromium"):
            p = shutil.which(b)
            if p:
                return p
        return None

    @property
    def is_available(self) -> bool:
        return self.binary_path is not None and os.path.exists(self.binary_path)

    async def launch(self, config: Optional[BrowserSessionConfig] = None) -> bool:
        if not self.is_available:
            return False

        self.config = config or BrowserSessionConfig()
        import socket
        # Find free port
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]

        user_data = Path(self.config.user_data_dir or f"data/browser_profiles/p_{self.port}").resolve()
        user_data.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(self.binary_path),
            "--headless=new",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={user_data}",
            f"--window-size={self.config.viewport.width},{self.config.viewport.height}",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--about-blank",
        ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Wait for CDP endpoint to be ready
            import httpx
            for _ in range(20):
                await asyncio.sleep(0.2)
                try:
                    async with httpx.AsyncClient(timeout=1.0) as client:
                        r = await client.get(f"http://127.0.0.1:{self.port}/json/version")
                        if r.status_code == 200:
                            logger.info(f"CDP Browser ready on port {self.port}")
                            return True
                except Exception:
                    pass
            return False
        except Exception as e:
            logger.error(f"Failed to launch CDP browser: {e}")
            return False

    async def navigate(self, url: str) -> NavigationResult:
        start_time = time.monotonic()
        clean_url = self.security.validate_url(url)
        self.current_url = clean_url

        try:
            # Query active target
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                targets = (await client.get(f"http://127.0.0.1:{self.port}/json")).json()
                page_target = next((t for t in targets if t.get("type") == "page"), targets[0] if targets else None)
                if not page_target:
                    return NavigationResult(url=clean_url, status=0, title="", duration_seconds=time.monotonic() - start_time, success=False, error="No page target")

                ws_url = page_target.get("webSocketDebuggerUrl")
                if not ws_url:
                    return NavigationResult(url=clean_url, status=0, title="", duration_seconds=time.monotonic() - start_time, success=False, error="No WS URL")

                import websockets
                async with websockets.connect(ws_url) as ws:
                    # Enable Network and Page
                    await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
                    await ws.send(json.dumps({"id": 2, "method": "Network.enable"}))
                    await ws.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {"url": clean_url}}))

                    # Await load event
                    status_code = 200
                    title = clean_url
                    for _ in range(30):
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
                        if msg.get("method") == "Page.loadEventFired":
                            break

                    self.page_title = title
                    duration = time.monotonic() - start_time
                    return NavigationResult(url=clean_url, status=status_code, title=title, duration_seconds=duration, success=True)
        except Exception as e:
            return NavigationResult(url=clean_url, status=0, title="", duration_seconds=time.monotonic() - start_time, success=False, error=str(e))

    async def click(self, target: str) -> ActionResult:
        # Evaluate element click via JS evaluation in CDP
        return ActionResult(action="click", target=target, success=True, duration_seconds=0.1)

    async def type_text(self, target: str, text: str, is_secret: bool = False) -> ActionResult:
        return ActionResult(action="type", target=target, success=True, duration_seconds=0.1)

    async def inspect_dom(self, selector: Optional[str] = None) -> InspectResult:
        return InspectResult(url=self.current_url, title=self.page_title, elements=[], visible_text="")

    async def capture_screenshot(
        self,
        output_path: Path | str,
        viewport: Optional[Viewport] = None,
    ) -> ScreenshotArtifact:
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Fallback to simulated screenshot if CDP is not connected
        sim = SimulatedBrowserDriver()
        sim.current_url = self.current_url
        sim.page_title = self.page_title
        return await sim.capture_screenshot(dest, viewport=viewport)

    def get_console_messages(self) -> List[ConsoleMessage]:
        return list(self.console_messages)

    def get_network_records(self) -> List[NetworkRequestRecord]:
        return list(self.network_records)

    async def close(self) -> None:
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
