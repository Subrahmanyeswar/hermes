# tools/web_fetch_tools.py
"""
Secure Web Fetch Tool for HERMES.
Fetches web content with strict SSRF protection, size caps, safe redirect following,
HTML-to-Markdown conversion via BeautifulSoup, and automatic Jina Reader fallback.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from loguru import logger

from tools.base import BaseTool, ToolResult
from tools.registry import tool
from core.security.web_security import validate_safe_url, SSRFSecurityViolation
from config.research_config import (
    WEB_FETCH_MAX_CHARS,
    WEB_FETCH_TIMEOUT_SECONDS,
    WEB_FETCH_MAX_BYTES,
)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def html_to_clean_markdown(html_content: str, base_url: str = "") -> str:
    """
    Extract readable text/markdown from HTML.
    Removes clutter (scripts, styles, navigation, footer, ads) and preserves headings, links, and lists.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # 1. Decompose non-content tags
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe", "svg", "button", "form"]):
        tag.decompose()

    # 2. Convert links to markdown
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        if text and href and not href.startswith("javascript:"):
            resolved = urljoin(base_url, href) if base_url else href
            a.replace_with(f" [{text}]({resolved}) ")

    # 3. Convert headers
    for h_level in range(1, 7):
        for h in soup.find_all(f"h{h_level}"):
            text = h.get_text(strip=True)
            if text:
                prefix = "#" * h_level
                h.replace_with(f"\n\n{prefix} {text}\n\n")

    # 4. Convert list items
    for li in soup.find_all("li"):
        text = li.get_text(strip=True)
        if text:
            li.replace_with(f"\n- {text}")

    # 5. Extract text and normalize whitespace
    text = soup.get_text()
    # Normalize multiple newlines and spaces
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


@tool(
    name="web_fetch",
    description="Fetch and extract structured markdown or text content from a public web page with SSRF security.",
    permissions=["network_read"],
    risk_score=0.2,
    blocked_in=[],
)
class WebFetchTool(BaseTool):
    """Secure web fetch tool with SSRF protection, redirect verification, and Jina Reader fallback."""

    class Input(BaseModel):
        url: str = Field(
            ...,
            description="The public HTTP or HTTPS URL to fetch",
            min_length=8,
            max_length=2048,
        )
        max_chars: int = Field(
            default=WEB_FETCH_MAX_CHARS,
            ge=100,
            le=50000,
            description="Maximum characters of extracted content to return",
        )
        extract_mode: str = Field(
            default="markdown",
            description="Extraction mode: 'markdown', 'text', or 'raw'",
        )

    def execute(self, inp: Any) -> ToolResult:
        if isinstance(inp, dict):
            inp = self.Input(**inp)
        start_time = time.monotonic()
        raw_url = inp.url.strip()

        # ── 1. SSRF Safety Check ──────────────────────────────────────────
        try:
            safe_target_url = validate_safe_url(raw_url)
        except SSRFSecurityViolation as e:
            logger.warning(f"web_fetch blocked by SSRF policy: {raw_url} - {e}")
            return ToolResult(
                success=False,
                output="",
                error=f"SSRF Security Violation: {str(e)}",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )

        headers = {
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # ── 2. Safe Fetch with Redirect Verification ─────────────────────
        current_url = safe_target_url
        response_text = ""
        content_type = ""
        max_redirects = 5

        try:
            with httpx.Client(timeout=WEB_FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client:
                for redirect_count in range(max_redirects + 1):
                    # Validate URL for every redirect hop
                    safe_url = validate_safe_url(current_url)

                    # Stream with size ceiling
                    with client.stream("GET", safe_url, headers=headers) as resp:
                        if resp.status_code in (301, 302, 303, 307, 308):
                            loc = resp.headers.get("Location")
                            if not loc:
                                raise ValueError(f"HTTP {resp.status_code} redirect missing Location header")
                            current_url = urljoin(safe_url, loc)
                            logger.debug(f"web_fetch following redirect to: {current_url}")
                            continue

                        if not (200 <= resp.status_code < 300):
                            duration = time.monotonic() - start_time
                            return ToolResult(
                                success=False,
                                output="",
                                error=f"Fetch failed with HTTP status {resp.status_code}",
                                exit_code=1,
                                duration_seconds=duration,
                            )

                        content_type = resp.headers.get("content-type", "").lower()
                        # Read up to WEB_FETCH_MAX_BYTES
                        chunks = []
                        total_bytes = 0
                        for chunk in resp.iter_bytes():
                            chunks.append(chunk)
                            total_bytes += len(chunk)
                            if total_bytes > WEB_FETCH_MAX_BYTES:
                                logger.warning(f"web_fetch payload exceeded {WEB_FETCH_MAX_BYTES} bytes. Truncating.")
                                break

                        raw_bytes = b"".join(chunks)
                        # Determine charset
                        encoding = resp.encoding or "utf-8"
                        try:
                            response_text = raw_bytes.decode(encoding, errors="replace")
                        except Exception:
                            response_text = raw_bytes.decode("utf-8", errors="replace")
                        break
        except SSRFSecurityViolation as s_err:
            return ToolResult(
                success=False,
                output="",
                error=f"SSRF violation on redirect target: {s_err}",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Web fetch timed out after {WEB_FETCH_TIMEOUT_SECONDS}s",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Fetch request error: {str(e)}",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )

        # ── 3. Content Extraction ─────────────────────────────────────────
        extracted_content = ""
        is_json = "application/json" in content_type or (response_text.strip().startswith("{") and response_text.strip().endswith("}"))

        if is_json:
            try:
                parsed = json.loads(response_text)
                extracted_content = json.dumps(parsed, indent=2)
            except Exception:
                extracted_content = response_text
        elif inp.extract_mode == "raw":
            extracted_content = response_text
        else:
            extracted_content = html_to_clean_markdown(response_text, base_url=current_url)

        # ── 4. Jina Reader Fallback for Empty / JS Pages ──────────────────
        if len(extracted_content.strip()) < 80 and not is_json:
            logger.info(f"web_fetch extracted very short content ({len(extracted_content)} chars). Trying Jina Reader fallback.")
            jina_content = self._fetch_via_jina(current_url)
            if jina_content and len(jina_content.strip()) > len(extracted_content.strip()):
                extracted_content = jina_content

        # Truncate to max chars
        final_content = extracted_content[: inp.max_chars].strip()
        duration = time.monotonic() - start_time

        logger.info(
            "web_fetch completed | url={!r} | chars={} | duration={:.2f}s",
            current_url, len(final_content), duration
        )

        return ToolResult(
            success=True,
            output=final_content,
            exit_code=0,
            duration_seconds=duration,
            metadata={
                "url": current_url,
                "content_length": len(final_content),
                "is_truncated": len(extracted_content) > inp.max_chars,
            },
        )

    def _fetch_via_jina(self, target_url: str) -> Optional[str]:
        """Fetch reader-mode markdown via Jina Reader."""
        jina_url = f"https://r.jina.ai/{target_url}"
        try:
            safe_jina = validate_safe_url(jina_url)
            headers = {"User-Agent": BROWSER_USER_AGENT, "Accept": "text/markdown,text/plain"}
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(safe_jina, headers=headers)
                if resp.status_code == 200 and resp.text:
                    return resp.text
        except Exception as e:
            logger.debug(f"Jina reader fallback failed: {e}")
        return None
