# tools/web_search_tools.py
"""
Universal Web Search Tool for HERMES.
Integrates Serper (primary), Tavily (secondary/fallback), and DuckDuckGo (zero-config fallback).
Provides URL normalization, cross-provider ranking, deduplication, and structured metadata.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import httpx
from pydantic import BaseModel, Field
from loguru import logger

from tools.base import BaseTool, ToolResult
from tools.registry import tool
from config.research_config import (
    SERPER_API_KEY,
    TAVILY_API_KEY,
    WEB_SEARCH_DEFAULT_NUM,
    WEB_SEARCH_MAX_NUM,
    WEB_SEARCH_TIMEOUT_SECONDS,
    is_serper_available,
    is_tavily_available,
)

# Tracking parameters to strip during URL normalization
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
    "yclid", "zanpid", "igshid",
}


def normalize_url(raw_url: str) -> str:
    """Normalize URL by lowercasing host, removing tracking query params, and dropping fragments."""
    try:
        parts = urlsplit(raw_url.strip())
        netloc = parts.netloc.lower()
        # Filter tracking parameters
        clean_query = []
        if parts.query:
            for k, v in parse_qsl(parts.query):
                if k.lower() not in TRACKING_PARAMS:
                    clean_query.append((k, v))
        new_query = urlencode(clean_query)
        path = parts.path
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return urlunsplit((parts.scheme.lower(), netloc, path, new_query, ""))
    except Exception:
        return raw_url.strip()


class SearchResultItem(BaseModel):
    """Normalized search result item across providers."""
    title: str
    url: str
    snippet: str
    source_provider: str
    rank: int = 1
    date: Optional[str] = None


@tool(
    name="web_search",
    description="Search the live web using Google Serper (primary) or Tavily with deduplication and metadata.",
    permissions=["network_read"],
    risk_score=0.1,
    blocked_in=[],
)
class WebSearchTool(BaseTool):
    """High-accuracy web search tool integrating Serper and Tavily with DuckDuckGo fallback."""

    class Input(BaseModel):
        query: str = Field(
            ...,
            description="The search query text",
            min_length=1,
            max_length=500,
        )
        num_results: int = Field(
            default=WEB_SEARCH_DEFAULT_NUM,
            ge=1,
            le=WEB_SEARCH_MAX_NUM,
            description="Maximum number of ranked results to return",
        )
        search_type: str = Field(
            default="search",
            description="Search type: 'search' or 'news'",
        )

    def execute(self, inp: Any) -> ToolResult:
        if isinstance(inp, dict):
            inp = self.Input(**inp)
        start_time = time.monotonic()
        query = inp.query.strip()
        num_results = inp.num_results
        results: List[SearchResultItem] = []
        provider_used = "none"
        errors: List[str] = []

        # ── 1. Try Serper (Google Search) ───────────────────────────────────
        if is_serper_available():
            try:
                serper_results = self._search_serper(query, num_results, inp.search_type)
                if serper_results:
                    results = serper_results
                    provider_used = "serper"
            except Exception as e:
                err_msg = f"Serper search failed: {e}"
                logger.warning(err_msg)
                errors.append(err_msg)

        # ── 2. Fallback to Tavily if Serper failed or empty ───────────────────
        if not results and is_tavily_available():
            try:
                tavily_results = self._search_tavily(query, num_results)
                if tavily_results:
                    results = tavily_results
                    provider_used = "tavily"
            except Exception as e:
                err_msg = f"Tavily search failed: {e}"
                logger.warning(err_msg)
                errors.append(err_msg)

        # ── 3. Fallback to DuckDuckGo if both failed or unconfigured ─────────
        if not results:
            try:
                ddg_results = self._search_duckduckgo(query, num_results)
                if ddg_results:
                    results = ddg_results
                    provider_used = "duckduckgo"
            except Exception as e:
                err_msg = f"DuckDuckGo search failed: {e}"
                logger.warning(err_msg)
                errors.append(err_msg)

        duration = time.monotonic() - start_time

        # Deduplicate results by normalized URL
        seen_urls: set[str] = set()
        deduped: List[SearchResultItem] = []
        for r in results:
            norm = normalize_url(r.url)
            if norm not in seen_urls:
                seen_urls.add(norm)
                deduped.append(r)
            if len(deduped) >= num_results:
                break

        if not deduped:
            error_detail = "; ".join(errors) if errors else "No results found"
            return ToolResult(
                success=True,
                output=f"No results found for query: '{query}'. ({error_detail})",
                exit_code=0,
                duration_seconds=duration,
                metadata={"query": query, "results": [], "provider": provider_used},
            )

        # Format human-readable output
        formatted_blocks = []
        for i, item in enumerate(deduped, 1):
            date_str = f" [{item.date}]" if item.date else ""
            formatted_blocks.append(
                f"[{i}] {item.title}{date_str}\n"
                f"    URL: {item.url}\n"
                f"    Snippet: {item.snippet}"
            )

        output_text = (
            f"Web search results for: '{query}' (via {provider_used}, {len(deduped)} results):\n\n"
            + "\n\n".join(formatted_blocks)
        )

        raw_records = [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "provider": r.source_provider,
                "date": r.date,
            }
            for r in deduped
        ]

        logger.info(
            "web_search completed | query={!r} | provider={} | count={}",
            query, provider_used, len(deduped)
        )

        return ToolResult(
            success=True,
            output=output_text,
            exit_code=0,
            duration_seconds=duration,
            metadata={"query": query, "results": raw_records, "provider": provider_used},
        )

    def _search_serper(self, query: str, num_results: int, search_type: str) -> List[SearchResultItem]:
        """Search via Google Serper API."""
        endpoint = "https://google.serper.dev/news" if search_type == "news" else "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "q": query,
            "num": min(num_results, 20),
        }
        with httpx.Client(timeout=WEB_SEARCH_TIMEOUT_SECONDS) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        items: List[SearchResultItem] = []
        # Check organic results
        organic = data.get("organic", []) or data.get("news", [])
        for rank, entry in enumerate(organic, 1):
            title = str(entry.get("title", "")).strip()
            link = str(entry.get("link", "")).strip()
            snippet = str(entry.get("snippet", "")).strip()
            date = entry.get("date")
            if link and (title or snippet):
                items.append(SearchResultItem(
                    title=title or "Untitled",
                    url=link,
                    snippet=snippet or "No snippet available",
                    source_provider="serper",
                    rank=rank,
                    date=str(date) if date else None,
                ))

        # Check answerBox if present
        answer_box = data.get("answerBox")
        if answer_box and isinstance(answer_box, dict):
            box_title = answer_box.get("title", "Quick Answer")
            box_answer = answer_box.get("answer") or answer_box.get("snippet", "")
            box_link = answer_box.get("link", "")
            if box_answer and box_link:
                items.insert(0, SearchResultItem(
                    title=box_title,
                    url=box_link,
                    snippet=str(box_answer),
                    source_provider="serper_answer_box",
                    rank=0,
                ))

        return items

    def _search_tavily(self, query: str, num_results: int) -> List[SearchResultItem]:
        """Search via Tavily API."""
        endpoint = "https://api.tavily.com/search"
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": min(num_results, 20),
            "search_depth": "basic",
            "include_answer": False,
        }
        with httpx.Client(timeout=WEB_SEARCH_TIMEOUT_SECONDS) as client:
            resp = client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

        items: List[SearchResultItem] = []
        for rank, entry in enumerate(data.get("results", []), 1):
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("url", "")).strip()
            content = str(entry.get("content", "")).strip()
            if url:
                items.append(SearchResultItem(
                    title=title or "Untitled",
                    url=url,
                    snippet=content or "No snippet available",
                    source_provider="tavily",
                    rank=rank,
                ))
        return items

    def _search_duckduckgo(self, query: str, num_results: int) -> List[SearchResultItem]:
        """Search via DuckDuckGo API (fallback)."""
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }
        with httpx.Client(timeout=WEB_SEARCH_TIMEOUT_SECONDS) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        items: List[SearchResultItem] = []
        abstract_text = str(data.get("AbstractText", "")).strip()
        abstract_url = str(data.get("AbstractURL", "")).strip()
        if abstract_text and abstract_url:
            items.append(SearchResultItem(
                title=str(data.get("Heading", "Instant Answer")),
                url=abstract_url,
                snippet=abstract_text,
                source_provider="duckduckgo",
                rank=1,
            ))

        for rank, topic in enumerate(data.get("RelatedTopics", []), len(items) + 1):
            if isinstance(topic, dict):
                text = str(topic.get("Text", "")).strip()
                first_url = str(topic.get("FirstURL", "")).strip()
                if text and first_url:
                    items.append(SearchResultItem(
                        title=text.split(" - ")[0] if " - " in text else text[:60],
                        url=first_url,
                        snippet=text,
                        source_provider="duckduckgo",
                        rank=rank,
                    ))
            if len(items) >= num_results:
                break

        return items
