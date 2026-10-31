import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from core.browser.driver import CdpBrowserDriver
from core.browser.models import Viewport

ARTIFACTS_DIR = Path("C:/Users/SUBBU/.gemini/antigravity/brain/87b861ce-9b10-4311-b870-8944e651cd6a")

async def test_isro_lvm3_simulation():
    print("======================================================================")
    print("AUTOMATED REAL BROWSER QUALIFICATION: ISRO LVM3-M6 LAUNCH SIMULATION")
    print("======================================================================")

    driver = CdpBrowserDriver()
    launched = await driver.launch()
    print(f"Browser launched: {launched}")
    assert launched, "Failed to launch Edge via CDP"

    target_url = "http://127.0.0.1:8088/index.html"
    print(f"Navigating to: {target_url}")
    nav = await driver.navigate(target_url)
    print(f"Navigation: success={nav.success} | Title='{nav.title}'")
    assert nav.success, f"Navigation failed: {nav.error}"

    # Wait 2.0s for Three.js scene, WebGL renderer, and fonts to load
    await asyncio.sleep(2.0)

    # ── Screenshot 1: Pad View, Initial State (T+00:00) ──
    shot1_path = ARTIFACTS_DIR / "isro_lvm3_pad_initial.png"
    shot1 = await driver.capture_screenshot(shot1_path, viewport=Viewport(width=1366, height=768))
    print(f"1. Captured Pad Initial View: {shot1.file_path}")

    # ── Screenshot 2: Vehicle Specs Modal ──
    print("Opening Vehicle Specs Modal...")
    await driver.click("#btn-specs-toggle")
    await asyncio.sleep(0.5)
    shot2_path = ARTIFACTS_DIR / "isro_lvm3_specs_modal.png"
    shot2 = await driver.capture_screenshot(shot2_path, viewport=Viewport(width=1366, height=768))
    print(f"2. Captured Vehicle Specs Modal: {shot2.file_path}")

    # Close modal
    await driver.click("#btn-close-specs")
    await asyncio.sleep(0.5)

    # ── Start Launch Simulation ──
    print("Starting Launch Simulation (clicking #btn-play-pause)...")
    await driver.click("#btn-play-pause")
    await asyncio.sleep(0.5)

    # Set Warp 5x for smooth fast progression
    print("Setting Time Warp to 5x...")
    await driver.click(".btn-warp[data-warp='5']")
    await asyncio.sleep(0.5)

    # Set Chase Camera
    print("Switching to CHASE Camera...")
    await driver.click(".btn-cam[data-cam='chase']")

    # Let simulation progress to T+135s (at 5x warp, 135s = ~27s real time)
    print("Waiting for S200 Booster Separation (T+130s - T+140s)...")
    await asyncio.sleep(27.0)

    # ── Screenshot 3: S200 Booster Separation ──
    shot3_path = ARTIFACTS_DIR / "isro_lvm3_booster_separation.png"
    shot3 = await driver.capture_screenshot(shot3_path, viewport=Viewport(width=1366, height=768))
    print(f"3. Captured S200 Booster Separation View: {shot3.file_path}")

    # Switch to Booster Cam to inspect jettison
    print("Switching to BOOSTER Camera & setting 5x warp towards Fairing Separation...")
    await driver.click(".btn-cam[data-cam='booster']")
    # Wait another 13s (at 5x warp = 65s mission time -> T+200s for Payload Fairing separation)
    await asyncio.sleep(13.0)

    # ── Screenshot 4: Payload Fairing Separation ──
    shot4_path = ARTIFACTS_DIR / "isro_lvm3_fairing_separation.png"
    shot4 = await driver.capture_screenshot(shot4_path, viewport=Viewport(width=1366, height=768))
    print(f"4. Captured Payload Fairing Separation View: {shot4.file_path}")

    # Switch to Orbit Camera and accelerate to 10x
    print("Switching to ORBIT Camera & setting 10x warp towards C25 Cryogenic Insertion...")
    await driver.click(".btn-warp[data-warp='10']")
    await driver.click(".btn-cam[data-cam='orbit']")
    # Wait 12s (at 10x warp = 120s mission time -> T+320s for C25 Cryogenic burn)
    await asyncio.sleep(12.0)

    # ── Screenshot 5: C25 Cryogenic Upper Stage Burn & Earth Horizon ──
    shot5_path = ARTIFACTS_DIR / "isro_lvm3_cryo_stage_orbit.png"
    shot5 = await driver.capture_screenshot(shot5_path, viewport=Viewport(width=1366, height=768))
    print(f"5. Captured C25 Cryogenic Orbital Insertion View: {shot5.file_path}")

    # Check Console Errors
    msgs = driver.get_console_messages()
    errs = [m for m in msgs if m.level == "error"]
    print(f"Console Message Audit: {len(msgs)} total messages, {len(errs)} errors.")
    for err in errs:
        print(f"  [BROWSER ERROR]: {err.text}")

    await driver.close()
    print("Browser closed cleanly.")

    assert len(errs) == 0, f"Encountered uncaught browser errors: {errs}"
    print("\n[ALL CHECKS PASSED] ISRO LVM3 LAUNCH SIMULATION VERIFIED LIVE IN REAL BROWSER!")

if __name__ == "__main__":
    asyncio.run(test_isro_lvm3_simulation())
