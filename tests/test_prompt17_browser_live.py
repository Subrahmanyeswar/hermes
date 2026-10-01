# tests/test_prompt17_browser_live.py
"""
Live Integration Test: Real Browser Binary Execution (Microsoft Edge / Google Chrome).
Tests actual headless browser launch, about:blank navigation, and screenshot rendering.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.browser.driver import CdpBrowserDriver
from core.browser.models import Viewport


@pytest.mark.asyncio
async def test_live_cdp_browser_launch_and_screenshot(tmp_path: Path):
    """Launch real Edge/Chrome binary in headless mode and capture screenshot."""
    driver = CdpBrowserDriver()
    if not driver.is_available:
        pytest.skip("Neither Microsoft Edge nor Google Chrome found on system")

    launched = await driver.launch()
    assert launched is True
    assert driver.port > 0

    try:
        # Navigate to a simple local data URL
        data_url = "data:text/html,<html><head><title>Live Test</title></head><body><h1>Live Chrome/Edge Test</h1></body></html>"
        res = await driver.navigate(data_url)
        assert res.success is True

        # Capture real screenshot
        shot_path = tmp_path / "live_shot.png"
        shot = await driver.capture_screenshot(shot_path, viewport=Viewport.desktop())
        assert shot.width == 1280
        assert shot.height == 800
        assert shot_path.exists()
    finally:
        await driver.close()
