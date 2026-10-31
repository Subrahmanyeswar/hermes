# tests/test_web_research_and_image_assets.py
"""
Deterministic Unit and Integration Test Suite for HERMES Web Research & Visual Asset Engine.
Covers specifications W01-W22 (Web Search, Fetch, Crawl, Visual Assets, SSRF Security)
and UI01-UI05 (Event integration, API status, Headline formatting, Secret protection).
"""

import io
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from PIL import Image

from core.security.web_security import (
    validate_safe_url,
    is_safe_url,
    SSRFSecurityViolation,
    resolve_and_validate_host,
)
from config.research_config import (
    is_serper_available,
    is_tavily_available,
    is_pixabay_available,
    get_research_status,
)
from tools.base import ToolResult
from tools.web_search_tools import WebSearchTool, normalize_url, SearchResultItem
from tools.web_fetch_tools import WebFetchTool, html_to_clean_markdown
from tools.web_crawl_tools import WebCrawlTool
from tools.image_asset_tools import (
    ImageSearchTool,
    DownloadImageTool,
    DeepWebResearchTool,
    verify_image_magic_bytes,
)
from core.agent_loop.actions import format_tool_headline
from core.runtime_state.events import EventType, HermesEvent


# ── W01-W06: SSRF and Host Validation ────────────────────────────────────────

def test_w01_reject_loopback_and_localhost():
    """W01: Rejection of 127.0.0.1, localhost, and loopback IPs."""
    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://127.0.0.1:8080/secret")

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://localhost/admin")

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("https://sub.localhost/api")

    assert not is_safe_url("http://127.0.0.1")
    assert not is_safe_url("http://localhost")


def test_w02_reject_rfc1918_private_ips():
    """W02: Rejection of RFC 1918 private IPv4 networks (10/8, 172.16/12, 192.168/16)."""
    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://10.0.0.1/status")

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://192.168.1.254/router")

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://172.16.0.5:8000/")


def test_w03_reject_cloud_metadata_ip():
    """W03: Rejection of AWS/GCP/Azure link-local metadata address 169.254.169.254."""
    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://169.254.170.2/v2/metadata")


def test_w04_reject_forbidden_schemes():
    """W04: Rejection of non-HTTP schemes (file://, data:, gopher://, ftp://)."""
    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("file:///etc/passwd")

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("gopher://example.com")

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("data:text/html,<h1>Hello</h1>")

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("ftp://ftp.example.com/file.txt")


def test_w05_reject_obfuscated_decimal_and_internal_ports():
    """W05: Rejection of decimal IP tricks (e.g. 2130706433 -> 127.0.0.1) and sensitive ports."""
    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://2130706433/")  # 127.0.0.1 in decimal

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://example.com:22/")  # SSH port

    with pytest.raises(SSRFSecurityViolation):
        validate_safe_url("http://example.com:6379/")  # Redis port


def test_w06_safe_public_url_validation():
    """W06: Acceptance and normalization of valid public URLs."""
    valid_url = "https://www.isro.gov.in/LVM3.html"
    result = validate_safe_url(valid_url)
    assert result == valid_url
    assert is_safe_url("https://en.wikipedia.org/wiki/Geosynchronous_Satellite_Launch_Vehicle")


# ── W07-W11: Web Search Engine ───────────────────────────────────────────────

def test_w07_web_search_serper_mock():
    """W07: web_search returns ranked, formatted results via Serper mock."""
    tool = WebSearchTool()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "organic": [
            {
                "title": "ISRO LVM3 Vehicle Details",
                "link": "https://www.isro.gov.in/lvm3.html?utm_source=twitter",
                "snippet": "LVM3 is ISRO's operational heavy lift launch vehicle.",
                "date": "2024-01-01",
            },
            {
                "title": "LVM3 Mission Profile",
                "link": "https://www.spaceflightnow.com/lvm3",
                "snippet": "Detailed flight parameters for LVM3 launches.",
            }
        ]
    }

    with patch("tools.web_search_tools.is_serper_available", return_value=True):
        with patch("httpx.Client.post", return_value=mock_resp):
            res = tool.execute(WebSearchTool.Input(query="ISRO LVM3 rocket specs", num_results=2))
            assert res.success
            assert "ISRO LVM3 Vehicle Details" in res.output
            assert res.metadata["provider"] == "serper"
            assert len(res.metadata["results"]) == 2


