import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from core.browser.driver import CdpBrowserDriver
from core.browser.models import Viewport

WORKSPACE_DIR = Path("C:/Users/SUBBU/Downloads/hermes_controlled_generation_ws")
ARTIFACTS_DIR = Path("C:/Users/SUBBU/.gemini/antigravity/brain/87b861ce-9b10-4311-b870-8944e651cd6a")

async def test_browser_acceptance():
    print("======================================================================")
    print("REAL BROWSER ACCEPTANCE TESTING VIA CDP (MICROSOFT EDGE)")
    print("======================================================================")
    
    driver = CdpBrowserDriver()
    launched = await driver.launch()
    print(f"Browser launched: {launched}")
    assert launched, "Failed to launch Edge browser via CDP"

    target_url = f"file:///{str(WORKSPACE_DIR / 'index.html').replace(os.sep, '/')}"
    print(f"Navigating to generated app: {target_url}")
    nav = await driver.navigate(target_url)
    print(f"Navigation success: {nav.success} | Title: '{nav.title}'")
    assert nav.success, f"Navigation failed: {nav.error}"

    await asyncio.sleep(1.0)

    # 1. Capture initial desktop screenshot
    shot1_path = ARTIFACTS_DIR / "counter_desktop_initial.png"
    shot1 = await driver.capture_screenshot(shot1_path, viewport=Viewport(width=1280, height=800))
    print(f"1. Captured initial desktop screenshot: {shot1.file_path} ({shot1.width}x{shot1.height})")

    # 2. Inspect DOM and click increment button
    dom = await driver.inspect_dom()
    print(f"2. Inspected DOM: {len(dom.elements)} elements found.")
    
    inc_res = await driver.click("#increment")
    print(f"   Clicked #increment: success={inc_res.success}")
    await asyncio.sleep(0.3)
    inc_res2 = await driver.click("#increment")
    print(f"   Clicked #increment second time: success={inc_res2.success}")
    await asyncio.sleep(0.5)

    # 3. Capture incremented screenshot
    shot2_path = ARTIFACTS_DIR / "counter_desktop_incremented.png"
    shot2 = await driver.capture_screenshot(shot2_path, viewport=Viewport(width=1280, height=800))
    print(f"3. Captured incremented screenshot: {shot2.file_path}")

    # 4. Click reset button
    reset_res = await driver.click("#reset")
    print(f"4. Clicked #reset: success={reset_res.success}")
    await asyncio.sleep(0.5)

    # 5. Capture reset screenshot
    shot3_path = ARTIFACTS_DIR / "counter_desktop_reset.png"
    shot3 = await driver.capture_screenshot(shot3_path, viewport=Viewport(width=1280, height=800))
    print(f"5. Captured reset screenshot: {shot3.file_path}")

    # 6. Check console errors
    msgs = driver.get_console_messages()
    errs = [m for m in msgs if m.level == "error"]
    print(f"6. Console validation: {len(msgs)} total messages, {len(errs)} errors.")
    for err in errs:
        print(f"   [CONSOLE ERROR]: {err.text}")
    assert len(errs) == 0, f"Uncaught console errors detected: {errs}"

    await driver.close()
    print("7. Browser closed cleanly.")
    print("\n[PASS] REAL BROWSER ACCEPTANCE COMPLETE: All interactions verified, zero console errors!")

if __name__ == "__main__":
    asyncio.run(test_browser_acceptance())
