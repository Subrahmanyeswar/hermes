# tests/test_prompt17_browser.py
"""
Test Suite: Prompt 17 Browser Subsystem.
Validates security policies (SSRF defense, localhost scoping, secret redaction),
dev server lifecycle, driver execution, DOM inspection, screenshots, and BaseTools.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.browser.dev_server import DevServerManager
from core.browser.driver import SimulatedBrowserDriver
from core.browser.manager import BrowserManager
from core.browser.models import Viewport
from core.browser.security import BrowserSecurityManager, BrowserSecurityViolation
from core.browser.tools import (
    BrowserClickTool,
    BrowserConsoleTool,
    BrowserInspectTool,
    BrowserNavigateTool,
    BrowserNetworkTool,
    BrowserScreenshotTool,
    BrowserTypeTool,
)


def test_browser_security_policies():
    """Verify SSRF defense, scheme restrictions, and secret redaction."""
    sec = BrowserSecurityManager(allow_localhost=True)

    # 1. Block cloud metadata
    with pytest.raises(BrowserSecurityViolation):
        sec.validate_url("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(BrowserSecurityViolation):
        sec.validate_url("http://metadata.google.internal/computeMetadata/v1/")

    # 2. Block invalid schemes
    with pytest.raises(BrowserSecurityViolation):
        sec.validate_url("javascript:alert(1)")

    with pytest.raises(BrowserSecurityViolation):
        sec.validate_url("ftp://ftp.example.com")

    # 3. Allow safe localhost
    assert sec.validate_url("http://localhost:8000/index.html") == "http://localhost:8000/index.html"
    assert sec.validate_url("http://127.0.0.1:3000/api") == "http://127.0.0.1:3000/api"

    # 4. Redact secret URL parameters
    safe_url = sec.redact_url("https://example.com/api?token=secret123&user=alice&password=mypassword")
    assert "token=%5BREDACTED%5D" in safe_url or "token=[REDACTED]" in safe_url
    assert "password=%5BREDACTED%5D" in safe_url or "password=[REDACTED]" in safe_url
    assert "user=alice" in safe_url

    # 5. Redact headers
    raw_headers = {
        "Authorization": "Bearer abcdef123456",
        "Cookie": "session_id=xyz",
        "Content-Type": "application/json",
    }
    cleaned = sec.redact_headers(raw_headers)
    assert cleaned["Authorization"] == "[REDACTED]"
    assert cleaned["Cookie"] == "[REDACTED]"
    assert cleaned["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_dev_server_lifecycle(tmp_path: Path):
    """Verify DevServerManager starts static server and terminates cleanly."""
    site_dir = tmp_path / "web"
    site_dir.mkdir()
    index_file = site_dir / "index.html"
    index_file.write_text("<!DOCTYPE html><html><head><title>Test App</title></head><body><h1>Hello World</h1></body></html>", encoding="utf-8")

    mgr = DevServerManager()
    try:
        info = await mgr.start_static_server(site_dir, name="test_site", timeout=5.0)
        assert info.port > 0
        assert info.url.startswith("http://127.0.0.1:")
        assert info.process.poll() is None

        # Stop server
        mgr.stop_server("test_site")
        assert info.process.poll() is not None
    finally:
        mgr.stop_all()


@pytest.mark.asyncio
async def test_simulated_browser_navigation_and_actions(tmp_path: Path):
    """Verify simulated driver navigates HTML, fills form, clicks, and captures screenshot."""
    html_content = (
        "<!DOCTYPE html>"
        "<html><head><title>Demo Store</title></head>"
        "<body>"
        "  <h1>Welcome to Store</h1>"
        "  <form id='login-form'>"
        "    <input id='username' name='user' placeholder='Enter username' />"
        "    <input id='password' name='pass' type='password' placeholder='Enter password' />"
        "    <button id='login-btn' type='submit'>Sign In</button>"
        "  </form>"
        "</body></html>"
    )

    page_file = tmp_path / "index.html"
    page_file.write_text(html_content, encoding="utf-8")
    page_url = page_file.as_uri()

    driver = SimulatedBrowserDriver()
    await driver.launch()

    # 1. Navigate
    nav_res = await driver.navigate(page_url)
    assert nav_res.success
    assert nav_res.title == "Demo Store"
    assert nav_res.status == 200

    # 2. Inspect DOM
    inspect_res = await driver.inspect_dom()
    assert inspect_res.title == "Demo Store"
    assert inspect_res.interactive_count >= 3
    assert "Welcome to Store" in inspect_res.visible_text

    # 3. Type text
    type_res1 = await driver.type_text("username", "testuser")
    assert type_res1.success
    assert driver.form_inputs.get("username") == "testuser"

    type_res2 = await driver.type_text("password", "secretpass", is_secret=True)
    assert type_res2.success
    assert driver.form_inputs.get("password") == "secretpass"

    # 4. Click button
    click_res = await driver.click("Sign In")
    assert click_res.success

    # 5. Capture screenshot artifact
    shot_path = tmp_path / "shot.png"
    shot = await driver.capture_screenshot(shot_path, viewport=Viewport.desktop())
    assert shot.file_path == str(shot_path.resolve())
    assert shot.width == 1280
    assert shot.height == 800
    assert shot_path.exists()
    assert len(shot.sha256) == 64

    # 6. Verify console & network
    console_msgs = driver.get_console_messages()
    assert len(console_msgs) > 0
    net_records = driver.get_network_records()
    assert len(net_records) > 0
    assert net_records[0].status == 200

    await driver.close()


def test_browser_tools_execution(tmp_path: Path):
    """Verify BaseTool adapters execute cleanly."""
    page_file = tmp_path / "demo.html"
    page_file.write_text(
        "<html><head><title>Tool Test</title></head>"
        "<body>"
        "  <p>Status: Ready</p>"
        "  <button id='action-btn'>Execute</button>"
        "</body></html>",
        encoding="utf-8",
    )
    page_url = page_file.as_uri()

    mgr = BrowserManager(artifacts_dir=tmp_path / "artifacts", prefer_cdp=False)

    # 1. Navigate Tool
    nav_tool = BrowserNavigateTool(manager=mgr)
    nav_res = nav_tool.execute({"url": page_url})
    assert nav_res.success
    assert "Navigated to" in nav_res.output

    # 2. Inspect Tool
    insp_tool = BrowserInspectTool(manager=mgr)
    insp_res = insp_tool.execute({})
    assert insp_res.success
    assert "Tool Test" in insp_res.output

    # 3. Click Tool
    click_tool = BrowserClickTool(manager=mgr)
    click_res = click_tool.execute({"target": "Execute"})
    assert click_res.success

    # 4. Screenshot Tool
    shot_tool = BrowserScreenshotTool(manager=mgr)
    shot_res = shot_tool.execute({"name": "tool_test", "viewport": "mobile"})
    assert shot_res.success
    assert "Screenshot captured:" in shot_res.output

    # 5. Console & Network Tools
    console_tool = BrowserConsoleTool(manager=mgr)
    assert console_tool.execute({}).success

    net_tool = BrowserNetworkTool(manager=mgr)
    assert net_tool.execute({}).success