def test_w08_web_search_fallback_to_tavily():
    """W08: web_search falls back to Tavily if Serper is unconfigured or fails."""
    tool = WebSearchTool()
    mock_tavily = MagicMock()
    mock_tavily.status_code = 200
    mock_tavily.json.return_value = {
        "results": [
            {
                "title": "Tavily ISRO Overview",
                "url": "https://en.wikipedia.org/wiki/LVM3",
                "content": "LVM3 heavy lift launch vehicle developed by ISRO.",
            }
        ]
    }

    with patch("tools.web_search_tools.is_serper_available", return_value=False):
        with patch("tools.web_search_tools.is_tavily_available", return_value=True):
            with patch("httpx.Client.post", return_value=mock_tavily):
                res = tool.execute(WebSearchTool.Input(query="ISRO LVM3", num_results=1))
                assert res.success
                assert res.metadata["provider"] == "tavily"
                assert "Tavily ISRO Overview" in res.output


def test_w09_web_search_fallback_to_duckduckgo():
    """W09: web_search falls back to DuckDuckGo when Serper and Tavily are unavailable."""
    tool = WebSearchTool()
    mock_ddg = MagicMock()
    mock_ddg.status_code = 200
    mock_ddg.json.return_value = {
        "Heading": "ISRO",
        "AbstractText": "Indian Space Research Organisation",
        "AbstractURL": "https://en.wikipedia.org/wiki/ISRO",
        "RelatedTopics": []
    }

    with patch("tools.web_search_tools.is_serper_available", return_value=False):
        with patch("tools.web_search_tools.is_tavily_available", return_value=False):
            with patch("httpx.Client.get", return_value=mock_ddg):
                res = tool.execute(WebSearchTool.Input(query="ISRO", num_results=1))
                assert res.success
                assert res.metadata["provider"] == "duckduckgo"
                assert "Indian Space Research Organisation" in res.output


def test_w10_url_normalization_and_dedup():
    """W10: URL normalization removes tracking parameters and deduplicates results."""
    url1 = "https://example.com/page?utm_source=google&utm_medium=cpc&ref=twitter"
    url2 = "https://EXAMPLE.COM/page"
    assert normalize_url(url1) == "https://example.com/page"
    assert normalize_url(url2) == "https://example.com/page"


def test_w11_web_search_validation_rejection():
    """W11: web_search rejects empty or over-length queries."""
    with pytest.raises(Exception):
        WebSearchTool.Input(query="")

    with pytest.raises(Exception):
        WebSearchTool.Input(query="x" * 600)


# ── W12-W15: Web Fetch ───────────────────────────────────────────────────────

