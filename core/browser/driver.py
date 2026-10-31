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
    AccessibilityAuditResult,
    ActionResult,
    BrowserSessionConfig,
    ConsoleMessage,
    DOMElement,
    ImageIntegrityResult,
    InspectResult,
    LayoutCheckResult,
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
    async def set_viewport(self, viewport: Viewport) -> bool:
        pass

    @abc.abstractmethod
    async def press_key(self, key: str) -> ActionResult:
        pass

    @abc.abstractmethod
    async def check_layout(
        self,
        viewports: Optional[List[Viewport]] = None,
        tolerance: float = 2.0,
    ) -> LayoutCheckResult:
        pass

    @abc.abstractmethod
    async def check_images(self, scroll_first: bool = True) -> ImageIntegrityResult:
        pass

    @abc.abstractmethod
    async def check_accessibility(self) -> AccessibilityAuditResult:
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
                    self.page_title = f"Error {resp.status_code}"
                    self.current_html = f"<!DOCTYPE html><html><head><title>Error {resp.status_code}</title></head><body><h1>Resource Error {resp.status_code}</h1><p>The requested resource could not be loaded: {clean_url}</p><button>Retry Navigation</button></body></html>"

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
            self.page_title = "Connection Error"
            self.current_html = f"<!DOCTYPE html><html><head><title>Connection Error</title></head><body><h1>Server Unreachable</h1><p>Failed to connect to {clean_url}: {err_msg}</p><button>Retry Navigation</button></body></html>"
            return NavigationResult(url=clean_url, status=0, title=self.page_title, duration_seconds=duration, success=False, error=err_msg)

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
        is_empty = not self.current_html or self.current_html.strip() in ("", "<html><head><title>Blank Page</title></head><body></body></html>")
        if is_empty:
            card_w = min(560, w - 60)
            card_x = (w - card_w) // 2
            draw.rectangle([(card_x, 100), (card_x + card_w, 270)], fill=(255, 255, 255), outline=(203, 213, 225))
            draw.rectangle([(card_x + 25, 125), (card_x + 150, 150)], fill=(239, 68, 68), outline=(220, 38, 38))
            draw.text((card_x + 35, 131), "PREVIEW ERROR", fill=(255, 255, 255))
            draw.text((card_x + 25, 165), "No Document Content Rendered", fill=(15, 23, 42))
            draw.text((card_x + 25, 195), f"URL: {self.current_url[:65]}", fill=(100, 116, 139))
            draw.text((card_x + 25, 225), "Verify that index.html exists in the selected workspace.", fill=(100, 116, 139))
        else:
            soup = BeautifulSoup(self.current_html, "html.parser")
            y = 70
            for tag in (soup.body or soup).find_all(["h1", "h2", "h3", "p", "button", "input", "table", "div", "img"], recursive=True):
                if y > h - 40:
                    break
                text = tag.get_text().strip()
                if not text and tag.name not in ("button", "input", "img"):
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
                elif tag.name == "img":
                    alt = tag.get("alt") or tag.get("src") or "Image Asset"
                    draw.rectangle([(30, y), (min(w - 30, 420), y + 70)], fill=(241, 245, 249), outline=(203, 213, 225))
                    draw.text((45, y + 26), f"[IMAGE: {alt[:35]}]", fill=(71, 85, 105))
                    y += 85
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

    async def set_viewport(self, viewport: Viewport) -> bool:
        self.config.viewport = viewport
        try:
            await self._send_cdp(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": viewport.width,
                    "height": viewport.height,
                    "deviceScaleFactor": viewport.device_scale_factor,
                    "mobile": viewport.is_mobile or viewport.width < 500,
                },
            )
            await asyncio.sleep(0.1)
            return True
        except Exception as e:
            logger.warning(f"CDP set_viewport failed: {e}")
            return False

    async def press_key(self, key: str) -> ActionResult:
        start_time = time.monotonic()
        clean_key = str(key).strip()
        js = f"""
        ((k) => {{
            const target = document.activeElement || document.body;
            const evtInit = {{ key: k, code: k, bubbles: true, cancelable: true }};
            target.dispatchEvent(new KeyboardEvent('keydown', evtInit));
            target.dispatchEvent(new KeyboardEvent('keypress', evtInit));
            target.dispatchEvent(new KeyboardEvent('keyup', evtInit));
            if (k === 'Enter') {{
                if (target.form) {{
                    target.form.dispatchEvent(new Event('submit', {{ bubbles: true, cancelable: true }}));
                }} else if (typeof target.click === 'function') {{
                    target.click();
                }}
            }} else if (k === 'Escape') {{
                const modal = document.querySelector('.modal.active, dialog[open]');
                if (modal) {{
                    modal.classList.remove('active');
                    if (typeof modal.close === 'function') modal.close();
                }}
            }}
            return {{ tag: target.tagName.toLowerCase(), id: target.id || '' }};
        }})({json.dumps(clean_key)})
        """
        try:
            try:
                await self._send_cdp("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": clean_key})
                await self._send_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": clean_key})
            except Exception:
                pass
            res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
            val = res.get("result", {}).get("value", {})
            duration = time.monotonic() - start_time
            return ActionResult(
                action="press_key",
                target=clean_key,
                success=True,
                duration_seconds=duration,
                after_state=f"Dispatched '{clean_key}' on <{val.get('tag', 'body')}>",
            )
        except Exception as e:
            return ActionResult(action="press_key", target=clean_key, success=False, duration_seconds=time.monotonic() - start_time, error=str(e))

    async def check_layout(
        self,
        viewports: Optional[List[Viewport]] = None,
        tolerance: float = 2.0,
    ) -> LayoutCheckResult:
        vps = viewports or Viewport.standard_matrix()
        orig_vp = self.config.viewport
        results: Dict[str, Any] = {}
        failed: List[str] = []

        js_measure = f"""
        ((tol) => {{
            const doc = document.documentElement;
            const body = document.body;
            const cw = doc.clientWidth;
            const sw = doc.scrollWidth;
            const hasDocOverflow = sw > (cw + tol);

            const offenders = [];
            const checkElements = document.querySelectorAll(
                'header, h1, h2, h3, .subtitle, nav, .tab-nav, .vehicle-nav, .card, .vehicle-card, .gallery-grid, figure, article, section, .modal-content, button'
            );
            checkElements.forEach(el => {{
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {{
                    if (r.right > (cw + tol) || r.width > (cw + tol)) {{
                        const desc = `<${{el.tagName.toLowerCase()}}${{el.id ? '#' + el.id : ''}}${{el.className ? '.' + Array.from(el.classList).slice(0, 2).join('.') : ''}}>`;
                        offenders.push({{
                            element: desc,
                            width: Math.round(r.width),
                            right: Math.round(r.right),
                            viewportWidth: cw,
                            overflowPx: Math.round(Math.max(r.right - cw, r.width - cw))
                        }});
                    }}
                }}
            }});

            return {{
                clientWidth: cw,
                scrollWidth: sw,
                hasOverflow: hasDocOverflow || offenders.length > 0,
                overflowPx: Math.round(Math.max(0, sw - cw)),
                offendingElements: offenders.slice(0, 10)
            }};
        }})({tolerance})
        """

        try:
            for vp in vps:
                vp_key = f"{vp.width}x{vp.height}"
                await self.set_viewport(vp)
                await asyncio.sleep(0.2)
                res = await self._send_cdp("Runtime.evaluate", {"expression": js_measure, "returnByValue": True})
                val = res.get("result", {}).get("value", {})
                is_ov = bool(val.get("hasOverflow", False))
                if is_ov:
                    failed.append(vp_key)
                results[vp_key] = {
                    "viewport": vp.to_dict(),
                    "clientWidth": val.get("clientWidth", vp.width),
                    "scrollWidth": val.get("scrollWidth", vp.width),
                    "hasOverflow": is_ov,
                    "overflowPx": val.get("overflowPx", 0),
                    "offendingElements": val.get("offendingElements", []),
                }
        finally:
            await self.set_viewport(orig_vp)

        passed = len(failed) == 0
        summary = "All viewports passed layout checks." if passed else f"Layout overflow detected in: {', '.join(failed)}"
        return LayoutCheckResult(
            passed=passed,
            total_viewports=len(vps),
            failed_viewports=failed,
            viewports=results,
            summary=summary,
        )

    async def check_images(self, scroll_first: bool = True) -> ImageIntegrityResult:
        if scroll_first:
            try:
                await self._send_cdp("Runtime.evaluate", {"expression": "window.scrollTo(0, document.body.scrollHeight)"})
                await asyncio.sleep(0.25)
                await self._send_cdp("Runtime.evaluate", {"expression": "window.scrollTo(0, 0)"})
                await asyncio.sleep(0.15)
            except Exception:
                pass

        js = """
        (() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            return imgs
                .filter(img => {
                    const rawSrc = img.getAttribute('src');
                    const isPlaceholder = (!rawSrc || rawSrc.trim() === '') && (img.id === 'modal-img' || img.closest('.modal, dialog, template'));
                    return !isPlaceholder;
                })
                .map(img => {
                    const complete = img.complete;
                    const nw = img.naturalWidth;
                    const nh = img.naturalHeight;
                    const isLoaded = complete && nw > 0 && nh > 0;
                    return {
                        src: img.currentSrc || img.src || '',
                        alt: img.alt || '',
                        complete: complete,
                        naturalWidth: nw,
                        naturalHeight: nh,
                        isLoaded: isLoaded
                    };
                });
        })()
        """
        try:
            res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
            details = res.get("result", {}).get("value", [])
            loaded = sum(1 for img in details if img.get("isLoaded"))
            broken = len(details) - loaded
            return ImageIntegrityResult(
                passed=(broken == 0),
                total_images=len(details),
                loaded_images=loaded,
                broken_images=broken,
                details=details,
            )
        except Exception as e:
            logger.warning(f"CDP check_images failed: {e}")
            return ImageIntegrityResult(passed=False, total_images=0, loaded_images=0, broken_images=0, details=[])

    async def check_accessibility(self) -> AccessibilityAuditResult:
        js = """
        (() => {
            const issues = [];
            // 1. Headings
            const h1s = document.querySelectorAll('h1');
            if (h1s.length === 0) {
                issues.push({ type: 'heading', message: 'No <h1> element found on page', severity: 'error' });
            } else if (h1s.length > 1) {
                issues.push({ type: 'heading_warning', message: `Multiple (${h1s.length}) <h1> elements found`, severity: 'warning' });
            }

            // 2. Interactive control accessible names
            document.querySelectorAll('button, a, [role="button"]').forEach((el, idx) => {
                const text = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                const hasImgAlt = !!el.querySelector('img[alt]');
                if (!text && !hasImgAlt) {
                    issues.push({
                        type: 'accessible_name',
                        tag: el.tagName.toLowerCase(),
                        selector: el.id ? '#' + el.id : `${el.className || ''} [index ${idx}]`,
                        message: `Interactive <${el.tagName.toLowerCase()}> is missing visible text, aria-label, or title`,
                        severity: 'error'
                    });
                }
            });

            // 3. Image alt attributes
            document.querySelectorAll('img').forEach((img, idx) => {
                if (!img.hasAttribute('alt')) {
                    issues.push({
                        type: 'img_alt',
                        src: (img.currentSrc || img.src || '').slice(-40),
                        message: 'Image is missing alt attribute',
                        severity: 'error'
                    });
                }
            });

            // 4. Form labels
            document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea').forEach((inp, idx) => {
                const id = inp.id;
                const hasLabel = !!(id && document.querySelector(`label[for="${id}"]`));
                const hasParentLabel = !!inp.closest('label');
                const hasAria = !!(inp.getAttribute('aria-label') || inp.getAttribute('aria-labelledby'));
                if (!hasLabel && !hasParentLabel && !hasAria) {
                    issues.push({
                        type: 'form_label',
                        id: id || `input_${idx}`,
                        message: `Form input '${id || inp.name || idx}' missing associated <label> or aria-label`,
                        severity: 'error'
                    });
                }
            });

            const critical = issues.filter(i => i.severity === 'error');
            const score = Math.max(0, 100 - (critical.length * 15 + (issues.length - critical.length) * 5));
            return {
                passed: critical.length === 0,
                score: score,
                total_issues: issues.length,
                issues: issues
            };
        })()
        """
        try:
            res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
            val = res.get("result", {}).get("value", {})
            return AccessibilityAuditResult(
                passed=val.get("passed", True),
                score=val.get("score", 100),
                total_issues=val.get("total_issues", 0),
                issues=val.get("issues", []),
            )
        except Exception as e:
            logger.warning(f"CDP check_accessibility failed: {e}")
            return AccessibilityAuditResult(passed=False, score=0, total_issues=1, issues=[{"type": "error", "message": str(e), "severity": "error"}])

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
        self.current_html: str = ""
        self._ws = None
        self._msg_id: int = 0

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

    async def _get_ws(self):
        """Retrieve or establish an active WebSocket connection to the CDP page target."""
        if self._ws is not None and not getattr(self._ws, "closed", True) and not getattr(self._ws, "is_closing", False):
            return self._ws

        import httpx
        import websockets

        async with httpx.AsyncClient(timeout=10.0) as client:
            targets = (await client.get(f"http://127.0.0.1:{self.port}/json")).json()
            page_target = next((t for t in targets if t.get("type") == "page"), targets[0] if targets else None)
            if not page_target:
                raise RuntimeError("No CDP page target available")
            ws_url = page_target.get("webSocketDebuggerUrl")
            if not ws_url:
                raise RuntimeError("No WebSocket debugger URL on page target")

        self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024, ping_interval=None)
        await self._send_cdp("Page.enable")
        await self._send_cdp("Network.enable")
        await self._send_cdp("Runtime.enable")
        return self._ws

    async def _send_cdp(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Dict[str, Any]:
        """Send a CDP command and await its specific response, recording background events."""
        ws = await self._get_ws()
        self._msg_id += 1
        req_id = self._msg_id
        payload = {"id": req_id, "method": method, "params": params or {}}
        await ws.send(json.dumps(payload))

        start_t = time.monotonic()
        while time.monotonic() - start_t < timeout:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msg = json.loads(raw)

            m_method = msg.get("method")
            if m_method == "Runtime.consoleAPICalled":
                p = msg.get("params", {})
                m_type = p.get("type", "log")
                args = p.get("args", [])
                txt = " ".join(str(a.get("value", a.get("description", ""))) for a in args)
                self.console_messages.append(ConsoleMessage(msg_type="error" if m_type == "error" else "log", text=txt))
            elif m_method == "Log.entryAdded":
                entry = msg.get("params", {}).get("entry", {})
                lvl = entry.get("level", "info")
                txt = entry.get("text", "")
                self.console_messages.append(ConsoleMessage(msg_type="error" if lvl == "error" else "log", text=txt))
            elif m_method == "Network.requestWillBeSent":
                p = msg.get("params", {})
                req = p.get("request", {})
                self.network_records.append(
                    NetworkRequestRecord(
                        request_id=p.get("requestId", ""),
                        url=req.get("url", ""),
                        method=req.get("method", "GET"),
                        resource_type=p.get("type", "").lower() or "other",
                    )
                )
            elif m_method == "Network.responseReceived":
                p = msg.get("params", {})
                resp = p.get("response", {})
                req_id_str = p.get("requestId", "")
                for r in self.network_records:
                    if r.request_id == req_id_str:
                        r.status = resp.get("status")
                        r.response_headers = self.security.redact_headers(resp.get("headers", {}))
                        break
            elif m_method == "Network.loadingFailed":
                p = msg.get("params", {})
                req_id_str = p.get("requestId", "")
                for r in self.network_records:
                    if r.request_id == req_id_str:
                        r.error = p.get("errorText", "Failed")
                        break

            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP command {method} failed: {msg['error'].get('message', msg['error'])}")
                return msg.get("result", {})

        raise TimeoutError(f"CDP command {method} timed out after {timeout}s")

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
            ws = await self._get_ws()

            # Set viewport metrics from config
            if self.config and self.config.viewport:
                await self._send_cdp(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": self.config.viewport.width,
                        "height": self.config.viewport.height,
                        "deviceScaleFactor": 1,
                        "mobile": self.config.viewport.width < 500,
                    },
                )

            self._msg_id += 1
            nav_id = self._msg_id
            await ws.send(json.dumps({"id": nav_id, "method": "Page.navigate", "params": {"url": clean_url}}))

            nav_success = False
            error_text = None
            status_code = 200

            while time.monotonic() - start_time < (self.config.timeout or 15.0):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    break
                msg = json.loads(raw)
                m_method = msg.get("method")
                if m_method == "Runtime.consoleAPICalled":
                    p = msg.get("params", {})
                    m_type = p.get("type", "log")
                    args = p.get("args", [])
                    txt = " ".join(str(a.get("value", a.get("description", ""))) for a in args)
                    self.console_messages.append(ConsoleMessage(msg_type="error" if m_type == "error" else "log", text=txt))
                elif m_method == "Network.requestWillBeSent":
                    p = msg.get("params", {})
                    req = p.get("request", {})
                    self.network_records.append(
                        NetworkRequestRecord(
                            request_id=p.get("requestId", ""),
                            url=req.get("url", ""),
                            method=req.get("method", "GET"),
                            resource_type=p.get("type", "").lower() or "other",
                        )
                    )
                elif m_method == "Network.responseReceived":
                    p = msg.get("params", {})
                    resp = p.get("response", {})
                    req_id_str = p.get("requestId", "")
                    for r in self.network_records:
                        if r.request_id == req_id_str:
                            r.status = resp.get("status")
                            r.response_headers = self.security.redact_headers(resp.get("headers", {}))
                            break
                elif m_method == "Network.loadingFailed":
                    p = msg.get("params", {})
                    req_id_str = p.get("requestId", "")
                    for r in self.network_records:
                        if r.request_id == req_id_str:
                            r.error = p.get("errorText", "Failed")
                            break

                if m_method == "Page.loadEventFired":
                    nav_success = True
                    break
                if msg.get("id") == nav_id:
                    res = msg.get("result", {})
                    if res.get("errorText"):
                        error_text = res.get("errorText")
                        break

            for rec in reversed(self.network_records):
                if rec.url == clean_url and rec.status:
                    status_code = rec.status
                    break

            # Evaluate document title and outerHTML
            try:
                eval_res = await self._send_cdp(
                    "Runtime.evaluate",
                    {"expression": "({title: document.title, html: document.documentElement.outerHTML})", "returnByValue": True},
                    timeout=5.0,
                )
                val = eval_res.get("result", {}).get("value", {})
                self.page_title = val.get("title") or clean_url
                self.current_html = val.get("html") or ""
            except Exception:
                self.page_title = clean_url
                self.current_html = ""

            duration = time.monotonic() - start_time

            # Handle HTTP errors with diagnostic screen
            if status_code >= 400 or error_text:
                diag_html = (
                    f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>HERMES Browser — Resource Error</title>"
                    f"<style>body {{ margin: 0; padding: 40px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
                    f"background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 80vh; }} "
                    f".card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 32px; max-width: 600px; width: 100%; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.5); }} "
                    f".badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; text-transform: uppercase; background: #ef4444; color: #fff; margin-bottom: 16px; }} "
                    f"h1 {{ font-size: 20px; font-weight: 700; margin: 0 0 12px 0; color: #fff; }} "
                    f"p {{ font-size: 14px; line-height: 1.6; color: #94a3b8; margin: 0 0 20px 0; }} "
                    f".url-box {{ background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 10px 14px; font-family: monospace; font-size: 13px; color: #38bdf8; word-break: break-all; margin-bottom: 24px; }} "
                    f".actions {{ display: flex; gap: 12px; }} "
                    f".btn {{ background: #2563eb; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; text-decoration: none; font-size: 13px; }}"
                    f"</style></head><body><div class='card'><div class='badge'>Error {status_code}</div>"
                    f"<h1>Resource Not Found</h1><p>The preview server could not locate the requested resource. Check that the file exists in the active workspace and that the dev server is active.</p>"
                    f"<div class='url-box'>{clean_url}</div>"
                    f"<div class='actions'><button class='btn' onclick='location.reload()'>Retry Navigation</button></div></div></body></html>"
                )
                try:
                    tree = await self._send_cdp("Page.getFrameTree")
                    frame_id = tree["frameTree"]["frame"]["id"]
                    await self._send_cdp("Page.setDocumentContent", {"frameId": frame_id, "html": diag_html})
                    self.current_html = diag_html
                    self.page_title = f"Error {status_code}"
                except Exception:
                    pass
                return NavigationResult(url=clean_url, status=status_code, title=self.page_title, duration_seconds=duration, success=False, error=error_text or f"HTTP {status_code}")

            return NavigationResult(url=clean_url, status=status_code, title=self.page_title, duration_seconds=duration, success=True)
        except Exception as e:
            duration = time.monotonic() - start_time
            return NavigationResult(url=clean_url, status=0, title="", duration_seconds=duration, success=False, error=str(e))

    async def click(self, target: str) -> ActionResult:
        start_time = time.monotonic()
        js = f"""
        ((t) => {{
            let el = null;
            try {{
                el = document.querySelector(t);
            }} catch(e) {{}}
            if (!el) {{
                const candidates = Array.from(document.querySelectorAll('button, a, input, [role="button"], span, div'));
                for (const c of candidates) {{
                    const text = (c.innerText || '').trim().toLowerCase();
                    const aria = (c.getAttribute('aria-label') || '').trim().toLowerCase();
                    const targetLower = t.toLowerCase();
                    if (text.includes(targetLower) || aria.includes(targetLower) || c.id === t) {{
                        el = c;
                        break;
                    }}
                }}
            }}
            if (el) {{
                el.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                el.click();
                return {{
                    found: true,
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText || el.getAttribute('aria-label') || el.value || '').trim().slice(0, 50)
                }};
            }}
            return {{ found: false }};
        }})({json.dumps(target)})
        """
        try:
            res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
            val = res.get("result", {}).get("value", {})
            duration = time.monotonic() - start_time
            if val.get("found"):
                return ActionResult(action="click", target=target, success=True, duration_seconds=duration, after_state=f"Clicked <{val.get('tag')}>: {val.get('text')}")
            else:
                return ActionResult(action="click", target=target, success=False, duration_seconds=duration, error=f"Element '{target}' not found in CDP browser DOM")
        except Exception as e:
            return ActionResult(action="click", target=target, success=False, duration_seconds=time.monotonic() - start_time, error=str(e))

    async def type_text(self, target: str, text: str, is_secret: bool = False) -> ActionResult:
        start_time = time.monotonic()
        js = f"""
        ((t, val) => {{
            let el = null;
            try {{
                el = document.querySelector(t);
            }} catch(e) {{}}
            if (!el) {{
                el = document.getElementById(t) ||
                     document.querySelector(`[name="${{t}}"]`) ||
                     document.querySelector(`[placeholder="${{t}}"]`);
            }}
            if (el) {{
                el.focus();
                el.value = val;
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return {{ found: true, tag: el.tagName.toLowerCase() }};
            }}
            return {{ found: false }};
        }})({json.dumps(target)}, {json.dumps(text)})
        """
        try:
            res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
            val = res.get("result", {}).get("value", {})
            duration = time.monotonic() - start_time
            if val.get("found"):
                return ActionResult(action="type", target=target, success=True, duration_seconds=duration, after_state=f"Typed text into <{val.get('tag')}>")
            else:
                return ActionResult(action="type", target=target, success=False, duration_seconds=duration, error=f"Input element '{target}' not found in CDP browser DOM")
        except Exception as e:
            return ActionResult(action="type", target=target, success=False, duration_seconds=time.monotonic() - start_time, error=str(e))

    async def inspect_dom(self, selector: Optional[str] = None) -> InspectResult:
        js = f"""
        (() => {{
            const sel = {json.dumps(selector)} || 'h1, h2, h3, h4, p, button, a, input, select, textarea, img, canvas, dialog, article, section, nav';
            let els = [];
            try {{
                els = Array.from(document.querySelectorAll(sel));
            }} catch(e) {{
                els = [];
            }}
            return {{
                title: document.title,
                interactive_count: document.querySelectorAll('button, a, input, select, textarea').length,
                elements: els.map(e => ({{
                    tag: e.tagName.toLowerCase(),
                    id: e.id || '',
                    classes: Array.from(e.classList || []),
                    text: (e.innerText || e.getAttribute('alt') || e.value || '').trim().slice(0, 100),
                    visible: e.offsetParent !== null || e.tagName.toLowerCase() === 'dialog'
                }})),
                visible_text: document.body ? document.body.innerText.slice(0, 5000) : ''
            }};
        }})()
        """
        try:
            res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
            val = res.get("result", {}).get("value", {})
            return InspectResult(
                url=self.current_url,
                title=val.get("title") or self.page_title,
                elements=val.get("elements", []),
                visible_text=val.get("visible_text", ""),
                interactive_count=val.get("interactive_count", 0),
            )
        except Exception:
            return InspectResult(url=self.current_url, title=self.page_title, elements=[], visible_text="")

    async def capture_screenshot(
        self,
        output_path: Path | str,
        viewport: Optional[Viewport] = None,
    ) -> ScreenshotArtifact:
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        vp = viewport or self.config.viewport
        w = vp.width
        h = vp.height

        try:
            await self._send_cdp(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": w,
                    "height": h,
                    "deviceScaleFactor": 1,
                    "mobile": w < 500,
                },
            )
            await asyncio.sleep(0.3)
            res = await self._send_cdp("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            data_b64 = res.get("data")
            if not data_b64:
                raise RuntimeError("CDP Page.captureScreenshot returned empty data")

            img_bytes = base64.b64decode(data_b64)
            dest.write_bytes(img_bytes)

            digest = hashlib.sha256(img_bytes).hexdigest()
            art_id = f"shot_{digest[:12]}"
            return ScreenshotArtifact(
                artifact_id=art_id,
                sha256=digest,
                width=w,
                height=h,
                file_path=str(dest.resolve()),
                url=self.current_url,
            )
        except Exception as e:
            logger.warning(f"CDP capture_screenshot failed ({e}), falling back to simulated renderer")
            sim = SimulatedBrowserDriver(security_manager=self.security)
            sim.current_url = self.current_url
            sim.page_title = self.page_title
            sim.current_html = self.current_html
            return await sim.capture_screenshot(dest, viewport=vp)

    def get_console_messages(self) -> List[ConsoleMessage]:
        return list(self.console_messages)

    def get_network_records(self) -> List[NetworkRequestRecord]:
        return list(self.network_records)

    async def set_viewport(self, viewport: Viewport) -> bool:
        self.config.viewport = viewport
        try:
            await self._send_cdp(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": viewport.width,
                    "height": viewport.height,
                    "deviceScaleFactor": viewport.device_scale_factor,
                    "mobile": viewport.is_mobile or viewport.width < 500,
                },
            )
            await asyncio.sleep(0.1)
            return True
        except Exception as e:
            logger.warning(f"CDP set_viewport failed: {e}")
            return False

    async def press_key(self, key: str) -> ActionResult:
        start_time = time.monotonic()
        clean_key = str(key).strip()
        js = f"""
        ((k) => {{
            const target = document.activeElement || document.body;
            const evtInit = {{ key: k, code: k, bubbles: true, cancelable: true }};
            target.dispatchEvent(new KeyboardEvent('keydown', evtInit));
            target.dispatchEvent(new KeyboardEvent('keypress', evtInit));
            target.dispatchEvent(new KeyboardEvent('keyup', evtInit));
            if (k === 'Enter') {{
                if (target.form) {{
                    target.form.dispatchEvent(new Event('submit', {{ bubbles: true, cancelable: true }}));
                }} else if (typeof target.click === 'function') {{
                    target.click();
                }}
            }} else if (k === 'Escape') {{
                const modal = document.querySelector('.modal.active, dialog[open]');
                if (modal) {{
                    modal.classList.remove('active');
                    if (typeof modal.close === 'function') modal.close();
                }}
            }}
            return {{ tag: target.tagName.toLowerCase(), id: target.id || '' }};
        }})({json.dumps(clean_key)})
        """
        try:
            try:
                await self._send_cdp("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": clean_key})
                await self._send_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": clean_key})
            except Exception:
                pass
            res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
            val = res.get("result", {}).get("value", {})
            duration = time.monotonic() - start_time
            return ActionResult(
                action="press_key",
                target=clean_key,
                success=True,
                duration_seconds=duration,
                after_state=f"Dispatched '{clean_key}' on <{val.get('tag', 'body')}>",
            )
        except Exception as e:
            return ActionResult(action="press_key", target=clean_key, success=False, duration_seconds=time.monotonic() - start_time, error=str(e))

    async def check_layout(
        self,
        viewports: Optional[List[Viewport]] = None,
        tolerance: float = 2.0,
    ) -> LayoutCheckResult:
        vps = viewports or Viewport.standard_matrix()
        orig_vp = self.config.viewport
        results: Dict[str, Any] = {}
        failed: List[str] = []

        js_measure = f"""
        ((tol) => {{
            const doc = document.documentElement;
            const body = document.body;
            const cw = doc.clientWidth;
            const sw = doc.scrollWidth;
            const hasDocOverflow = sw > (cw + tol);

            const offenders = [];
            const checkElements = document.querySelectorAll(
                'header, h1, h2, h3, .subtitle, nav, .tab-nav, .vehicle-nav, .card, .vehicle-card, .gallery-grid, figure, article, section, .modal-content, button'
            );
            checkElements.forEach(el => {{
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {{
                    if (r.right > (cw + tol) || r.width > (cw + tol)) {{
                        const desc = `<${{el.tagName.toLowerCase()}}${{el.id ? '#' + el.id : ''}}${{el.className ? '.' + Array.from(el.classList).slice(0, 2).join('.') : ''}}>`;
                        offenders.push({{
                            element: desc,
                            width: Math.round(r.width),
                            right: Math.round(r.right),
                            viewportWidth: cw,
                            overflowPx: Math.round(Math.max(r.right - cw, r.width - cw))
                        }});
                    }}
                }}
            }});

            return {{
                clientWidth: cw,
                scrollWidth: sw,
                hasOverflow: hasDocOverflow || offenders.length > 0,
                overflowPx: Math.round(Math.max(0, sw - cw)),
                offendingElements: offenders.slice(0, 10)
            }};
        }})({tolerance})
        """

        try:
            for vp in vps:
                vp_key = f"{vp.width}x{vp.height}"
                await self.set_viewport(vp)
                await asyncio.sleep(0.2)
                res = await self._send_cdp("Runtime.evaluate", {"expression": js_measure, "returnByValue": True})
                val = res.get("result", {}).get("value", {})
                is_ov = bool(val.get("hasOverflow", False))
                if is_ov:
                    failed.append(vp_key)
                results[vp_key] = {
                    "viewport": vp.to_dict(),
                    "clientWidth": val.get("clientWidth", vp.width),
                    "scrollWidth": val.get("scrollWidth", vp.width),
                    "hasOverflow": is_ov,
                    "overflowPx": val.get("overflowPx", 0),
                    "offendingElements": val.get("offendingElements", []),
                }
        finally:
            await self.set_viewport(orig_vp)

        passed = len(failed) == 0
        summary = "All viewports passed layout checks." if passed else f"Layout overflow detected in: {', '.join(failed)}"
        return LayoutCheckResult(
            passed=passed,
            total_viewports=len(vps),
            failed_viewports=failed,
            viewports=results,
            summary=summary,
        )

    async def check_images(self, scroll_first: bool = True) -> ImageIntegrityResult:
        if scroll_first:
            try:
                await self._send_cdp("Runtime.evaluate", {"expression": "window.scrollTo(0, document.body.scrollHeight)"})
                await asyncio.sleep(0.25)
                await self._send_cdp("Runtime.evaluate", {"expression": "window.scrollTo(0, 0)"})
                await asyncio.sleep(0.15)
            except Exception:
                pass

        js = """
        (() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            return imgs
                .filter(img => {
                    const rawSrc = img.getAttribute('src');
                    const isPlaceholder = (!rawSrc || rawSrc.trim() === '') && (img.id === 'modal-img' || img.closest('.modal, dialog, template'));
                    return !isPlaceholder;
                })
                .map(img => {
                    const complete = img.complete;
                    const nw = img.naturalWidth;
                    const nh = img.naturalHeight;
                    const isLoaded = complete && nw > 0 && nh > 0;
                    return {
                        src: img.currentSrc || img.src || '',
                        alt: img.alt || '',
                        complete: complete,
                        naturalWidth: nw,
                        naturalHeight: nh,
                        isLoaded: isLoaded
                    };
                });
        })()
        """
        try:
            res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
            details = res.get("result", {}).get("value", [])
            loaded = sum(1 for img in details if img.get("isLoaded"))
            broken = len(details) - loaded
            return ImageIntegrityResult(
                passed=(broken == 0),
                total_images=len(details),
                loaded_images=loaded,
                broken_images=broken,
                details=details,
            )
        except Exception as e:
            logger.warning(f"CDP check_images failed: {e}")
            return ImageIntegrityResult(passed=False, total_images=0, loaded_images=0, broken_images=0, details=[])

    async def check_accessibility(self) -> AccessibilityAuditResult:
        js = """
        (() => {
            const issues = [];
            // 1. Headings
            const h1s = document.querySelectorAll('h1');
            if (h1s.length === 0) {
                issues.push({ type: 'heading', message: 'No <h1> element found on page', severity: 'error' });
            } else if (h1s.length > 1) {
                issues.push({ type: 'heading_warning', message: `Multiple (${h1s.length}) <h1> elements found`, severity: 'warning' });
            }

            // 2. Interactive control accessible names
            document.querySelectorAll('button, a, [role="button"]').forEach((el, idx) => {
                const text = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                const hasImgAlt = !!el.querySelector('img[alt]');
                if (!text && !hasImgAlt) {
                    issues.push({
                        type: 'accessible_name',
                        tag: el.tagName.toLowerCase(),
                        selector: el.id ? '#' + el.id : `${el.className || ''} [index ${idx}]`,
                        message: `Interactive <${el.tagName.toLowerCase()}> is missing visible text, aria-label, or title`,
                        severity: 'error'
                    });
                }
            });

            // 3. Image alt attributes
            document.querySelectorAll('img').forEach((img, idx) => {
                if (!img.hasAttribute('alt')) {
                    issues.push({
                        type: 'img_alt',
                        src: (img.currentSrc || img.src || '').slice(-40),
                        message: 'Image is missing alt attribute',
                        severity: 'error'
                    });
                }
            });

            // 4. Form labels
            document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), select, textarea').forEach((inp, idx) => {
                const id = inp.id;
                const hasLabel = !!(id && document.querySelector(`label[for="${id}"]`));
                const hasParentLabel = !!inp.closest('label');
                const hasAria = !!(inp.getAttribute('aria-label') || inp.getAttribute('aria-labelledby'));
                if (!hasLabel && !hasParentLabel && !hasAria) {
                    issues.push({
                        type: 'form_label',
                        id: id || `input_${idx}`,
                        message: `Form input '${id || inp.name || idx}' missing associated <label> or aria-label`,
                        severity: 'error'
                    });
                }
            });

            const critical = issues.filter(i => i.severity === 'error');
            const score = Math.max(0, 100 - (critical.length * 15 + (issues.length - critical.length) * 5));
            return {
                passed: critical.length === 0,
                score: score,
                total_issues: issues.length,
                issues: issues
            };
        })()
        """
        try:
            res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
            val = res.get("result", {}).get("value", {})
            return AccessibilityAuditResult(
                passed=val.get("passed", True),
                score=val.get("score", 100),
                total_issues=val.get("total_issues", 0),
                issues=val.get("issues", []),
            )
        except Exception as e:
            logger.warning(f"CDP check_accessibility failed: {e}")
            return AccessibilityAuditResult(passed=False, score=0, total_issues=1, issues=[{"type": "error", "message": str(e), "severity": "error"}])

    async def close(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self.process:
            pid = self.process.pid
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5)
            except Exception:
                pass
            try:
                import psutil
                if psutil.pid_exists(pid):
                    p = psutil.Process(pid)
                    p.kill()
                    p.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                    self.process.wait(timeout=1.0)
                except Exception:
                    pass
            self.process = None
