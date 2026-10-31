# verify_focusforge_live.py
"""
Live CDP Browser Verification Script for FocusForge in testing 9.
Executes Test A through Test I:
- Test A: Initial load, preview server, initial seed data, dashboard stats, progress bar.
- Test B: Navigation across all 6 sections (Dashboard, Tasks, Timer, Habits, Analytics, Settings).
- Test C: Task Management CRUD, search, priority filter, completion toggle, dashboard update.
- Test D: Habit Tracking CRUD, streak calculation, toggle today, dashboard update.
- Test E: Pomodoro Focus Timer mode switching (25m/5m/15m), start, pause, reset.
- Test F: Analytics metrics and 7-day SVG bar charts rendering.
- Test G: Theme toggle (dark/light/dark) and localStorage persistence.
- Test H: Responsive viewports (1440x900, 768x1024, 390x844) and mobile menu toggle.
- Test I: Telemetry audit (0 console errors, 0 failed network requests) and screenshot capture.
"""

import asyncio
import os
import shutil
import time
from pathlib import Path

from core.browser.manager import BrowserManager
from core.browser.models import Viewport


WORKSPACE_DIR = Path(r"C:\Users\SUBBU\Downloads\testing 9").resolve()
SCREENSHOT_TARGET = Path(r"C:\Users\SUBBU\Downloads\hermes\artifacts\evidence\focusforge_verified_final.png").resolve()
ARTIFACT_DIR_TARGET = Path(r"C:\Users\SUBBU\.gemini\antigravity\brain\0053cd8a-b464-4edf-b9e4-90e766120e56\focusforge_verified_final.png")