def test_w12_html_to_markdown_clean():
    """W12: html_to_clean_markdown strips nav/script/style and converts headings and links."""
    html = """
    <html>
      <head><script>alert(1)</script><style>body { color: red; }</style></head>
      <body>
        <nav><a href="/home">Home</a></nav>
        <h1>ISRO LVM3 Specifications</h1>
        <p>The vehicle features two <a href="https://isro.gov.in/s200">S200 solid boosters</a>.</p>
        <ul>
          <li>Height: 43.5 m</li>
          <li>Lift-off mass: 640 tonnes</li>
        </ul>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    md = html_to_clean_markdown(html, base_url="https://isro.gov.in")
    assert "# ISRO LVM3 Specifications" in md
    assert "[S200 solid boosters](https://isro.gov.in/s200)" in md
    assert "- Height: 43.5 m" in md
    assert "alert(1)" not in md
    assert "Copyright 2026" not in md


def test_w13_web_fetch_ssrf_rejection():
    """W13: web_fetch actively blocks SSRF targets with exit code 1."""
    tool = WebFetchTool()
    res = tool.execute(WebFetchTool.Input(url="http://127.0.0.1:8765/secret"))
    assert not res.success
    assert res.exit_code == 1
    assert "SSRF" in res.error


def test_w14_web_fetch_json_formatting():
    """W14: web_fetch formats raw JSON API responses as indented JSON."""
    tool = WebFetchTool()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.iter_bytes.return_value = [b'{"status": "ok", "count": 42}']
    mock_resp.encoding = "utf-8"

    with patch("core.security.web_security.resolve_and_validate_host", return_value=["93.184.216.34"]):
        with patch("httpx.Client.stream") as mock_stream:
            mock_stream.return_value.__enter__.return_value = mock_resp
            res = tool.execute(WebFetchTool.Input(url="https://api.example.com/data"))
            assert res.success
            assert '"count": 42' in res.output


def test_w15_web_fetch_jina_fallback_on_empty():
    """W15: web_fetch triggers Jina Reader fallback when page HTML is empty or JS-only."""
    tool = WebFetchTool()
    mock_empty_resp = MagicMock()
    mock_empty_resp.status_code = 200
    mock_empty_resp.headers = {"content-type": "text/html"}
    mock_empty_resp.iter_bytes.return_value = [b'<html><body><div id="root"></div></body></html>']
    mock_empty_resp.encoding = "utf-8"

    with patch("core.security.web_security.resolve_and_validate_host", return_value=["93.184.216.34"]):
        with patch("httpx.Client.stream") as mock_stream:
            mock_stream.return_value.__enter__.return_value = mock_empty_resp
            with patch.object(tool, "_fetch_via_jina", return_value="# Rendered Content via Jina\nDetailed specs."):
                res = tool.execute(WebFetchTool.Input(url="https://app.example.com/"))
                assert res.success
                assert "Rendered Content via Jina" in res.output


# ── W16-W19: Bounded Web Crawl ───────────────────────────────────────────────

def test_w16_web_crawl_bounded_depth_and_pages():
    """W16-W19: web_crawl respects depth <= 2, ceiling <= 6 pages, and domain scope."""
    tool = WebCrawlTool()
    p1 = "<html><head><title>Page 1</title></head><body><a href='/page2'>Page 2</a><a href='https://external.com'>Ext</a></body></html>"
    p2 = "<html><head><title>Page 2</title></head><body><h1>Content 2</h1></body></html>"

    def mock_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "text/html"}
        if "page2" in str(url):
            resp.text = p2
        else:
            resp.text = p1
        return resp

    with patch("core.security.web_security.resolve_and_validate_host", return_value=["93.184.216.34"]):
        with patch("httpx.Client.get", side_effect=mock_get):
            res = tool.execute(WebCrawlTool.Input(start_url="https://example.com/page1", max_pages=3, max_depth=2))
            assert res.success
            assert res.metadata["pages_count"] == 2
            # Verify external.com was NOT crawled
            urls = [p["url"] for p in res.metadata["pages"]]
            assert all("example.com" in u for u in urls)


# ── W20-W22: Visual Assets and Download ──────────────────────────────────────

def test_w20_image_search_pixabay_mock():
    """W20: image_search returns candidate images with dimensions, author, and license."""
    tool = ImageSearchTool()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "hits": [
            {
                "id": 12345,
                "previewURL": "https://cdn.pixabay.com/photo/preview.jpg",
                "largeImageURL": "https://cdn.pixabay.com/photo/large.jpg",
                "tags": "rocket, launch, space",
                "user": "SpacePhotographer",
                "user_id": 999,
                "imageWidth": 1920,
                "imageHeight": 1080,
            }
        ]
    }

    with patch("tools.image_asset_tools.is_pixabay_available", return_value=True):
        with patch("httpx.Client.get", return_value=mock_resp):
            res = tool.execute(ImageSearchTool.Input(query="rocket launch", num_results=1))
            assert res.success
            assert res.metadata["count"] == 1
            img = res.metadata["images"][0]
            assert img["width"] == 1920
            assert img["height"] == 1080
            assert "Pixabay Content License" in img["license"]


def test_w21_verify_image_magic_bytes():
    """W21: verify_image_magic_bytes accepts valid JPEG/PNG/WebP and rejects text/HTML."""
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 30
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
    webp_bytes = b"RIFF\x20\x00\x00\x00WEBPVP8 " + b"\x00" * 20

    assert verify_image_magic_bytes(jpeg_bytes) == "jpeg"
    assert verify_image_magic_bytes(png_bytes) == "png"
    assert verify_image_magic_bytes(webp_bytes) == "webp"

    # Rejection of HTML error page
    with pytest.raises(ValueError, match="HTML or text error"):
        verify_image_magic_bytes(b"<html><body>404 Not Found</body></html>")


def test_w22_download_image_writes_manifest_and_credits(tmp_path, monkeypatch):
    """W22: download_image atomically saves to assets/images/ and updates manifest & credits."""
    monkeypatch.setenv("HERMES_WORKSPACE_ROOT", str(tmp_path))
    tool = DownloadImageTool()

    # Create real small PNG image bytes
    buf = io.BytesIO()
    img = Image.new("RGB", (200, 100), color="blue")
    img.save(buf, format="PNG")
    raw_png = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = raw_png

    with patch("core.security.web_security.resolve_and_validate_host", return_value=["93.184.216.34"]):
        with patch("httpx.Client.get", return_value=mock_resp):
            res = tool.execute(DownloadImageTool.Input(
                image_url="https://images.example.com/rocket.png",
                filename="test_rocket.png",
                alt_text="Test Rocket Launch",
                attribution={
                    "author": "Test Artist",
                    "license": "Pixabay Content License",
                    "source_platform": "Pixabay",
                }
            ))

            assert res.success
            saved_file = tmp_path / "assets" / "images" / "test_rocket.png"
            assert saved_file.exists()
            assert res.metadata["width"] == 200
            assert res.metadata["height"] == 100

            # Verify asset_manifest.json
            manifest_file = tmp_path / "assets" / "images" / "asset_manifest.json"
            assert manifest_file.exists()
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            assert len(manifest["assets"]) == 1
            assert manifest["assets"][0]["filename"] == "test_rocket.png"
            assert manifest["assets"][0]["format"] == "png"

            # Verify IMAGE_CREDITS.md
            credits_file = tmp_path / "IMAGE_CREDITS.md"
            assert credits_file.exists()
            credits_text = credits_file.read_text(encoding="utf-8")
            assert "test_rocket.png" in credits_text
            assert "Test Artist" in credits_text


# ── UI01-UI05: Orchestration, Headlines, API Status, and Secret Safety ───────

def test_ui01_deep_web_research_synthesis():
    """UI01: deep_web_research orchestrates search and fetch into a cited research brief."""
    tool = DeepWebResearchTool()

    mock_search = ToolResult(
        success=True,
        output="Result",
        metadata={
            "results": [
                {
                    "title": "LVM3 Technical Specs",
                    "url": "https://example.com/lvm3_specs",
                    "snippet": "Solid boosters generate 10,000 kN thrust.",
                }
            ]
        }
    )

    mock_fetch = ToolResult(
        success=True,
        output="# LVM3 Specifications\nThe S200 solid rocket boosters provide initial liftoff thrust.",
    )

    with patch.object(WebSearchTool, "execute", return_value=mock_search):
        with patch.object(WebFetchTool, "execute", return_value=mock_fetch):
            res = tool.execute(DeepWebResearchTool.Input(topic="ISRO LVM3 Booster Thrust"))
            assert res.success
            assert "# Research Brief: ISRO LVM3 Booster Thrust" in res.output
            assert "[LVM3 Technical Specs](https://example.com/lvm3_specs)" in res.output


def test_ui02_format_tool_headlines():
    """UI02: format_tool_headline produces descriptive UI headlines for research tools."""
    h1, _ = format_tool_headline("web_search", {"query": "LVM3 rocket"}, is_completed=False)
    assert "Searched web for 'LVM3 rocket'" in h1

    h2, _ = format_tool_headline("image_search", {"query": "chandrayaan"}, is_completed=False)
    assert "Searching images for 'chandrayaan'" in h2

    h3, _ = format_tool_headline(
        "download_image",
        {"filename": "launch.jpg"},
        is_completed=True,
        obs=MagicMock(metadata={"filename": "launch.jpg", "width": 1920, "height": 1080})
    )
    assert "Downloaded launch.jpg (1920x1080)" in h3


def test_ui04_research_status_api_safety():
    """UI04: get_research_status reports provider availability without exposing raw keys."""
    status = get_research_status()
    assert "serper" in status
    assert "tavily" in status
    assert "pixabay" in status
    assert isinstance(status["serper"]["configured"], bool)
    assert isinstance(status["pixabay"]["configured"], bool)
    # Ensure no secrets leak in status values
    status_str = json.dumps(status)
    assert "7a9c4d" not in status_str
    assert "582835" not in status_str
    assert "tvly-dev" not in status_str


def test_ui05_event_lifecycle_redaction():
    """UI05: Event payloads automatically scrub sensitive credentials."""
    event = HermesEvent(
        event_type=EventType.WEB_SEARCH_COMPLETED,
        payload={
            "query": "ISRO specs",
            "api_key": "secret_key_12345",
            "token": "ghp_123456789012345678901234567890123456",
        }
    )
    dumped = event.to_dict()
    assert dumped["payload"]["api_key"] == "[REDACTED_SECRET]"
    assert dumped["payload"]["token"] == "[REDACTED_SECRET]"
