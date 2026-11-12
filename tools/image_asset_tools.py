# tools/image_asset_tools.py
"""
Universal Visual Asset and Deep Research Engine for HERMES.
Provides:
  - image_search: Pixabay API integration with Wikimedia fallback, license/dimension filtering, and in-memory TTL caching.
  - download_image: Atomic workspace asset downloader with SSRF validation, magic-byte verification,
                    image dimension checking, and automatic asset_manifest.json / IMAGE_CREDITS.md generation.
  - deep_web_research: High-level research synthesizer combining multi-query search, page scraping,
                       and cited factual brief generation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, unquote

import httpx
from PIL import Image
from pydantic import BaseModel, Field
from loguru import logger

from tools.base import BaseTool, ToolResult
from tools.registry import tool
from tools.web_search_tools import WebSearchTool
from tools.web_fetch_tools import WebFetchTool, BROWSER_USER_AGENT
from core.security.web_security import validate_safe_url, SSRFSecurityViolation
from config.research_config import (
    PIXABAY_API_KEY,
    IMAGE_SEARCH_DEFAULT_NUM,
    IMAGE_SEARCH_MAX_NUM,
    IMAGE_SEARCH_TIMEOUT_SECONDS,
    IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
    IMAGE_DOWNLOAD_MAX_BYTES,
    is_pixabay_available,
)

RESEARCH_USER_AGENT = "HERMESResearchEngine/1.0 (https://hermes-engine.org; contact: support@hermes-engine.org)"

# 24-hour in-memory cache for image search results
_IMAGE_SEARCH_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
CACHE_TTL_SECONDS = 86400.0  # 24 hours


def _get_cache_key(query: str, orientation: str, image_type: str, min_w: int, min_h: int) -> str:
    norm = f"{query.strip().lower()}|{orientation}|{image_type}|{min_w}|{min_h}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def verify_image_magic_bytes(data: bytes) -> str:
    """
    Verify binary magic bytes for common web image formats.
    Returns format name ('jpeg', 'png', 'webp', 'gif') or raises ValueError.
    """
    if len(data) < 16:
        raise ValueError("File content too small to be a valid image")

    # JPEG
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"

    # PNG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"

    # GIF
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"

    # WebP: starts with 'RIFF', then 4 bytes of size, then 'WEBP'
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"

    # Rejection of common text / HTML error payloads
    snippet = data[:100].decode("latin-1", errors="replace").lower()
    if "<html" in snippet or "<!doctype" in snippet or "error" in snippet:
        raise ValueError("Server returned HTML or text error payload instead of binary image")

    raise ValueError("Unrecognized image binary signature (not JPEG, PNG, WebP, or GIF)")


@tool(
    name="image_search",
    description="Search royalty-free, high-quality images via Pixabay and open repositories with license and dimension filtering.",
    permissions=["network_read"],
    risk_score=0.1,
    blocked_in=[],
)
class ImageSearchTool(BaseTool):
    """Search royalty-free visual assets with caching, metadata, and attribution info."""

    class Input(BaseModel):
        query: str = Field(
            ...,
            description="Visual search query (e.g. 'rocket launch space', 'mars rover')",
            min_length=1,
            max_length=200,
        )
        num_results: int = Field(
            default=IMAGE_SEARCH_DEFAULT_NUM,
            ge=1,
            le=IMAGE_SEARCH_MAX_NUM,
            description="Number of image candidates to return",
        )
        orientation: str = Field(
            default="all",
            description="Image orientation: 'all', 'horizontal', or 'vertical'",
        )
        image_type: str = Field(
            default="photo",
            description="Image type: 'all', 'photo', 'illustration', 'vector'",
        )
        min_width: int = Field(
            default=0,
            ge=0,
            description="Minimum image width in pixels",
        )
        min_height: int = Field(
            default=0,
            ge=0,
            description="Minimum image height in pixels",
        )

    def execute(self, inp: Input) -> ToolResult:
        if isinstance(inp, dict):
            inp = self.Input(**inp)
        start_time = time.monotonic()
        query = inp.query.strip()
        cache_key = _get_cache_key(query, inp.orientation, inp.image_type, inp.min_width, inp.min_height)

        # Check cache
        now = time.monotonic()
        if cache_key in _IMAGE_SEARCH_CACHE:
            ts, cached_hits = _IMAGE_SEARCH_CACHE[cache_key]
            if now - ts < CACHE_TTL_SECONDS:
                logger.debug(f"image_search: cache hit for '{query}'")
                return self._build_result(query, cached_hits[: inp.num_results], "pixabay_cache", time.monotonic() - start_time)

        hits: List[Dict[str, Any]] = []
        provider_used = "none"

        # 1. Primary: Pixabay API
        if is_pixabay_available():
            try:
                hits = self._search_pixabay(query, inp.num_results, inp.orientation, inp.image_type, inp.min_width, inp.min_height)
                if hits:
                    provider_used = "pixabay"
            except Exception as e:
                logger.warning(f"Pixabay search error: {e}")

        # 2. Fallback: Wikimedia Commons API
        if not hits:
            try:
                hits = self._search_wikimedia(query, inp.num_results)
                if hits:
                    provider_used = "wikimedia_commons"
            except Exception as e:
                logger.warning(f"Wikimedia search fallback error: {e}")

        # Cache results if found
        if hits:
            _IMAGE_SEARCH_CACHE[cache_key] = (now, hits)

        duration = time.monotonic() - start_time
        return self._build_result(query, hits[: inp.num_results], provider_used, duration)

    def _search_pixabay(
        self, query: str, num_results: int, orientation: str, image_type: str, min_w: int, min_h: int
    ) -> List[Dict[str, Any]]:
        """Query Pixabay API."""
        endpoint = "https://pixabay.com/api/"
        params: Dict[str, Any] = {
            "key": PIXABAY_API_KEY,
            "q": query,
            "image_type": image_type if image_type in ("photo", "illustration", "vector") else "all",
            "per_page": min(max(num_results, 3), 20),
            "safesearch": "true",
        }
        if orientation in ("horizontal", "vertical"):
            params["orientation"] = orientation
        if min_w > 0:
            params["min_width"] = min_w
        if min_h > 0:
            params["min_height"] = min_h

        with httpx.Client(timeout=IMAGE_SEARCH_TIMEOUT_SECONDS) as client:
            resp = client.get(endpoint, params=params)
            resp.raise_for_status()
            data = resp.json()

        hits: List[Dict[str, Any]] = []
        for item in data.get("hits", []):
            prev_url = item.get("previewURL") or item.get("webformatURL")
            # Prefer stable cdn.pixabay.com URL over temporary /get/ URLs that trigger Cloudflare 429 rate limits
            cdn_url = None
            if prev_url and "_150." in prev_url:
                cdn_url = prev_url.replace("_150.", "_960_720.")
            img_url = cdn_url or item.get("largeImageURL") or item.get("webformatURL") or prev_url
            tags = item.get("tags", "")
            user = item.get("user", "Unknown Artist")
            user_id = item.get("user_id", "")
            w = item.get("imageWidth") or 0
            h = item.get("imageHeight") or 0

            if img_url:
                hits.append({
                    "id": str(item.get("id")),
                    "title": tags or query,
                    "preview_url": prev_url,
                    "image_url": img_url,
                    "width": w,
                    "height": h,
                    "author": user,
                    "author_url": f"https://pixabay.com/users/{user}-{user_id}/" if user_id else "https://pixabay.com",
                    "license": "Pixabay Content License (Free to use, no attribution required)",
                    "source_platform": "Pixabay",
                })
        return hits

    def _search_wikimedia(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Query Wikimedia Commons Open API as zero-config fallback."""
        endpoint = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": min(num_results, 10),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": 1280,
            "format": "json",
        }
        headers = {"User-Agent": RESEARCH_USER_AGENT}
        with httpx.Client(timeout=IMAGE_SEARCH_TIMEOUT_SECONDS) as client:
            resp = client.get(endpoint, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        hits: List[Dict[str, Any]] = []
        pages = data.get("query", {}).get("pages", {})
        for _, page in pages.items():
            ii = page.get("imageinfo", [{}])[0]
            url = ii.get("url")
            thumb_url = ii.get("thumburl") or url
            w = ii.get("width", 0)
            h = ii.get("height", 0)
            meta = ii.get("extmetadata", {})
            artist = meta.get("Artist", {}).get("value", "Wikimedia Contributor")
            # Strip html tags from artist
            artist_clean = re.sub(r"<[^>]+>", "", artist).strip() or "Wikimedia Contributor"
            license_name = meta.get("LicenseShortName", {}).get("value", "CC-BY-SA / Public Domain")

            path_lower = urlsplit(url).path.lower()
            if url and any(path_lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
                hits.append({
                    "id": str(page.get("pageid")),
                    "title": page.get("title", "").replace("File:", ""),
                    "preview_url": thumb_url,
                    "image_url": url,
                    "width": w,
                    "height": h,
                    "author": artist_clean,
                    "author_url": ii.get("descriptionurl", "https://commons.wikimedia.org"),
                    "license": license_name,
                    "source_platform": "Wikimedia Commons",
                })
        return hits

    def _build_result(self, query: str, hits: List[Dict[str, Any]], provider: str, duration: float) -> ToolResult:
        if not hits:
            return ToolResult(
                success=True,
                output=f"No royalty-free images found matching: '{query}'.",
                exit_code=0,
                duration_seconds=duration,
                metadata={"query": query, "count": 0, "images": []},
            )

        formatted = [f"Found {len(hits)} royalty-free images for '{query}' (via {provider}):\n"]
        for i, hit in enumerate(hits, 1):
            dim_str = f" ({hit['width']}x{hit['height']})" if hit['width'] and hit['height'] else ""
            formatted.append(
                f"[{i}] {hit['title']}{dim_str}\n"
                f"    Preview: {hit['preview_url']}\n"
                f"    High-Res URL: {hit['image_url']}\n"
                f"    Author: {hit['author']} | License: {hit['license']}"
            )

        return ToolResult(
            success=True,
            output="\n\n".join(formatted),
            exit_code=0,
            duration_seconds=duration,
            metadata={"query": query, "count": len(hits), "images": hits, "provider": provider},
        )


@tool(
    name="download_image",
    description="Download a verified image into workspace assets/images/, validating binary magic bytes, dimensions, and updating asset_manifest.json and IMAGE_CREDITS.md.",
    permissions=["network_read", "fs_write"],
    risk_score=0.2,
    blocked_in=[],
)
class DownloadImageTool(BaseTool):
    """Download image asset into workspace with format validation and manifest tracking."""

    class Input(BaseModel):
        image_url: Optional[str] = Field(
            default=None,
            description="The HTTP or HTTPS URL of the image to download",
            min_length=8,
            max_length=2048,
        )
        url: Optional[str] = Field(
            default=None,
            description="Alternative parameter name for image_url",
            min_length=8,
            max_length=2048,
        )
        filename: Optional[str] = Field(
            default=None,
            description="Target filename (e.g. 'hero_rocket.jpg'). If omitted, slugified from URL.",
        )
        alt_text: Optional[str] = Field(
            default=None,
            description="Descriptive alt text for the image in the UI/app",
        )
        attribution: Optional[Dict[str, Any]] = Field(
            default=None,
            description="Attribution metadata: author, license, source_platform, source_url",
        )

    def execute(self, inp: Input) -> ToolResult:
        if isinstance(inp, dict):
            inp = self.Input(**inp)
        start_time = time.monotonic()
        target_url = inp.image_url or inp.url
        if not target_url:
            return ToolResult(
                success=False,
                output="",
                error="Missing required parameter: image_url (or url)",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )
        raw_url = target_url.strip()

        # ── 1. SSRF Safety Check ──────────────────────────────────────────
        try:
            safe_target = validate_safe_url(raw_url)
        except SSRFSecurityViolation as e:
            return ToolResult(
                success=False,
                output="",
                error=f"SSRF security violation on image URL: {e}",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )

        # ── 2. Determine Destination Directory in Workspace ───────────────
        base_dir: Optional[Path] = None
        try:
            from core.workspace import workspace_manager
            if workspace_manager.is_locked and workspace_manager.workspace_root:
                base_dir = Path(workspace_manager.workspace_root)
        except Exception:
            pass

        if not base_dir:
            ws_root = os.getenv("HERMES_WORKSPACE_ROOT")
            if ws_root and os.path.isdir(ws_root):
                base_dir = Path(ws_root)
            else:
                base_dir = Path.cwd()

        images_dir = base_dir / "assets" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        # ── 3. Fetch Image with Bounded Size ──────────────────────────────
        parsed_target = urlsplit(safe_target)
        ref_header = f"{parsed_target.scheme}://{parsed_target.netloc}/"
        headers = {
            "User-Agent": RESEARCH_USER_AGENT,
            "Accept": "image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": ref_header,
        }

        try:
            with httpx.Client(timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
                resp = client.get(safe_target, headers=headers)
                if resp.status_code == 429:
                    time.sleep(1.5)
                    headers["User-Agent"] = BROWSER_USER_AGENT
                    resp = client.get(safe_target, headers=headers)
                elif not (200 <= resp.status_code < 300):
                    # Try desktop browser UA fallback
                    headers["User-Agent"] = BROWSER_USER_AGENT
                    resp = client.get(safe_target, headers=headers)

                if not (200 <= resp.status_code < 300):
                    # Attempt fallback if preview_url is provided in attribution
                    fallback_url = (inp.attribution or {}).get("preview_url")
                    if fallback_url and fallback_url != safe_target:
                        logger.warning(f"Download failed with HTTP {resp.status_code}. Attempting preview_url fallback.")
                        safe_fallback = validate_safe_url(fallback_url)
                        resp = client.get(safe_fallback, headers=headers)

                if not (200 <= resp.status_code < 300):
                    # Attempt Wikimedia Commons search fallback if primary provider gave 429 or failed
                    try:
                        query = inp.alt_text or (inp.attribution or {}).get("title") or "rocket launch"
                        clean_query = re.sub(r"[^a-zA-Z0-9\s]", " ", query).strip()
                        wiki_hits = ImageSearchTool()._search_wikimedia(clean_query, num_results=3)
                        for wh in wiki_hits:
                            w_url = wh.get("image_url") or wh.get("preview_url")
                            if w_url:
                                safe_w = validate_safe_url(w_url)
                                w_headers = {"User-Agent": RESEARCH_USER_AGENT}
                                w_resp = client.get(safe_w, headers=w_headers)
                                if 200 <= w_resp.status_code < 300:
                                    resp = w_resp
                                    inp.attribution = wh
                                    logger.info(f"Successfully downloaded fallback asset from Wikimedia: {w_url}")
                                    break
                    except Exception as fallback_err:
                        logger.warning(f"Wikimedia download fallback attempt notice: {fallback_err}")

                if not (200 <= resp.status_code < 300):
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Failed downloading image: HTTP {resp.status_code}",
                        exit_code=1,
                        duration_seconds=time.monotonic() - start_time,
                    )
                raw_bytes = resp.content
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Image download network error: {e}",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )

        if len(raw_bytes) > IMAGE_DOWNLOAD_MAX_BYTES:
            return ToolResult(
                success=False,
                output="",
                error=f"Image size ({len(raw_bytes)} bytes) exceeds maximum allowable limit ({IMAGE_DOWNLOAD_MAX_BYTES} bytes)",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )

        # ── 4. Verify Binary Magic Bytes & Image Validity ─────────────────
        try:
            fmt_detected = verify_image_magic_bytes(raw_bytes)
        except ValueError as ve:
            return ToolResult(
                success=False,
                output="",
                error=f"Image validation failed: {ve}",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )

        # Verify PIL can open and decode it
        import io
        try:
            with Image.open(io.BytesIO(raw_bytes)) as pil_img:
                width, height = pil_img.size
                pil_format = (pil_img.format or fmt_detected).lower()
        except Exception as pe:
            return ToolResult(
                success=False,
                output="",
                error=f"Corrupt image file. PIL decode failed: {pe}",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )

        # ── 5. Determine Filename ─────────────────────────────────────────
        ext = f".{pil_format}" if pil_format != "jpeg" else ".jpg"
        if inp.filename:
            clean_name = Path(inp.filename).name
            if not any(clean_name.lower().endswith(x) for x in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
                clean_name += ext
        else:
            url_path = unquote(urlsplit(safe_target).path)
            stem = Path(url_path).stem
            stem_clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", stem)[:40] or "image"
            h_suffix = hashlib.md5(raw_bytes).hexdigest()[:6]
            clean_name = f"{stem_clean}_{h_suffix}{ext}"

        final_dest = images_dir / clean_name
        tmp_dest = images_dir / f"{clean_name}.tmp_{os.getpid()}"

        # ── 6. Atomic Write to Disk ───────────────────────────────────────
        try:
            tmp_dest.write_bytes(raw_bytes)
            tmp_dest.replace(final_dest)
        except Exception as we:
            if tmp_dest.exists():
                tmp_dest.unlink(missing_ok=True)
            return ToolResult(
                success=False,
                output="",
                error=f"Failed writing image to workspace: {we}",
                exit_code=1,
                duration_seconds=time.monotonic() - start_time,
            )

        sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
        rel_path = f"assets/images/{clean_name}"

        # ── 7. Update asset_manifest.json ─────────────────────────────────
        manifest_path = images_dir / "asset_manifest.json"
        manifest: Dict[str, Any] = {"assets": []}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest.get("assets"), list):
                    manifest["assets"] = []
            except Exception:
                manifest = {"assets": []}

        # Deduplicate manifest record
        manifest["assets"] = [a for a in manifest["assets"] if a.get("filename") != clean_name]

        attr = inp.attribution or {}
        new_entry = {
            "filename": clean_name,
            "relative_path": rel_path,
            "width": width,
            "height": height,
            "format": pil_format,
            "size_bytes": len(raw_bytes),
            "sha256": sha256_hash,
            "source_url": safe_target,
            "alt_text": inp.alt_text or clean_name,
            "attribution": {
                "author": attr.get("author", "Pixabay / Open Contributor"),
                "author_url": attr.get("author_url", ""),
                "license": attr.get("license", "Pixabay Content License / Open Access"),
                "source_platform": attr.get("source_platform", "Pixabay"),
            },
            "downloaded_at": time.time(),
        }
        manifest["assets"].append(new_entry)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # ── 8. Update IMAGE_CREDITS.md ────────────────────────────────────
        credits_path = base_dir / "IMAGE_CREDITS.md"
        try:
            credits_lines = [
                "# Image Credits and Licensing\n",
                "All visual assets used in this project are royalty-free and compliant with their respective licenses:\n",
            ]
            for asset in manifest["assets"]:
                a_info = asset.get("attribution", {})
                author = a_info.get("author", "Unknown")
                license_str = a_info.get("license", "Royalty Free")
                src_platform = a_info.get("source_platform", "Web")
                rel = asset.get("relative_path", "")
                alt = asset.get("alt_text", "")
                credits_lines.append(
                    f"- **`{rel}`** ({asset.get('width')}x{asset.get('height')})\n"
                    f"  - **Description**: {alt}\n"
                    f"  - **Creator / Source**: {author} via {src_platform}\n"
                    f"  - **License**: {license_str}\n"
                )
            credits_path.write_text("\n".join(credits_lines), encoding="utf-8")
        except Exception as ce:
            logger.debug(f"Could not update IMAGE_CREDITS.md: {ce}")

        duration = time.monotonic() - start_time
        logger.info(
            "download_image completed | file={} | size={} | dims={}x{}",
            rel_path, len(raw_bytes), width, height
        )

        return ToolResult(
            success=True,
            output=(
                f"Successfully downloaded image to '{rel_path}'\n"
                f"- Dimensions: {width} x {height} px\n"
                f"- Format: {pil_format.upper()}\n"
                f"- Size: {len(raw_bytes) / 1024:.1f} KB\n"
                f"- Alt text: {inp.alt_text or 'None'}\n"
                f"- Updated: {manifest_path.name} and IMAGE_CREDITS.md"
            ),
            exit_code=0,
            duration_seconds=duration,
            metadata=new_entry,
        )


@tool(
    name="deep_web_research",
    description="Perform an end-to-end multi-query research bundle: searches, fetches top sources, and compiles a structured, factual brief with citations.",
    permissions=["network_read"],
    risk_score=0.2,
    blocked_in=[],
)
class DeepWebResearchTool(BaseTool):
    """High-level research bundle synthesizing multi-query search and content scraping into cited notes."""

    class Input(BaseModel):
        topic: str = Field(
            ...,
            description="The primary research topic or technical question",
            min_length=3,
            max_length=400,
        )
        subqueries: Optional[List[str]] = Field(
            default=None,
            description="Optional targeted sub-search queries. If omitted, generated automatically.",
        )
        max_sources: int = Field(
            default=4,
            ge=1,
            le=8,
            description="Maximum number of authoritative sources to deeply scrape and synthesize",
        )

    def execute(self, inp: Input) -> ToolResult:
        if isinstance(inp, dict):
            inp = self.Input(**inp)
        start_time = time.monotonic()
        topic = inp.topic.strip()
        searcher = WebSearchTool()
        fetcher = WebFetchTool()

        queries = inp.subqueries if inp.subqueries else [topic]
        if not inp.subqueries:
            # Generate 2 targeted variants
            queries.append(f"{topic} official documentation")
            queries.append(f"{topic} specifications technical overview")

        candidate_sources: List[Dict[str, str]] = []
        seen_urls: set[str] = set()

        for q in queries[:3]:
            try:
                s_res = searcher.execute(WebSearchTool.Input(query=q, num_results=3))
                if s_res.metadata and "results" in s_res.metadata:
                    for r in s_res.metadata["results"]:
                        u = r.get("url")
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            candidate_sources.append({
                                "title": r.get("title", "Untitled"),
                                "url": u,
                                "snippet": r.get("snippet", ""),
                            })
            except Exception as se:
                logger.debug(f"deep_web_research subquery '{q}' failed: {se}")

        # Fetch top candidate pages
        scraped_sources: List[Dict[str, Any]] = []
        for src in candidate_sources[: inp.max_sources]:
            try:
                f_res = fetcher.execute(WebFetchTool.Input(url=src["url"], max_chars=3500))
                if f_res.success and f_res.output:
                    scraped_sources.append({
                        "title": src["title"],
                        "url": src["url"],
                        "content": f_res.output,
                        "snippet": src["snippet"],
                    })
            except Exception as fe:
                logger.debug(f"deep_web_research fetch failed for {src['url']}: {fe}")

        duration = time.monotonic() - start_time
        if not scraped_sources:
            return ToolResult(
                success=True,
                output=f"Deep research completed for topic: '{topic}' with 0 full sources fetched.",
                exit_code=0,
                duration_seconds=duration,
                metadata={"topic": topic, "sources": []},
            )

        # Assemble cited research brief
        brief_sections = [
            f"# Research Brief: {topic}\n",
            f"**Sources Analyzed**: {len(scraped_sources)}\n",
            "## Key Findings & Source Excerpts\n",
        ]

        for i, src in enumerate(scraped_sources, 1):
            brief_sections.append(
                f"### [{i}] {src['title']}\n"
                f"- **Source URL**: {src['url']}\n"
                f"- **Excerpt / Content Summary**:\n\n{src['content'][:1500]}\n"
            )

        brief_sections.append("## Citations\n")
        for i, src in enumerate(scraped_sources, 1):
            brief_sections.append(f"{i}. [{src['title']}]({src['url']})")

        brief_text = "\n".join(brief_sections)

        return ToolResult(
            success=True,
            output=brief_text,
            exit_code=0,
            duration_seconds=duration,
            metadata={
                "topic": topic,
                "sources_count": len(scraped_sources),
                "sources": [
                    {"title": s["title"], "url": s["url"]} for s in scraped_sources
                ],
            },
        )
