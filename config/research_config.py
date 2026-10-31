# config/research_config.py
"""
Configuration and provider status for HERMES Universal Web Research & Visual Asset Engine.
Safely extracts API keys from environment without logging or exposing secrets.
"""

from __future__ import annotations

import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()

# Research Tool Limits & Defaults
WEB_SEARCH_DEFAULT_NUM = int(os.getenv("WEB_SEARCH_DEFAULT_NUM", "5"))
WEB_SEARCH_MAX_NUM = int(os.getenv("WEB_SEARCH_MAX_NUM", "20"))
WEB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "15.0"))

WEB_FETCH_MAX_CHARS = int(os.getenv("WEB_FETCH_MAX_CHARS", "8000"))
WEB_FETCH_TIMEOUT_SECONDS = float(os.getenv("WEB_FETCH_TIMEOUT_SECONDS", "15.0"))
WEB_FETCH_MAX_BYTES = int(os.getenv("WEB_FETCH_MAX_BYTES", "2097152"))  # 2MB

WEB_CRAWL_MAX_PAGES = int(os.getenv("WEB_CRAWL_MAX_PAGES", "6"))
WEB_CRAWL_MAX_DEPTH = int(os.getenv("WEB_CRAWL_MAX_DEPTH", "2"))

IMAGE_SEARCH_DEFAULT_NUM = int(os.getenv("IMAGE_SEARCH_DEFAULT_NUM", "6"))
IMAGE_SEARCH_MAX_NUM = int(os.getenv("IMAGE_SEARCH_MAX_NUM", "20"))
IMAGE_SEARCH_TIMEOUT_SECONDS = float(os.getenv("IMAGE_SEARCH_TIMEOUT_SECONDS", "15.0"))

IMAGE_DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("IMAGE_DOWNLOAD_TIMEOUT_SECONDS", "25.0"))
IMAGE_DOWNLOAD_MAX_BYTES = int(os.getenv("IMAGE_DOWNLOAD_MAX_BYTES", "10485760"))  # 10MB


def is_serper_available() -> bool:
    """Return True if a non-empty Serper API key is configured."""
    return bool(SERPER_API_KEY and len(SERPER_API_KEY) > 10)


def is_tavily_available() -> bool:
    """Return True if a non-empty Tavily API key is configured."""
    return bool(TAVILY_API_KEY and len(TAVILY_API_KEY) > 10)


def is_pixabay_available() -> bool:
    """Return True if a non-empty Pixabay API key is configured."""
    return bool(PIXABAY_API_KEY and len(PIXABAY_API_KEY) > 10)


def get_research_status() -> Dict[str, Any]:
    """Safe status report of configured research providers with zero secret exposure."""
    return {
        "serper": {
            "configured": is_serper_available(),
            "role": "primary_web_search",
        },
        "tavily": {
            "configured": is_tavily_available(),
            "role": "secondary_web_search_and_extract",
        },
        "pixabay": {
            "configured": is_pixabay_available(),
            "role": "primary_image_search",
        },
        "openverse_fallback": {
            "configured": True,
            "role": "fallback_image_search",
        },
        "duckduckgo_fallback": {
            "configured": True,
            "role": "fallback_web_search",
        },
    }
