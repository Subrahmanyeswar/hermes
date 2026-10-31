# tools/web_crawl_tools.py
"""
Bounded Web Crawler Tool for HERMES.
Performs scoped, BFS crawling within a domain with SSRF protection,
crawl-trap avoidance, and per-page markdown extraction.
"""

from __future__ import annotations

import collections
import re
import time
from urllib.parse import urlsplit, urljoin, urldefrag
from typing import List, Set, Dict, Any

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from loguru import logger

from tools.base import BaseTool, ToolResult
from tools.registry import tool
from tools.web_fetch_tools import html_to_clean_markdown, BROWSER_USER_AGENT
from core.security.web_security import validate_safe_url, is_safe_url, SSRFSecurityViolation
from config.research_config import (
    WEB_CRAWL_MAX_PAGES,
    WEB_CRAWL_MAX_DEPTH,
    WEB_FETCH_TIMEOUT_SECONDS,
)
import httpx

# Extensions to skip during web crawl
SKIPPED_EXTENSIONS = {
    ".pdf", ".zip", ".tar", ".gz", ".exe", ".bin", ".dmg", ".pkg",
    ".iso", ".mp4", ".mp3", ".wav", ".avi", ".mov", ".mkv",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".css", ".js", ".json", ".xml", ".csv", ".tsv",
}


@tool(
    name="web_crawl",
    description="Perform a bounded, same-domain crawl (up to 6 pages, depth 2) to collect connected documentation or articles.",
    permissions=["network_read"],
    risk_score=0.25,
    blocked_in=[],
)
class WebCrawlTool(BaseTool):
    """Bounded crawler for gathering connected documentation and pages."""

    class Input(BaseModel):
        start_url: str = Field(
            ...,
            description="The entrypoint HTTP/HTTPS URL for the crawl",
            min_length=8,
            max_length=2048,
        )
        max_pages: int = Field(
            default=4,
            ge=1,
            le=WEB_CRAWL_MAX_PAGES,
            description=f"Maximum pages to crawl (hard ceiling: {WEB_CRAWL_MAX_PAGES})",
        )
        max_depth: int = Field(
            default=2,
            ge=1,
            le=WEB_CRAWL_MAX_DEPTH,
            description="Maximum link traversal depth",
        )
        same_domain_only: bool = Field(
            default=True,
            description="Whether to restrict crawl to the same hostname",
        )
        chars_per_page: int = Field(
            default=3000,
            ge=500,
            le=10000,
            description="Maximum characters to extract per crawled page",
        )

    def execute(self, inp: Any) -> ToolResult:
        if isinstance(inp, dict):
            inp = self.Input(**inp)
        start_time = time.monotonic()
        start_url = inp.start_url.strip()

        # Initial SSRF check
        try:
            canonical_start = validate_safe_url(start_url)
        except SSRFSecurityViolation as e:
            return ToolResult(
                success=False,
                output="",
                error=f"SSRF violation on start_url: {e}",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )

        start_parts = urlsplit(canonical_start)
        base_domain = start_parts.netloc.lower()

        # BFS state
        queue: collections.deque[tuple[str, int]] = collections.deque([(canonical_start, 0)])
        visited: Set[str] = set()
        crawled_pages: List[Dict[str, Any]] = []

        headers = {
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        with httpx.Client(timeout=WEB_FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
            while queue and len(crawled_pages) < inp.max_pages:
                current_url, depth = queue.popleft()
                clean_url, _ = urldefrag(current_url)

                if clean_url in visited:
                    continue
                visited.add(clean_url)

                # Validate URL before requesting
                try:
                    safe_url = validate_safe_url(clean_url)
                except SSRFSecurityViolation:
                    continue

                try:
                    resp = client.get(safe_url, headers=headers)
                    if not (200 <= resp.status_code < 300):
                        continue

                    ct = resp.headers.get("content-type", "").lower()
                    if "text/html" not in ct and "application/xhtml" not in ct:
                        continue

                    html_text = resp.text
                    extracted_text = html_to_clean_markdown(html_text, base_url=safe_url)
                    page_snippet = extracted_text[: inp.chars_per_page].strip()

                    # Extract title
                    soup = BeautifulSoup(html_text, "html.parser")
                    page_title = soup.title.get_text(strip=True) if soup.title else safe_url

                    crawled_pages.append({
                        "url": safe_url,
                        "title": page_title,
                        "depth": depth,
                        "chars": len(page_snippet),
                        "content": page_snippet,
                    })

                    # If not at max depth, discover links
                    if depth < inp.max_depth:
                        for a in soup.find_all("a", href=True):
                            href = a["href"].strip()
                            if not href or href.startswith("javascript:") or href.startswith("mailto:"):
                                continue

                            # Check extension
                            path_lower = urlsplit(href).path.lower()
                            if any(path_lower.endswith(ext) for ext in SKIPPED_EXTENSIONS):
                                continue

                            full_link = urljoin(safe_url, href)
                            link_clean, _ = urldefrag(full_link)
                            link_parts = urlsplit(link_clean)

                            # Domain check
                            if inp.same_domain_only and link_parts.netloc.lower() != base_domain:
                                continue

                            if link_clean not in visited and is_safe_url(link_clean):
                                queue.append((link_clean, depth + 1))

                    # Rate-limiting pause
                    time.sleep(0.15)

                except Exception as e:
                    logger.debug(f"web_crawl failed fetching {clean_url}: {e}")
                    continue

        duration = time.monotonic() - start_time
        if not crawled_pages:
            return ToolResult(
                success=True,
                output=f"Crawl completed with 0 pages extracted from '{start_url}'.",
                exit_code=0,
                duration_seconds=duration,
                metadata={"pages_count": 0, "pages": []},
            )

        # Assemble summary
        formatted = [f"Web Crawl Summary for '{start_url}' ({len(crawled_pages)} pages crawled):"]
        for i, page in enumerate(crawled_pages, 1):
            formatted.append(
                f"\n--- Page [{i}]: {page['title']} (Depth {page['depth']}) ---\n"
                f"URL: {page['url']}\n\n"
                f"{page['content']}\n"
            )

        return ToolResult(
            success=True,
            output="\n".join(formatted),
            exit_code=0,
            duration_seconds=duration,
            metadata={"pages_count": len(crawled_pages), "pages": crawled_pages},
        )
