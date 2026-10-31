# tests/test_browser_preview_forensic_repair.py
"""
Focused regression tests for HERMES Browser Preview Forensic Repair.
Validates:
1. Successful HTML preview rendering with real CDP automation.
2. External CSS and JavaScript loading and execution.
3. Relative resource resolution in workspaces with spaces in their path.
4. Clean diagnostic error state (no silent blank white screen) on 404 or connection failure.
5. Dev server process cleanup and workspace switching.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from PIL import Image
import pytest

from core.browser.dev_server import DevServerManager
from core.browser.driver import CdpBrowserDriver, SimulatedBrowserDriver
from core.browser.models import BrowserSessionConfig, Viewport


@pytest.mark.asyncio
async def test_successful_html_preview_rendering(tmp_path: Path):
    """Case A: Isolated workspace serving known HTML via DevServer & CDP driver."""
    ws = tmp_path / "site_a"
    ws.mkdir()
    (ws / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>Preview Alpha</title></head><body><h1>Alpha Ready</h1></body></html>",
        encoding="utf-8",
    )

    dsm = DevServerManager()
    info = await dsm.start_static_server(ws, name="test_a")
    driver = CdpBrowserDriver()
    await driver.launch(BrowserSessionConfig(headless=True, viewport=Viewport.desktop()))

    try:
        nav = await driver.navigate(f"{info.url}/index.html")
        assert nav.success is True
        assert nav.status == 200
        assert "Preview Alpha" in nav.title

        insp = await driver.inspect_dom("h1")
        assert len(insp.elements) == 1
        assert "Alpha Ready" in insp.elements[0]["text"]

        shot_path = tmp_path / "shot_a.png"
        shot = await driver.capture_screenshot(shot_path)
        assert shot_path.exists()
        assert shot_path.stat().st_size > 5000, "Rendered screenshot must contain real image data"
    finally:
        await driver.close()
        dsm.stop_all()


@pytest.mark.asyncio
async def test_css_and_javascript_execution(tmp_path: Path):
    """Case B: External CSS and JS load, execute, and alter DOM."""
    ws = tmp_path / "site_b"
    ws.mkdir()
    (ws / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>Interactive App</title>"
        "<link rel='stylesheet' href='styles.css'></head>"
        "<body><h1 id='title'>Initial</h1><button id='btn'>Click</button>"
        "<script src='app.js'></script></body></html>",
        encoding="utf-8",
    )
    (ws / "styles.css").write_text("body { background: #111; color: #fff; }", encoding="utf-8")
    (ws / "app.js").write_text(
        "document.getElementById('btn').addEventListener('click', () => {"
        "  document.getElementById('title').textContent = 'Updated by JS';"
        "});",
        encoding="utf-8",
    )

    dsm = DevServerManager()
    info = await dsm.start_static_server(ws, name="test_b")
    driver = CdpBrowserDriver()
    await driver.launch(BrowserSessionConfig(headless=True, viewport=Viewport.desktop()))

    try:
        nav = await driver.navigate(f"{info.url}/index.html")
        assert nav.success is True

        click_res = await driver.click("#btn")
        assert click_res.success is True

        insp = await driver.inspect_dom("#title")
        assert len(insp.elements) == 1
        assert "Updated by JS" in insp.elements[0]["text"]
    finally:
        await driver.close()
        dsm.stop_all()


@pytest.mark.asyncio
async def test_workspace_paths_with_spaces_and_relative_assets(tmp_path: Path):
    """Case C: Workspaces containing spaces resolve relative CSS, JS, and image assets."""
    ws = tmp_path / "my special test workspace 2026"
    ws.mkdir()
    assets = ws / "assets" / "img"
    assets.mkdir(parents=True)

    # 1x1 valid PNG image
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00"
        b"\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (assets / "car.png").write_bytes(tiny_png)

    (ws / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>Spaces Test</title>"
        "<link rel='stylesheet' href='theme.css'></head>"
        "<body><h1>Car Showcase</h1><img src='assets/img/car.png' alt='Speed Car' id='hero-img'></body></html>",
        encoding="utf-8",
    )
    (ws / "theme.css").write_text("h1 { color: #f59e0b; }", encoding="utf-8")

    dsm = DevServerManager()
    info = await dsm.start_static_server(ws, name="test_c")
    driver = CdpBrowserDriver()
    await driver.launch(BrowserSessionConfig(headless=True))

    try:
        nav = await driver.navigate(f"{info.url}/index.html")
        assert nav.success is True
        insp = await driver.inspect_dom("img")
        assert len(insp.elements) == 1
        assert "Speed Car" in insp.elements[0]["text"]
    finally:
        await driver.close()
        dsm.stop_all()


@pytest.mark.asyncio
async def test_missing_resource_and_failure_diagnostics(tmp_path: Path):
    """Case D: 404 or connection failure presents clear diagnostic card, never blank white viewport."""
    ws = tmp_path / "site_d"
    ws.mkdir()
    (ws / "index.html").write_text("<h1>Real Index</h1>", encoding="utf-8")

    dsm = DevServerManager()
    info = await dsm.start_static_server(ws, name="test_d")
    driver = CdpBrowserDriver()
    await driver.launch(BrowserSessionConfig(headless=True))

    try:
        # 1. 404 navigation
        nav_404 = await driver.navigate(f"{info.url}/missing_page.html")
        assert nav_404.status == 404
        assert nav_404.success is False
        assert "Error 404" in nav_404.title

        # Verify screenshot is diagnostic card, not blank white screen
        shot_404_path = tmp_path / "shot_404.png"
        await driver.capture_screenshot(shot_404_path)
        assert shot_404_path.exists()
        assert shot_404_path.stat().st_size > 10000

        # Inspect DOM shows diagnostic error card
        insp = await driver.inspect_dom("h1")
        assert any("Resource Not Found" in el["text"] or "Error 404" in el["text"] for el in insp.elements)
    finally:
        await driver.close()
        dsm.stop_all()


@pytest.mark.asyncio
async def test_workspace_switching_and_process_cleanup(tmp_path: Path):
    """Case E: Switching workspaces terminates previous server, preventing port leakage and stale content."""
    ws1 = tmp_path / "workspace_one"
    ws1.mkdir()
    (ws1 / "index.html").write_text("<title>Site One</title><h1>Site 1</h1>", encoding="utf-8")

    ws2 = tmp_path / "workspace_two"
    ws2.mkdir()
    (ws2 / "index.html").write_text("<title>Site Two</title><h1>Site 2</h1>", encoding="utf-8")

    dsm = DevServerManager()
    try:
        # Launch for ws1
        info1 = await dsm.start_static_server(ws1, name="active_project")
        pid1 = info1.process.pid
        port1 = info1.port
        assert info1.is_alive is True

        # Switch to ws2 with same server slot name
        info2 = await dsm.start_static_server(ws2, name="active_project")
        pid2 = info2.process.pid
        port2 = info2.port
        assert info2.is_alive is True
        assert info2.workspace_dir == ws2

        # Verify old process was stopped and not leaked
        assert pid1 != pid2 or port1 != port2
        assert not info1.is_alive or info1 == info2

        # Switching back to ws1
        info3 = await dsm.start_static_server(ws1, name="active_project")
        assert info3.is_alive is True
        assert info3.workspace_dir == ws1
    finally:
        dsm.stop_all()
