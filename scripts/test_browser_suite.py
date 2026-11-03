import json
import time
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.browser_tools import (
    BrowserOpenPreviewTool,
    BrowserClickTool,
    BrowserFillTool,
    BrowserSetViewportTool,
    BrowserGetConsoleErrorsTool,
    BrowserGetNetworkFailuresTool,
    BrowserScreenshotTool,
    BrowserInspectPageTool,
    get_browser_manager,
)

ws_dir = Path(r"C:\Users\SUBBU\Downloads\HERMES_FINAL_REVIEW_DEMO").resolve()

def run_browser_verification():
    print("=" * 70)
    print("AURELION COMPLETE LIVE BROWSER & CDP VERIFICATION SUITE")
    print("=" * 70)
    
    manager = get_browser_manager()
    results = {}

    # 1. Open Preview
    print("\n[Step 1] Launching local preview server and Chrome browser...")
    open_tool = BrowserOpenPreviewTool(manager)
    res_open = open_tool.execute({"directory": str(ws_dir), "path": "index.html"})
    print("  Open Preview Success:", res_open.success)
    print("  Output:", res_open.output)
    results["step1_open_preview"] = res_open.success
    time.sleep(2)

    # 2. Inspect Home Page & DOM
    print("\n[Step 2] Inspecting Initial Page State...")
    inspect_tool = BrowserInspectPageTool(manager)
    res_inspect = inspect_tool.execute({})
    print("  Inspect Success:", res_inspect.success)
    results["step2_home_inspect"] = res_inspect.success

    # 3. Viewport 1440px Desktop
    print("\n[Step 3] Setting Desktop Viewport 1440x900...")
    vp_tool = BrowserSetViewportTool(manager)
    res_vp1440 = vp_tool.execute({"width": 1440, "height": 900})
    print("  Desktop Viewport Success:", res_vp1440.success)
    results["step3_viewport_1440"] = res_vp1440.success

    # 4. Navigation: Click Showroom (models)
    print("\n[Step 4] Navigating to Showroom (data-view='models')...")
    click_tool = BrowserClickTool(manager)
    res_click_models = click_tool.execute({"target": "[data-view='models']"})
    print("  Click Showroom Success:", res_click_models.success)
    time.sleep(1)
    results["step4_nav_models"] = res_click_models.success

    # 5. Click Vehicle Model Details
    print("\n[Step 5] Clicking Vehicle 'Explore Details'...")
    res_click_details = click_tool.execute({"target": ".btn-details, button[data-id='e-gt']"})
    print("  Click Vehicle Details Success:", res_click_details.success)
    time.sleep(1)
    results["step5_vehicle_details"] = res_click_details.success

    # 6. Click Configure from Details
    print("\n[Step 6] Navigating to Configurator from Details View...")
    res_click_config = click_tool.execute({"target": "#detailConfigureBtn, [data-view='configurator']"})
    print("  Navigate Configurator Success:", res_click_config.success)
    time.sleep(1)
    results["step6_nav_configurator"] = res_click_config.success

    # 7. Exercising Configurator Tabs & Options
    print("\n[Step 7] Exercising Configurator Tabs & Dynamic Pricing...")
    res_tab_ext = click_tool.execute({"target": ".config-tab[data-tab='exterior']"})
    time.sleep(0.5)
    res_opt_color = click_tool.execute({"target": ".option-card"})
    time.sleep(0.5)
    res_tab_wheels = click_tool.execute({"target": ".config-tab[data-tab='wheels']"})
    time.sleep(0.5)
    res_proceed = click_tool.execute({"target": "#configProceedBtn"})
    time.sleep(1)
    print(f"  Config Tabs & Options: ExtTab={res_tab_ext.success}, ColorOpt={res_opt_color.success}, WheelsTab={res_tab_wheels.success}, Proceed={res_proceed.success}")
    results["step7_configurator_interactive"] = res_tab_ext.success and res_opt_color.success and res_proceed.success

    # Dismiss Modal
    click_tool.execute({"target": "#modalCloseBtn"})
    time.sleep(0.5)

    # 8. Navigation: Test Drive
    print("\n[Step 8] Navigating to Test Drive View...")
    res_nav_td = click_tool.execute({"target": "[data-view='testdrive']"})
    print("  Click Test Drive Nav Success:", res_nav_td.success)
    time.sleep(1)
    results["step8_nav_testdrive"] = res_nav_td.success

    # 9. Test Drive Form: Invalid Submission (Empty)
    print("\n[Step 9] Testing Client-Side Validation on Test Drive Form (Empty Submission)...")
    res_td_empty = click_tool.execute({"target": "#testDriveForm button[type='submit']"})
    print("  Empty Test Drive Submitted (Validation Check):", res_td_empty.success)
    time.sleep(1)
    results["step9_testdrive_validation"] = res_td_empty.success

    # 10. Test Drive Form: Valid Submission
    print("\n[Step 10] Filling and Submitting Valid Test Drive Booking...")
    fill_tool = BrowserFillTool(manager)
    fill_tool.execute({"target": "#testDriveForm select[name='model']", "text": "e-gt"})
    fill_tool.execute({"target": "#testDriveForm select[name='location']", "text": "monaco"})
    fill_tool.execute({"target": "#testDriveForm input[name='date']", "text": "2026-11-15"})
    fill_tool.execute({"target": "#testDriveForm select[name='time']", "text": "14:00"})
    fill_tool.execute({"target": "#testDriveForm input[name='fullName']", "text": "Alexander Wright"})
    fill_tool.execute({"target": "#testDriveForm input[name='email']", "text": "alexander.wright@aurelion.luxury"})
    fill_tool.execute({"target": "#testDriveForm input[name='phone']", "text": "+1 (555) 019-2834"})
    time.sleep(1)
    res_td_valid = click_tool.execute({"target": "#testDriveForm button[type='submit']"})
    print("  Valid Test Drive Submission Success:", res_td_valid.success)
    time.sleep(1)
    results["step10_testdrive_submit_valid"] = res_td_valid.success

    # Dismiss Modal
    click_tool.execute({"target": "#modalCloseBtn"})
    time.sleep(0.5)

    # 11. Navigation: Concierge / Contact View
    print("\n[Step 11] Navigating to Concierge / Contact View...")
    res_nav_contact = click_tool.execute({"target": "[data-view='contact']"})
    print("  Click Contact Nav Success:", res_nav_contact.success)
    time.sleep(1)
    results["step11_nav_contact"] = res_nav_contact.success

    # 12. Contact Form: Valid Submission
    print("\n[Step 12] Submitting Contact Inquiry Form...")
    fill_tool.execute({"target": "#contactForm input[name='name']", "text": "Eleanor Vance"})
    fill_tool.execute({"target": "#contactForm input[name='email']", "text": "eleanor.vance@aurelion.luxury"})
    fill_tool.execute({"target": "#contactForm input[name='subject']", "text": "Private Fleet Acquisition"})
    fill_tool.execute({"target": "#contactForm textarea[name='message']", "text": "Inquiring about allocation slots for Aurelion Speeder."})
    time.sleep(1)
    res_contact_valid = click_tool.execute({"target": "#contactForm button[type='submit']"})
    print("  Contact Form Submission Success:", res_contact_valid.success)
    time.sleep(1)
    results["step12_contact_submit_valid"] = res_contact_valid.success

    # Dismiss Modal
    click_tool.execute({"target": "#modalCloseBtn"})
    time.sleep(0.5)

    # 13. Navigation: Heritage (About)
    print("\n[Step 13] Navigating to Heritage / About View...")
    res_nav_about = click_tool.execute({"target": "[data-view='about']"})
    print("  Click About Nav Success:", res_nav_about.success)
    time.sleep(1)
    results["step13_nav_about"] = res_nav_about.success

    # 14. Viewport 768px Tablet
    print("\n[Step 14] Testing Tablet Viewport 768x1024...")
    res_vp768 = vp_tool.execute({"width": 768, "height": 1024})
    print("  Tablet Viewport Success:", res_vp768.success)
    time.sleep(1)
    results["step14_viewport_768"] = res_vp768.success

    # 15. Viewport 375px Mobile & Mobile Menu Toggle
    print("\n[Step 15] Testing Mobile Viewport 375x812 & Menu Toggle...")
    res_vp375 = vp_tool.execute({"width": 375, "height": 812, "is_mobile": True})
    print("  Mobile Viewport Success:", res_vp375.success)
    time.sleep(1)
    res_mobile_menu = click_tool.execute({"target": "#mobileMenuBtn"})
    print("  Mobile Menu Toggle Success:", res_mobile_menu.success)
    time.sleep(1)
    results["step15_mobile_menu"] = res_mobile_menu.success

    # 16. Capturing Authoritative Screenshots
    print("\n[Step 16] Capturing Screenshots...")
    shot_tool = BrowserScreenshotTool(manager)
    shot_mobile = shot_tool.execute({"name": "aurelion_mobile_375px_verified"})
    vp_tool.execute({"width": 1440, "height": 900})
    time.sleep(1)
    click_tool.execute({"target": "[data-view='home']"})
    time.sleep(1)
    shot_desktop = shot_tool.execute({"name": "aurelion_desktop_1440px_verified"})
    print("  Mobile Screenshot:", shot_mobile.success, shot_mobile.output)
    print("  Desktop Screenshot:", shot_desktop.success, shot_desktop.output)
    results["step16_screenshots"] = shot_mobile.success and shot_desktop.success

    # 17. Console Errors Inspection
    print("\n[Step 17] Inspecting Browser Console Errors...")
    err_tool = BrowserGetConsoleErrorsTool(manager)
    res_err = err_tool.execute({})
    err_list = res_err.details.get("errors", []) if isinstance(res_err.details, dict) else []
    print(f"  Console Errors Count: {len(err_list)}")
    results["step17_console_errors_count"] = len(err_list)

    # 18. Network Failures Inspection
    print("\n[Step 18] Inspecting Network Failures...")
    net_tool = BrowserGetNetworkFailuresTool(manager)
    res_net = net_tool.execute({})
    net_list = res_net.details.get("failures", []) if isinstance(res_net.details, dict) else []
    print(f"  Network Failures Count: {len(net_list)}")
    if net_list:
        print(f"  Failures: {net_list}")
    results["step18_network_failures_count"] = len(net_list)

    # Record Evidence
    evidence_path = ws_dir / "FINAL_REVIEW_BROWSER_EVIDENCE.json"
    evidence_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nFinal browser evidence written to: {evidence_path}")

    print("\n" + "=" * 70)
    print("FINAL BROWSER VERIFICATION SUMMARY:")
    print("=" * 70)
    for k, v in results.items():
        print(f"  {k:35s}: {v}")

    return results

if __name__ == "__main__":
    run_browser_verification()
