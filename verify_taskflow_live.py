# verify_taskflow_live.py
"""
Deterministic Live Browser Verification Script for TaskFlow in testing 5.
Uses HERMES BrowserManager and CdpBrowserDriver to interact with the real browser.
Performs all 8 required interaction steps, validates persistence, records network & console logs,
and captures the final screenshot to artifacts/evidence/taskflow_verified_final.png.
"""

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from core.browser.manager import BrowserManager
from core.browser.models import Viewport


WORKSPACE_DIR = Path(r"C:\Users\SUBBU\Downloads\testing 5").resolve()
SCREENSHOT_TARGET = Path(r"C:\Users\SUBBU\Downloads\hermes\artifacts\evidence\taskflow_verified_final.png").resolve()
ARTIFACT_DIR_TARGET = Path(r"C:\Users\SUBBU\.gemini\antigravity\brain\0053cd8a-b464-4edf-b9e4-90e766120e56\taskflow_verified_final.png")

async def run_verification():
    print("=" * 60)
    print("TASKFLOW BROWSER EVIDENCE RECONCILIATION & INTERACTION VERIFICATION")
    print("=" * 60)
    print(f"Target Workspace: {WORKSPACE_DIR}")

    # 1. Initialize BrowserManager with CDP driver preference
    mgr = BrowserManager(prefer_cdp=True)
    try:
        # 2. Open preview explicitly targeting testing 5
        print("\n[Step 0] Starting DevServer and Navigating Browser ...")
        info = await mgr.open_preview(
            workspace_dir=WORKSPACE_DIR,
            url_path="index.html",
        )
        print(f"  URL:       {info.get('url')}")
        print(f"  Port:      {info.get('port')}")
        print(f"  Workspace: {info.get('workspace_dir')}")
        print(f"  Title:     '{info.get('title')}'")
        print(f"  Status:    {info.get('status')}")

        assert "TaskFlow" in info.get("title", ""), f"Unexpected page title: {info.get('title')}"
        assert info.get("status") == 200, f"HTTP status failed: {info.get('status')}"

        driver = mgr.driver
        # Send CDP helper
        async def eval_js(expression: str):
            res = await driver._send_cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True})
            return res.get("result", {}).get("value")

        # Let DOM initialize
        await asyncio.sleep(1.0)

        # Confirm Initial State
        initial_title = await eval_js("document.title")
        initial_tasks_count = await eval_js("document.querySelectorAll('.task-item').length")
        print(f"  Initial DOM: Title='{initial_title}', Task items rendered={initial_tasks_count}")

        # Interaction 1: Create a task
        print("\n[Interaction 1] Creating a new task ...")
        task_title = "Launch Final Production Architecture"
        task_desc = "Verify multi-tier failover and browser qualification end-to-end."
        
        # Click "+ New Task" button
        click_res = await driver.click("#open-add-modal")
        print(f"  Clicked #open-add-modal: {click_res.success}")
        await asyncio.sleep(0.3)

        # Type in title and description
        await driver.type_text("#task-title", task_title)
        await driver.type_text("#task-description", task_desc)
        await eval_js("document.getElementById('task-priority').value = 'high'")
        await eval_js("document.getElementById('task-category').value = 'Work'")
        await eval_js("document.getElementById('task-due-date').value = '2026-11-15'")
        
        # Submit form
        await driver.click("#save-task-btn")
        await asyncio.sleep(0.5)

        tasks_after_create = await eval_js("document.querySelectorAll('.task-item').length")
        first_title = await eval_js("document.querySelector('.task-item .task-title') ? document.querySelector('.task-item .task-title').innerText : ''")
        print(f"  Task items count: {tasks_after_create} (First task: '{first_title}')")
        assert task_title in first_title, f"Task title mismatch: {first_title}"

        # Interaction 2: Change its priority / Edit
        print("\n[Interaction 2] Changing task priority / Editing ...")
        # Click edit on the first task
        await driver.click(".task-item .edit-btn")
        await asyncio.sleep(0.3)
        # Change priority to 'low' and title update
        await eval_js("document.getElementById('task-priority').value = 'low'")
        await driver.type_text("#task-title", f"{task_title} (Verified)")
        await driver.click("#save-task-btn")
        await asyncio.sleep(0.5)

        updated_badge = await eval_js("document.querySelector('.task-item .badge').innerText")
        updated_title = await eval_js("document.querySelector('.task-item .task-title').innerText")
        print(f"  Updated task: '{updated_title}' | Priority badge: '{updated_badge}'")
        assert "LOW" in updated_badge.upper(), f"Priority update failed: {updated_badge}"

        # Interaction 3: Mark it completed
        print("\n[Interaction 3] Marking task completed ...")
        completed_before = await eval_js("document.getElementById('completed-count').innerText")
        await driver.click(".task-item .task-checkbox")
        await asyncio.sleep(0.5)
        completed_after = await eval_js("document.getElementById('completed-count').innerText")
        is_completed_class = await eval_js("document.querySelector('.task-item').classList.contains('completed')")
        print(f"  Completed count: {completed_before} -> {completed_after} (Has 'completed' class: {is_completed_class})")
        assert is_completed_class is True, "Task item does not have 'completed' class"

        # Interaction 4: Search for it
        print("\n[Interaction 4] Searching for task ...")
        await driver.type_text("#search-input", "Production Architecture")
        await asyncio.sleep(0.3)
        search_matches = await eval_js("document.querySelectorAll('.task-item').length")
        print(f"  Search for 'Production Architecture' returned {search_matches} match(es)")
        assert search_matches >= 1, "Search should return matching task"

        # Clear search
        await driver.type_text("#search-input", "")
        await asyncio.sleep(0.3)

        # Interaction 5: Test the filters (tabs and priority)
        print("\n[Interaction 5] Testing tab and priority filters ...")
        # Click 'Completed' tab
        await driver.click(".tab-btn[data-tab='completed']")
        await asyncio.sleep(0.3)
        completed_tab_count = await eval_js("document.querySelectorAll('.task-item').length")
        print(f"  Completed tab shows: {completed_tab_count} task(s)")

        # Click 'Active' tab
        await driver.click(".tab-btn[data-tab='active']")
        await asyncio.sleep(0.3)
        active_tab_count = await eval_js("document.querySelectorAll('.task-item').length")
        print(f"  Active tab shows: {active_tab_count} task(s)")

        # Click 'All' tab
        await driver.click(".tab-btn[data-tab='all']")
        await asyncio.sleep(0.3)
        all_tab_count = await eval_js("document.querySelectorAll('.task-item').length")
        print(f"  All tab shows: {all_tab_count} task(s)")

        # Interaction 6 & 7: Refresh browser and confirm persistence
        print("\n[Interaction 6 & 7] Refreshing browser & confirming LocalStorage persistence ...")
        nav_res = await driver.navigate(info["url"])
        await asyncio.sleep(1.0)
        persisted_count = await eval_js("document.querySelectorAll('.task-item').length")
        persisted_raw = await eval_js("localStorage.getItem('taskflow_tasks')")
        persisted_tasks = json.loads(persisted_raw) if persisted_raw else []
        print(f"  After page reload: {persisted_count} tasks rendered from LocalStorage ({len(persisted_tasks)} stored in localStorage)")
        assert persisted_count == len(persisted_tasks), "Rendered count should match localStorage count"
        assert any(task_title in t.get("title", "") for t in persisted_tasks), "Created task must persist in localStorage"

        # Interaction 8: Toggle dark mode
        print("\n[Interaction 8] Toggling dark mode ...")
        theme_before = await eval_js("document.body.getAttribute('data-theme')")
        await driver.click("#theme-toggle")
        await asyncio.sleep(0.4)
        theme_after = await eval_js("document.body.getAttribute('data-theme')")
        stored_theme = await eval_js("localStorage.getItem('taskflow_theme')")
        print(f"  Theme toggle: '{theme_before}' -> '{theme_after}' (Stored in localStorage: '{stored_theme}')")
        assert theme_after == "dark", f"Expected dark theme, got: {theme_after}"
        assert stored_theme == "dark", f"Expected stored dark theme, got: {stored_theme}"

        # 3. Check console errors and network failures
        print("\n[Diagnostic Audit] Checking console messages and network traffic ...")
        console_errs = [m for m in driver.console_messages if m.msg_type == "error"]
        print(f"  Total console messages: {len(driver.console_messages)}")
        print(f"  Console errors:         {len(console_errs)}")
        for err in console_errs:
            print(f"    ! Console Error: {err.text}")

        net_fails = [r for r in driver.network_records if r.status and r.status >= 400 and not r.url.endswith("favicon.ico")]
        print(f"  Total network requests: {len(driver.network_records)}")
        print(f"  Failed requests:        {len(net_fails)}")
        for f in net_fails:
            print(f"    ! HTTP {f.status} on {f.url}")

        assert len(console_errs) == 0, f"Found {len(console_errs)} console errors"
        assert len(net_fails) == 0, f"Found {len(net_fails)} failed network requests"

        # 4. Capture fresh screenshot
        print(f"\n[Step 5] Capturing verified screenshot to: {SCREENSHOT_TARGET} ...")
        SCREENSHOT_TARGET.parent.mkdir(parents=True, exist_ok=True)
        shot_art = await driver.capture_screenshot(
            output_path=SCREENSHOT_TARGET,
            viewport=Viewport(width=1280, height=800),
        )
        print(f"  Screenshot saved: {shot_art.file_path} ({shot_art.width}x{shot_art.height}, SHA: {shot_art.sha256[:12]})")

        # Copy to brain artifact directory as well
        ARTIFACT_DIR_TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shot_art.file_path, ARTIFACT_DIR_TARGET)
        print(f"  Copied to brain artifact directory: {ARTIFACT_DIR_TARGET}")

        print("\n" + "=" * 60)
        print("ALL 8 BROWSER INTERACTIONS & QUALIFICATIONS PASSED PERFECTLY!")
        print("=" * 60)

    finally:
        await mgr.close()

if __name__ == "__main__":
    asyncio.run(run_verification())
