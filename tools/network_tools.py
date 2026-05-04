# tools/network_tools.py
# Network tools for HERMES.
# WebSearchTool: searches using DuckDuckGo's free instant answer API (no API key needed).
# WebFetchTool: fetches the text content of a URL using httpx.
# Both tools are read-only. Neither writes to disk.
# Allowed in all permission modes including safe mode.

import httpx
import time
import json
import re
from pydantic import BaseModel, Field, HttpUrl
from tools.base import BaseTool, ToolResult
from tools.registry import tool
from loguru import logger


@tool(
    name="web_search",
    description="Search the web using DuckDuckGo and return a list of results with titles, URLs, and snippets.",
    permissions=["network_read"],
    risk_score=0.1,
    blocked_in=[],
)
class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo's instant answer API."""

    class Input(BaseModel):
        """Validated input for WebSearchTool."""

        query: str = Field(
            ...,
            description="The search query",
            min_length=1,
            max_length=500,
        )
        max_results: int = Field(
            default=5,
            ge=1,
            le=10,
            description="Maximum number of results to return",
        )

    def execute(self, inp: Input) -> ToolResult:
        """Run a DuckDuckGo web search and return formatted results."""
        start_time = time.monotonic()
        url = "https://api.duckduckgo.com/"
        params = {
            "q": inp.query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }

        try:
            response = httpx.get(
                url,
                params=params,
                timeout=15.0,
                follow_redirects=True,
            )
            response.raise_for_status()
            data = response.json()

            results: list[tuple[str, str]] = []
            abstract_text = str(data.get("AbstractText", "")).strip()
            abstract_url = str(data.get("AbstractURL", "")).strip()
            if abstract_text:
                results.append((abstract_text, abstract_url))

            for item in data.get("RelatedTopics", []):
                if len(results) >= inp.max_results:
                    break
                if not isinstance(item, dict):
                    continue
                if "Topics" in item and isinstance(item["Topics"], list):
                    for nested_item in item["Topics"]:
                        if len(results) >= inp.max_results:
                            break
                        if isinstance(nested_item, dict) and nested_item.get("Text"):
                            results.append(
                                (
                                    str(nested_item.get("Text", "")).strip(),
                                    str(nested_item.get("FirstURL", "")).strip(),
                                )
                            )
                    continue
                if item.get("Text"):
                    results.append(
                        (
                            str(item.get("Text", "")).strip(),
                            str(item.get("FirstURL", "")).strip(),
                        )
                    )

            results = results[: inp.max_results]
            duration = time.monotonic() - start_time
            logger.info(
                "web_search | query={!r} | results={}",
                inp.query,
                len(results),
            )
            logger.debug("web_search | duration={:.2f}s", duration)

            if not results:
                return ToolResult(
                    success=True,
                    output=f"No results found for: {inp.query}",
                    exit_code=0,
                    duration_seconds=duration,
                )

            formatted_results = []
            for index, (text, result_url) in enumerate(results, start=1):
                formatted_results.append(f"[{index}] {text}\n    URL: {result_url}")

            return ToolResult(
                success=True,
                output="\n\n".join(formatted_results),
                exit_code=0,
                duration_seconds=duration,
            )
        except httpx.TimeoutException:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error="Web search timed out after 15 seconds",
                exit_code=1,
                duration_seconds=duration,
            )
        except httpx.ConnectError:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error="Cannot connect to DuckDuckGo. Check internet connection.",
                exit_code=1,
                duration_seconds=duration,
            )
        except json.JSONDecodeError:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error="Unexpected response format from search API",
                exit_code=1,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Search failed: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )


@tool(
    name="web_fetch",
    description="Fetch the text content of a URL. Returns the page's visible text content, not raw HTML.",
    permissions=["network_read"],
    risk_score=0.2,
    blocked_in=[],
)
class WebFetchTool(BaseTool):
    """Fetch visible text content from an HTTP or HTTPS URL."""

    class Input(BaseModel):
        """Validated input for WebFetchTool."""

        url: str = Field(
            ...,
            description="The URL to fetch",
            min_length=10,
            max_length=2000,
        )
        max_chars: int = Field(
            default=5000,
            ge=100,
            le=20000,
            description="Maximum characters of content to return",
        )

    def execute(self, inp: Input) -> ToolResult:
        """Fetch a URL and return visible text or formatted JSON content."""
        start_time = time.monotonic()
        if not (inp.url.startswith("http://") or inp.url.startswith("https://")):
            return ToolResult(
                success=False,
                output="",
                error="URL must start with http:// or https://",
                exit_code=1,
            )

        headers = {
            "User-Agent": "HERMES-Agent/1.0 (research project; not a crawler)",
            "Accept": "text/html,text/plain,application/json",
        }

        try:
            response = httpx.get(
                inp.url,
                headers=headers,
                timeout=20.0,
                follow_redirects=True,
            )
            duration = time.monotonic() - start_time
            if not 200 <= response.status_code < 300:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Fetch failed with HTTP status {response.status_code}",
                    exit_code=1,
                    duration_seconds=duration,
                )

            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                content = json.dumps(response.json(), indent=2)
            else:
                content = re.sub(r"<[^>]+>", " ", response.text)
                content = re.sub(r"\s+", " ", content).strip()

            logger.info("web_fetch | url={!r} | chars={}", inp.url, len(content))
            logger.debug("web_fetch | duration={:.2f}s", duration)
            return ToolResult(
                success=True,
                output=content[: inp.max_chars],
                exit_code=0,
                duration_seconds=duration,
            )
        except httpx.TimeoutException:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error="Web fetch timed out after 20 seconds",
                exit_code=1,
                duration_seconds=duration,
            )
        except httpx.ConnectError:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error="Cannot connect to URL. Check internet connection.",
                exit_code=1,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Fetch failed: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )
