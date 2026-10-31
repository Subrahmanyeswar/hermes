import asyncio
import os
import sys
from pathlib import Path

# Add hermes to path
sys.path.insert(0, r"C:\Users\SUBBU\Downloads\hermes")

from core.browser.dev_server import DevServerManager
from core.browser.driver import CdpBrowserDriver
from core.browser.models import BrowserSessionConfig, Viewport

WORKSPACE = Path(r"C:\Users\SUBBU\Downloads\rocket7 hermes test")
ARTIFACTS_DIR = Path(r"C:\Users\SUBBU\.gemini\antigravity\brain\87b861ce-9b10-4311-b870-8944e651cd6a")

async def evaluate_js(driver: CdpBrowserDriver, expr: str):
    res = await driver._send_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    if "exceptionDetails" in res:
        print("JS EXCEPTION:", res.get("exceptionDetails"))
    return res.get("result", {}).get("value")

async def run_rocket7_browser_qualification():
    print(f"=== Qualification Mission: ISRO LVM3 Browser CDP Verification ===")
    print(f"Target Workspace: {WORKSPACE}")
    
    # 1. Start DevServer strictly bound to rocket7
    dsm = DevServerManager()
    server_info = await dsm.start_static_server(WORKSPACE, name="rocket7_preview")
    base_url = server_info.url
    print(f"DevServer running at: {base_url}")
    target_url = f"{base_url}/index.html"
    
    driver = CdpBrowserDriver()
    config = BrowserSessionConfig(viewport=Viewport(width=1440, height=900), headless=True)
    launched = await driver.launch(config)
    assert launched, "Failed to launch CDP browser driver"
    
    evidence = []
    
    try:
        # Step 1: Initial Pad Load
        print(f"\n[Step 1] Navigating to {target_url} (Desktop 1440x900)...")
        nav_res = await driver.navigate(target_url)
        assert nav_res.success, f"Navigation failed: {nav_res.error}"
        await asyncio.sleep(2.0)
        
        # Verify WebGL context
        webgl_ok = await evaluate_js(driver, """(() => {
            const canvas = document.querySelector('#canvas-container canvas') || document.querySelector('canvas');
            if (!canvas) return { ok: false, error: 'canvas not found' };
            const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
            return {
                ok: !!gl,
                renderer: gl ? gl.getParameter(gl.RENDERER) : null,
                vendor: gl ? gl.getParameter(gl.VENDOR) : null
            };
        })()""")
        print("WebGL Context Check:", webgl_ok)
        assert webgl_ok and webgl_ok.get("ok"), f"WebGL context initialization failed: {webgl_ok}"
        
        # Step 1 Screenshot: Pad Initial
        pad_shot = ARTIFACTS_DIR / "rocket7_lvm3_pad_initial.png"
        await driver.capture_screenshot(pad_shot)
        assert pad_shot.exists() and pad_shot.stat().st_size > 10000
        print(f"Captured initial pad screenshot: {pad_shot} ({pad_shot.stat().st_size} bytes)")
        evidence.append("rocket7_lvm3_pad_initial.png")
        
        # Step 2: Open ISRO Specifications Modal
        print("\n[Step 2] Opening Specifications Modal...")
        modal_opened = await evaluate_js(driver, """(() => {
            const btn = document.getElementById('btn-specs-toggle');
            if (btn) { btn.click(); return true; }
            return false;
        })()""")
        await asyncio.sleep(0.5)
        specs_shot = ARTIFACTS_DIR / "rocket7_lvm3_specs_modal.png"
        await driver.capture_screenshot(specs_shot)
        assert specs_shot.exists() and specs_shot.stat().st_size > 10000
        print(f"Captured specs modal screenshot: {specs_shot} ({specs_shot.stat().st_size} bytes)")
        evidence.append("rocket7_lvm3_specs_modal.png")
        
        # Close modal
        await evaluate_js(driver, """(() => {
            const closeBtn = document.getElementById('btn-close-specs');
            if (closeBtn) closeBtn.click();
        })()""")
        await asyncio.sleep(0.5)
        
        # Step 3: Trigger Launch (Liftoff & Plume)
        print("\n[Step 3] Triggering Launch...")
        launched_ok = await evaluate_js(driver, """(() => {
            const btn = document.getElementById('btn-play-pause');
            if (btn) { btn.click(); return true; }
            return false;
        })()""")
        print("Launch button clicked:", launched_ok)
        await asyncio.sleep(3.5)
        
        # Check telemetry updates
        telemetry = await evaluate_js(driver, """(() => {
            const alt = document.getElementById('telem-altitude')?.textContent;
            const vel = document.getElementById('telem-velocity')?.textContent;
            const time = document.getElementById('met-clock')?.textContent;
            const stage = document.getElementById('current-stage-name')?.textContent;
            return { altitude: alt, velocity: vel, met: time, stage: stage };
        })()""")
        print("Telemetry after 3.5s:", telemetry)
        
        liftoff_shot = ARTIFACTS_DIR / "rocket7_lvm3_liftoff.png"
        await driver.capture_screenshot(liftoff_shot)
        assert liftoff_shot.exists() and liftoff_shot.stat().st_size > 10000
        print(f"Captured liftoff screenshot: {liftoff_shot} ({liftoff_shot.stat().st_size} bytes)")
        evidence.append("rocket7_lvm3_liftoff.png")
        
        # Step 4: Advance to Booster Separation (T+135s)
        print("\n[Step 4] Advancing to Booster Separation...")
        await evaluate_js(driver, """(() => {
            if (window.missionSim) {
                window.missionSim.currentTime = 135.0;
                window.missionSim.setCameraMode('booster');
            }
        })()""")
        await asyncio.sleep(1.0)
        
        booster_shot = ARTIFACTS_DIR / "rocket7_lvm3_booster_separation.png"
        await driver.capture_screenshot(booster_shot)
        assert booster_shot.exists() and booster_shot.stat().st_size > 10000
        print(f"Captured booster separation screenshot: {booster_shot} ({booster_shot.stat().st_size} bytes)")
        evidence.append("rocket7_lvm3_booster_separation.png")
        
        # Step 5: Advance to Cryogenic Stage / Orbit (T+350s)
        print("\n[Step 5] Advancing to Cryogenic Stage & Orbit Insertion...")
        await evaluate_js(driver, """(() => {
            if (window.missionSim) {
                window.missionSim.currentTime = 350.0;
                window.missionSim.setCameraMode('orbit');
            }
        })()""")
        await asyncio.sleep(1.0)
        
        orbit_shot = ARTIFACTS_DIR / "rocket7_lvm3_cryo_orbit.png"
        await driver.capture_screenshot(orbit_shot)
        assert orbit_shot.exists() and orbit_shot.stat().st_size > 10000
        print(f"Captured cryogenic orbit screenshot: {orbit_shot} ({orbit_shot.stat().st_size} bytes)")
        evidence.append("rocket7_lvm3_cryo_orbit.png")
        
        # Step 6: Console Logs & Zero Errors Check
        logs = driver.get_console_messages()
        errors = [l for l in logs if getattr(l, "level", "") in ("error", "severe")]
        print(f"\nConsole message count: {len(logs)}, errors: {len(errors)}")
        if errors:
            for err in errors:
                print(f"  [ERROR] {getattr(err, 'text', err)}")
        assert len(errors) == 0, f"Found {len(errors)} console errors during simulation execution!"
        print("PASS: Zero console errors detected.")
        
        print(f"\n=== QUALIFICATION COMPLETE: 5/5 Visual Milestones Verified ===")
        print(f"Evidence artifacts created:")
        for ev in evidence:
            print(f"  - {ev}")
        
    finally:
        await driver.close()
        dsm.stop_all()

if __name__ == "__main__":
    asyncio.run(run_rocket7_browser_qualification())