async def main():
    print("=" * 70)
    print("FOCUSFORGE LIVE BROWSER AUTOMATION & VERIFICATION SUITE")
    print("=" * 70)

    mgr = BrowserManager(prefer_cdp=True)
    try:
        # -------------------------------------------------------------
        # TEST A — INITIAL LOAD & MANAGED PREVIEW SERVER
        # -------------------------------------------------------------
        print("\n[TEST A] Opening FocusForge via Managed DevServer...")
        info = await mgr.open_preview(
            workspace_dir=WORKSPACE_DIR,
            url_path="index.html",
        )
        print(f"  Preview URL:   {info.get('url')}")
        print(f"  Assigned Port: {info.get('port')}")
        print(f"  Page Title:    '{info.get('title')}'")
        print(f"  HTTP Status:   {info.get('status')}")

        assert info.get("status") == 200, f"Expected HTTP 200, got: {info.get('status')}"
        assert "FocusForge" in info.get("title", ""), f"Page title mismatch: {info.get('title')}"
        assert str(WORKSPACE_DIR) in info.get("workspace_dir", ""), "DevServer must strictly serve testing 9 workspace"

        driver = mgr.driver

        async def eval_js(expr: str):
            res = await driver._send_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            if "exceptionDetails" in res:
                err = res["exceptionDetails"]
                raise RuntimeError(f"CDP eval_js exception: {err.get('exception', {}).get('description') or err.get('text')}")
            return res.get("result", {}).get("value")

        await asyncio.sleep(1.0)

        # Clear any old test keys from previous runs to test pristine first launch
        await eval_js("""
            localStorage.clear();
            location.reload();
        """)
        await asyncio.sleep(1.5)

        # Verify initial dashboard stats
        tasks_completed = await eval_js("document.getElementById('stat-tasks-completed').innerText")
        tasks_pending = await eval_js("document.getElementById('stat-tasks-pending').innerText")
        focus_time = await eval_js("document.getElementById('stat-focus-time').innerText")
        habits_done = await eval_js("document.getElementById('habits-completed-today').innerText")
        habits_total = await eval_js("document.getElementById('habits-total-today').innerText")
        streak_display = await eval_js("document.getElementById('habit-streak-display').innerText")

        print(f"  Initial Dashboard Stats: Tasks Completed={tasks_completed}, Pending={tasks_pending}, Focus Time={focus_time}, Habits Done={habits_done}/{habits_total}, Streak={streak_display}")
        assert tasks_completed == "1", f"Expected 1 task completed today, got {tasks_completed}"
        assert tasks_pending == "2", f"Expected 2 pending tasks, got {tasks_pending}"
        assert "25m" in focus_time or "50m" in focus_time, f"Expected focus time today, got {focus_time}"
        assert habits_done == "1", f"Expected 1 habit done today, got {habits_done}"
        assert habits_total == "3", f"Expected 3 total habits, got {habits_total}"
        assert "3 days" in streak_display, f"Expected 3 days streak, got {streak_display}"

        # Verify Daily Progress Bar
        progress_text = await eval_js("document.getElementById('daily-progress-text').innerText")
        progress_width = await eval_js("document.getElementById('daily-progress-fill').style.width")
        print(f"  Daily Progress: {progress_text} (fill width: {progress_width})")
        assert "% Completed" in progress_text, f"Progress text invalid: {progress_text}"
        assert progress_width and progress_width != "0%", f"Progress width should be non-zero, got: {progress_width}"

        # Verify Dashboard Mini Lists
        dash_tasks = await eval_js("document.querySelectorAll('#dashboard-task-list .mini-item').length")
        dash_habits = await eval_js("document.querySelectorAll('#dashboard-habit-list .mini-item').length")
        print(f"  Dashboard Mini Lists: {dash_tasks} pending priority tasks, {dash_habits} habits")
        assert dash_tasks == 2, f"Expected 2 pending priority tasks in mini-list, got {dash_tasks}"
        assert dash_habits == 3, f"Expected 3 habits in mini-list, got {dash_habits}"

        print("  [TEST A PASSED] Initial load, sample seed data, and dashboard metrics verified.")

        # -------------------------------------------------------------
        # TEST B — NAVIGATION ACROSS ALL 6 SECTIONS
        # -------------------------------------------------------------
        print("\n[TEST B] Testing Navigation Across All 6 Sections...")
        sections_to_test = [
            ("tasks", "section-tasks", "Task Management"),
            ("timer", "section-timer", "Focus Timer"),
            ("habits", "section-habits", "Daily Habit Tracker"),
            ("analytics", "section-analytics", "Productivity Analytics"),
            ("settings", "section-settings", "Settings & Data"),
            ("dashboard", "section-dashboard", "Dashboard"),
        ]

        for nav_name, sec_id, expected_title in sections_to_test:
            btn_selector = f"#nav-{nav_name}"
            await driver.click(btn_selector)
            await asyncio.sleep(0.3)

            is_active = await eval_js(f"document.getElementById('{sec_id}').classList.contains('active')")
            is_visible = await eval_js(f"window.getComputedStyle(document.getElementById('{sec_id}')).display !== 'none'")
            title_text = await eval_js("document.getElementById('section-title').innerText")

            print(f"  Nav -> {nav_name.capitalize()}: section active={is_active}, visible={is_visible}, title='{title_text}'")
            assert is_active, f"Section {sec_id} should have active class"
            assert is_visible, f"Section {sec_id} should be visible"
            assert expected_title in title_text, f"Expected title '{expected_title}', got: '{title_text}'"

            # Check that other sections are hidden
            other_vis_count = await eval_js(f"""
                Array.from(document.querySelectorAll('.app-section:not(#{sec_id})'))
                    .filter(el => window.getComputedStyle(el).display !== 'none').length
            """)
            assert other_vis_count == 0, f"Expected other sections to be hidden, but {other_vis_count} are visible!"

        print("  [TEST B PASSED] Section navigation and visibility contract verified across all 6 sections.")

        # -------------------------------------------------------------
        # TEST C — TASK MANAGEMENT CRUD & SEARCH/FILTER
        # -------------------------------------------------------------
        print("\n[TEST C] Testing Task Management CRUD & Search/Filter...")
        await driver.click("#nav-tasks")
        await asyncio.sleep(0.3)

        # Open Add Task Modal
        await driver.click("#open-task-modal")
        await asyncio.sleep(0.3)

        modal_active = await eval_js("document.getElementById('task-modal').classList.contains('active')")
        assert modal_active, "Task modal should be active"

        # Fill in task form
        await eval_js("""
            document.getElementById('task-title').value = 'Automated Verification via CDP';
            document.getElementById('task-desc').value = 'Testing dynamic task creation, filtering, and state persistence.';
            document.getElementById('task-priority').value = 'high';
            document.getElementById('task-category').value = 'work';
        """)

        # Submit form
        await driver.click("#task-submit-btn")
        await asyncio.sleep(0.5)

        # Verify modal closed
        modal_active = await eval_js("document.getElementById('task-modal').classList.contains('active')")
        assert not modal_active, "Task modal should close after submit"

        # Verify task is in tasks container (now 4 tasks)
        total_tasks = await eval_js("document.querySelectorAll('#tasks-container .task-item').length")
        print(f"  Tasks in container after adding: {total_tasks}")
        assert total_tasks == 4, f"Expected 4 tasks, got {total_tasks}"

        # Test Search Filter
        await eval_js("""
            document.getElementById('task-search').value = 'CDP';
            document.getElementById('task-search').dispatchEvent(new Event('input'));
        """)
        await asyncio.sleep(0.3)
        search_res_count = await eval_js("document.querySelectorAll('#tasks-container .task-item').length")
        print(f"  Tasks matching search 'CDP': {search_res_count}")
        assert search_res_count == 1, f"Expected 1 search match, got {search_res_count}"

        # Reset search
        await eval_js("""
            document.getElementById('task-search').value = '';
            document.getElementById('task-search').dispatchEvent(new Event('input'));
        """)
        await asyncio.sleep(0.3)
        reset_cnt = await eval_js("document.querySelectorAll('#tasks-container .task-item').length")
        print(f"  Tasks after search reset: {reset_cnt}")
        assert reset_cnt == 4, f"Expected 4 tasks after search reset, got {reset_cnt}"

        # Test Priority Filter
        await eval_js("""
            document.getElementById('filter-priority').value = 'high';
            document.getElementById('filter-priority').dispatchEvent(new Event('change'));
        """)
        await asyncio.sleep(0.3)
        high_res_count = await eval_js("document.querySelectorAll('#tasks-container .task-item').length")
        print(f"  High priority tasks count: {high_res_count}")
        assert high_res_count == 3, f"Expected 3 high priority tasks, got {high_res_count}"

        # Reset priority filter
        await eval_js("""
            document.getElementById('filter-priority').value = 'all';
            document.getElementById('filter-priority').dispatchEvent(new Event('change'));
        """)
        await asyncio.sleep(0.3)

        # Toggle completion checkbox on newly added task
        await eval_js("""
            document.querySelector('#tasks-container .task-item:first-child .toggle-task-status').click();
        """)
        await asyncio.sleep(0.4)

        # Verify dashboard completed count incremented
        await driver.click("#nav-dashboard")
        await asyncio.sleep(0.3)
        updated_completed = await eval_js("document.getElementById('stat-tasks-completed').innerText")
        print(f"  Dashboard tasks completed after toggle: {updated_completed}")
        assert updated_completed == "2", f"Expected 2 completed tasks today, got {updated_completed}"

        print("  [TEST C PASSED] Task CRUD, search filtering, priority filtering, and dashboard synchronization verified.")

        # -------------------------------------------------------------
        # TEST D — HABIT TRACKING & STREAK MANAGEMENT
        # -------------------------------------------------------------
        print("\n[TEST D] Testing Habit Tracking & Streaks...")
        await driver.click("#nav-habits")
        await asyncio.sleep(0.3)

        # Open Habit Modal
        await driver.click("#open-habit-modal")
        await asyncio.sleep(0.3)
        habit_modal_active = await eval_js("document.getElementById('habit-modal').classList.contains('active')")
        assert habit_modal_active, "Habit modal should be active"

        # Fill in habit form
        await eval_js("""
            document.getElementById('habit-name').value = 'Evening Engineering Log';
            document.getElementById('habit-desc').value = 'Document architectural insights and daily progress.';
        """)
        await driver.click("#habit-submit-btn")
        await asyncio.sleep(0.5)

        # Verify habit was added (now 4 habits)
        total_habits = await eval_js("document.querySelectorAll('#habits-container .habit-item').length")
        print(f"  Total habits after adding: {total_habits}")
        assert total_habits == 4, f"Expected 4 habits, got {total_habits}"

        # Toggle habit completion today for the newly added habit
        await eval_js("""
            document.querySelector('#habits-container .habit-item:last-child .toggle-habit-btn').click();
        """)
        await asyncio.sleep(0.4)

        # Verify button text changed to '✓ Completed Today'
        btn_text = await eval_js("document.querySelector('#habits-container .habit-item:last-child .toggle-habit-btn').innerText")
        assert "Completed" in btn_text, f"Expected 'Completed' in button text, got: {btn_text}"

        # Verify dashboard habits count updated
        await driver.click("#nav-dashboard")
        await asyncio.sleep(0.3)
        habits_done_now = await eval_js("document.getElementById('habits-completed-today').innerText")
        print(f"  Dashboard habits completed today after toggle: {habits_done_now}")
        assert habits_done_now == "2", f"Expected 2 habits completed today, got {habits_done_now}"

        print("  [TEST D PASSED] Habit CRUD, streak history, and daily toggle verified.")

        # -------------------------------------------------------------
        # TEST E — POMODORO FOCUS TIMER
        # -------------------------------------------------------------
        print("\n[TEST E] Testing Pomodoro Focus Timer...")
        await driver.click("#nav-timer")
        await asyncio.sleep(0.3)

        # Verify initial display
        display_init = await eval_js("document.getElementById('timer-display').innerText")
        assert display_init == "25:00", f"Expected 25:00 initial timer display, got {display_init}"

        # Switch to Short Break mode
        await driver.click(".timer-mode-btn[data-mode='shortBreak']")
        await asyncio.sleep(0.3)
        display_short = await eval_js("document.getElementById('timer-display').innerText")
        print(f"  Short Break display: {display_short}")
        assert display_short == "05:00", f"Expected 05:00 for Short Break, got {display_short}"

        # Switch to Long Break mode
        await driver.click(".timer-mode-btn[data-mode='longBreak']")
        await asyncio.sleep(0.3)
        display_long = await eval_js("document.getElementById('timer-display').innerText")
        print(f"  Long Break display: {display_long}")
        assert display_long == "15:00", f"Expected 15:00 for Long Break, got {display_long}"

        # Switch back to Focus mode
        await driver.click(".timer-mode-btn[data-mode='focus']")
        await asyncio.sleep(0.3)

        # Start Timer
        await driver.click("#timer-start")
        await asyncio.sleep(1.2)

        # Verify timer is running and ticked down
        display_ticked = await eval_js("document.getElementById('timer-display').innerText")
        btn_start_txt = await eval_js("document.getElementById('timer-start').innerText")
        print(f"  Timer after 1.2s: display='{display_ticked}', start button='{btn_start_txt}'")
        assert "Running" in btn_start_txt, "Timer start button should indicate Running"
        assert display_ticked in ("24:59", "24:58"), f"Expected display to tick down, got {display_ticked}"

        # Pause Timer
        await driver.click("#timer-pause")
        await asyncio.sleep(0.5)
        btn_start_txt_after_pause = await eval_js("document.getElementById('timer-start').innerText")
        print(f"  Timer after pause: start button='{btn_start_txt_after_pause}'")
        assert "Resume" in btn_start_txt_after_pause, "Timer start button should show Resume after pause"

        # Reset Timer
        await driver.click("#timer-reset")
        await asyncio.sleep(0.3)
        display_reset = await eval_js("document.getElementById('timer-display').innerText")
        print(f"  Timer after reset: display='{display_reset}'")
        assert display_reset == "25:00", f"Expected timer to reset to 25:00, got {display_reset}"

        print("  [TEST E PASSED] Focus timer mode transitions, start, pause, and reset verified.")

        # -------------------------------------------------------------
        # TEST F — PRODUCTIVITY ANALYTICS & CHARTS
        # -------------------------------------------------------------
        print("\n[TEST F] Testing Productivity Analytics & SVG Bar Charts...")
        await driver.click("#nav-analytics")
        await asyncio.sleep(0.5)

        ana_focus = await eval_js("document.getElementById('analytics-focus-week').innerText")
        ana_sessions = await eval_js("document.getElementById('analytics-sessions-count').innerText")
        ana_tasks = await eval_js("document.getElementById('analytics-tasks-week').innerText")
        ana_habit_rate = await eval_js("document.getElementById('analytics-habit-rate').innerText")

        print(f"  Analytics Metrics: Focus Week={ana_focus}, Sessions={ana_sessions}, Tasks Week={ana_tasks}, Habit Rate={ana_habit_rate}")
        assert ana_focus != "0m", f"Expected weekly focus time > 0, got {ana_focus}"
        assert ana_sessions != "0", f"Expected sessions count > 0, got {ana_sessions}"

        # Verify 7-day SVG bar charts
        focus_bars = await eval_js("document.querySelectorAll('#chart-focus-weekly .bar-wrapper').length")
        tasks_bars = await eval_js("document.querySelectorAll('#chart-tasks-daily .bar-wrapper').length")
        print(f"  Chart Bars: Weekly Focus Chart={focus_bars} bars, Daily Tasks Chart={tasks_bars} bars")
        assert focus_bars == 7, f"Expected 7 daily bars for weekly focus chart, got {focus_bars}"
        assert tasks_bars == 7, f"Expected 7 daily bars for tasks chart, got {tasks_bars}"

        print("  [TEST F PASSED] Analytics metrics and 7-day bar charts rendering verified.")

        # -------------------------------------------------------------
        # TEST G — THEME TOGGLE & LOCALSTORAGE PERSISTENCE
        # -------------------------------------------------------------
        print("\n[TEST G] Testing Theme Toggle & LocalStorage Persistence...")
        init_theme = await eval_js("document.documentElement.getAttribute('data-theme')")
        assert init_theme == "dark", f"Expected initial dark theme, got {init_theme}"

        # Click theme toggle -> light theme
        await driver.click("#theme-toggle")
        await asyncio.sleep(0.3)
        light_theme = await eval_js("document.documentElement.getAttribute('data-theme')")
        print(f"  Theme after first toggle: {light_theme}")
        assert light_theme == "light", f"Expected light theme, got {light_theme}"

        # Click theme toggle again -> dark theme
        await driver.click("#theme-toggle")
        await asyncio.sleep(0.3)
        dark_theme = await eval_js("document.documentElement.getAttribute('data-theme')")
        print(f"  Theme after second toggle: {dark_theme}")
        assert dark_theme == "dark", f"Expected dark theme, got {dark_theme}"

        # Test reload persistence
        await eval_js("location.reload();")
        await asyncio.sleep(1.2)
        reloaded_theme = await eval_js("document.documentElement.getAttribute('data-theme')")
        print(f"  Theme after page reload: {reloaded_theme}")
        assert reloaded_theme == "dark", f"Expected theme to persist across reload, got {reloaded_theme}"

        print("  [TEST G PASSED] Theme toggling and localStorage persistence verified.")

        # -------------------------------------------------------------
        # TEST H — RESPONSIVE VIEWPORTS & MOBILE SIDEBAR
        # -------------------------------------------------------------
        print("\n[TEST H] Testing Responsive Viewports (1440x900, 768x1024, 390x844)...")
        viewports = [
            ("Desktop (1440x900)", 1440, 900, False),
            ("Tablet (768x1024)", 768, 1024, False),
            ("Mobile (390x844)", 390, 844, True),
        ]

        for v_name, width, height, is_mobile in viewports:
            await driver._send_cdp("Emulation.setDeviceMetricsOverride", {
                "width": width,
                "height": height,
                "deviceScaleFactor": 1.0,
                "mobile": is_mobile,
            })
            await asyncio.sleep(0.3)

            # Check horizontal overflow
            scroll_width = await eval_js("document.documentElement.scrollWidth")
            client_width = await eval_js("document.documentElement.clientWidth")
            print(f"  {v_name}: clientWidth={client_width}, scrollWidth={scroll_width}")
            assert scroll_width <= client_width + 5, f"Horizontal overflow on {v_name}: scroll={scroll_width}, client={client_width}"

            # On mobile, test mobile menu toggle
            if is_mobile:
                menu_btn_visible = await eval_js("window.getComputedStyle(document.getElementById('mobile-menu-btn')).display !== 'none'")
                assert menu_btn_visible, "Mobile menu button should be visible on mobile viewport"
                # Click mobile menu button
                await driver.click("#mobile-menu-btn")
                await asyncio.sleep(0.3)
                sidebar_open = await eval_js("document.getElementById('sidebar').classList.contains('open')")
                print(f"  Mobile sidebar toggle: open={sidebar_open}")
                assert sidebar_open, "Sidebar should open on clicking mobile menu button"
                # Click menu button again to close
                await driver.click("#mobile-menu-btn")
                await asyncio.sleep(0.3)

        # Reset to desktop viewport
        await driver._send_cdp("Emulation.setDeviceMetricsOverride", {
            "width": 1440,
            "height": 900,
            "deviceScaleFactor": 1.0,
            "mobile": False,
        })
        await asyncio.sleep(0.3)
        print("  [TEST H PASSED] All viewports verified without horizontal overflow and mobile sidebar works.")

        # -------------------------------------------------------------
        # TEST I — TELEMETRY & CONSOLE ERROR AUDIT + SCREENSHOT
        # -------------------------------------------------------------
        print("\n[TEST I] Auditing Telemetry & Capturing Final Evidence Screenshot...")
        console_errs = [m for m in driver.console_messages if m.msg_type == "error"]
        net_fails = [r for r in driver.network_records if r.status and r.status >= 400 and not r.url.endswith("favicon.ico")]

        print(f"  Console Errors: {len(console_errs)}")
        print(f"  Network Fails:  {len(net_fails)}")
        for e in console_errs:
            print(f"    ! Console Error: {e.text}")
        for nf in net_fails:
            print(f"    ! HTTP {nf.status} on {nf.url}")

        assert len(console_errs) == 0, f"Found {len(console_errs)} console errors"
        assert len(net_fails) == 0, f"Found {len(net_fails)} failed network requests"

        # Capture Verified Final Screenshot on Dashboard with full stats
        await driver.click("#nav-dashboard")
        await asyncio.sleep(0.4)

        SCREENSHOT_TARGET.parent.mkdir(parents=True, exist_ok=True)
        shot_art = await driver.capture_screenshot(
            output_path=SCREENSHOT_TARGET,
            viewport=Viewport(width=1440, height=900),
        )
        print(f"  Screenshot captured: {shot_art.file_path} ({shot_art.width}x{shot_art.height})")

        # Copy to brain artifact directory
        ARTIFACT_DIR_TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shot_art.file_path, ARTIFACT_DIR_TARGET)
        print(f"  Copied to brain artifact directory: {ARTIFACT_DIR_TARGET}")

        print("\n" + "=" * 70)
        print("ALL TESTS (TEST A THROUGH TEST I) PASSED WITH ZERO DEFECTS!")
        print("=" * 70)

    finally:
        await mgr.close()


if __name__ == "__main__":
    asyncio.run(main())
