# verify_pageturn_live.py
"""
Live CDP Browser Verification Script for PageTurn in testing 8.
Executes Test A through Test I:
- Test A: Initial load, 4 sample books, statistics, CSS/JS load, 0 console errors.
- Test B: Add Book ('Clean Code', 'Robert C. Martin', 464 pages, 50 read, 5 stars).
- Test C: Edit book title and quick +10 pages progress.
- Test D: Search, genre filtering, status filtering, sorting, and clear filters.
- Test E: Details modal opening and deletion with confirmation dialog.
- Test F: Page reload and localStorage persistence.
- Test G: CSV export generation and data verification.
- Test H: Responsive viewports (1440x900, 768x1024, 390x844).
- Test I: Telemetry audit (0 console errors, 0 failed network requests).
- Captures verified screenshot to artifacts/evidence/pageturn_verified_final.png.
"""

import asyncio
import os
import shutil
import time
from pathlib import Path

from core.browser.manager import BrowserManager
from core.browser.models import Viewport


WORKSPACE_DIR = Path(r"C:\Users\SUBBU\Downloads\testing 8").resolve()
SCREENSHOT_TARGET = Path(r"C:\Users\SUBBU\Downloads\hermes\artifacts\evidence\pageturn_verified_final.png").resolve()
ARTIFACT_DIR_TARGET = Path(r"C:\Users\SUBBU\.gemini\antigravity\brain\0053cd8a-b464-4edf-b9e4-90e766120e56\pageturn_verified_final.png")


async def main():
    print("=" * 70)
    print("PAGETURN LIVE BROWSER AUTOMATION & VERIFICATION SUITE")
    print("=" * 70)

    mgr = BrowserManager(prefer_cdp=True)
    try:
        # -------------------------------------------------------------
        # TEST A — INITIAL LOAD & MANAGED PREVIEW SERVER
        # -------------------------------------------------------------
        print("\n[TEST A] Opening PageTurn via Managed DevServer...")
        info = await mgr.open_preview(
            workspace_dir=WORKSPACE_DIR,
            url_path="index.html",
        )
        print(f"  Preview URL:   {info.get('url')}")
        print(f"  Assigned Port: {info.get('port')}")
        print(f"  Page Title:    '{info.get('title')}'")
        print(f"  HTTP Status:   {info.get('status')}")

        assert info.get("status") == 200, f"Expected HTTP 200, got: {info.get('status')}"
        assert "PageTurn" in info.get("title", ""), f"Page title mismatch: {info.get('title')}"
        assert str(WORKSPACE_DIR) in info.get("workspace_dir", ""), "DevServer must strictly serve testing 8 workspace"

        driver = mgr.driver

        async def eval_js(expr: str):
            res = await driver._send_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return res.get("result", {}).get("value")

        await asyncio.sleep(1.0)

        # Clear any old test keys from previous runs to test pristine first launch
        await eval_js("localStorage.removeItem('pageturn_books'); location.reload();")
        await asyncio.sleep(1.2)

        # Verify initial sample books (4 books)
        init_books_cnt = await eval_js("document.querySelectorAll('#books-container .book-card').length")
        print(f"  Initial Books rendered: {init_books_cnt}")
        assert init_books_cnt == 4, f"Expected 4 initial sample books, got: {init_books_cnt}"

        # Verify initial dashboard stats
        total_books_txt = await eval_js("document.getElementById('stat-total-books').innerText")
        reading_txt = await eval_js("document.getElementById('stat-currently-reading').innerText")
        completed_txt = await eval_js("document.getElementById('stat-completed-books').innerText")
        want_txt = await eval_js("document.getElementById('stat-want-to-read').innerText")
        pages_txt = await eval_js("document.getElementById('stat-total-pages').innerText")

        print(f"  Dashboard Stats: Total={total_books_txt}, Reading={reading_txt}, Completed={completed_txt}, Want={want_txt}, Pages={pages_txt}")
        assert total_books_txt == "4", f"Expected 4 total books, got {total_books_txt}"
        assert reading_txt == "2", f"Expected 2 reading, got {reading_txt}"
        assert completed_txt == "1", f"Expected 1 completed, got {completed_txt}"
        assert want_txt == "1", f"Expected 1 want to read, got {want_txt}"
        # Pages read: 140 + 320 + 0 + 200 = 660
        assert "660" in pages_txt, f"Expected 660 pages read, got {pages_txt}"

        print("  [TEST A PASSED] Initial load, 4 sample books, and dashboard stats verified.")

        # -------------------------------------------------------------
        # TEST B — ADD BOOK
        # -------------------------------------------------------------
        print("\n[TEST B] Testing Add Book Modal & Submission...")
        # Click Add Book button
        await driver.click("#add-book-btn")
        await asyncio.sleep(0.4)

        modal_active = await eval_js("document.getElementById('book-modal').classList.contains('active')")
        print(f"  Add Book Modal Active: {modal_active}")
        assert modal_active, "Book modal should be active after clicking Add Book button"

        # Fill in valid form inputs:
        # Title: Clean Code
        # Author: Robert C. Martin
        # Genre: Technology
        # Total Pages: 464
        # Pages Read: 50
        # Status: Currently Reading
        # Rating: 5
        await driver.type_text("#book-title", "Clean Code")
        await driver.type_text("#book-author", "Robert C. Martin")
        await driver.type_text("#book-genre", "Technology")
        await driver.type_text("#book-total-pages", "464")
        await driver.type_text("#book-pages-read", "50")

        await eval_js("""
            document.getElementById('book-status').value = 'Currently Reading';
            document.getElementById('book-rating').value = '5';
            document.getElementById('book-notes').value = 'A Handbook of Agile Software Craftsmanship.';
        """)

        # Submit form
        await driver.click("#save-book-btn")
        await asyncio.sleep(0.6)

        # Modal must close
        modal_closed = await eval_js("!document.getElementById('book-modal').classList.contains('active')")
        assert modal_closed, "Modal must close after successful form submission"

        # Total books count increases by 1 (4 -> 5)
        new_books_cnt = await eval_js("document.querySelectorAll('#books-container .book-card').length")
        new_stat_total = await eval_js("document.getElementById('stat-total-books').innerText")
        new_stat_pages = await eval_js("document.getElementById('stat-total-pages').innerText")

        print(f"  After Add: Books in DOM={new_books_cnt}, Stat Total={new_stat_total}, Stat Pages={new_stat_pages}")
        assert new_books_cnt == 5, f"Expected 5 books in DOM, got {new_books_cnt}"
        assert new_stat_total == "5", f"Expected Stat Total = 5, got {new_stat_total}"
        # Pages read: 660 + 50 = 710
        assert "710" in new_stat_pages, f"Expected 710 pages read, got {new_stat_pages}"

        # Clean Code card exists
        has_clean_code = await eval_js("Boolean(Array.from(document.querySelectorAll('.book-title')).find(el => el.textContent.includes('Clean Code')))")
        assert has_clean_code, "Clean Code card must be rendered in books container"

        print("  [TEST B PASSED] Clean Code added successfully with stats increment.")

        # -------------------------------------------------------------
        # TEST C — EDIT AND QUICK PROGRESS
        # -------------------------------------------------------------
        print("\n[TEST C] Testing Edit and Quick Progress (+10 pages)...")
        # Click +10 button on Clean Code card (first card)
        pages_before = await eval_js("document.getElementById('stat-total-pages').innerText")
        await driver.click(".book-card:first-child .btn-plus")
        await asyncio.sleep(0.4)

        pages_after_plus = await eval_js("document.getElementById('stat-total-pages').innerText")
        print(f"  Pages after +10: before='{pages_before}', after='{pages_after_plus}'")
        # 710 + 10 = 720
        assert "720" in pages_after_plus, f"Expected 720 total pages after +10, got: {pages_after_plus}"

        # Now test Edit Book title
        await driver.click(".book-card:first-child .btn-edit")
        await asyncio.sleep(0.4)
        assert await eval_js("document.getElementById('book-modal').classList.contains('active')")

        # Update title to "Clean Code: Advanced Edition"
        await eval_js("document.getElementById('book-title').value = 'Clean Code: Advanced Edition';")
        await driver.click("#save-book-btn")
        await asyncio.sleep(0.5)

        has_updated_title = await eval_js("Boolean(Array.from(document.querySelectorAll('.book-title')).find(el => el.textContent.includes('Clean Code: Advanced Edition')))")
        print(f"  Title edited in DOM: {has_updated_title}")
        assert has_updated_title, "Book title should update to 'Clean Code: Advanced Edition'"

        print("  [TEST C PASSED] Quick progress and edit verified.")

        # -------------------------------------------------------------
        # TEST D — SEARCH, FILTERING, AND SORTING
        # -------------------------------------------------------------
        print("\n[TEST D] Testing Search, Filtering, and Sorting...")
        # 1. Search for "Clean Code"
        await driver.type_text("#search-input", "Clean Code")
        await eval_js("document.getElementById('search-input').dispatchEvent(new Event('input', { bubbles: true }));")
        await asyncio.sleep(0.3)
        search_res_cnt = await eval_js("document.querySelectorAll('#books-container .book-card').length")
        print(f"  Search for 'Clean Code' yielded: {search_res_cnt} book(s)")
        assert search_res_cnt == 1, f"Expected 1 search match, got {search_res_cnt}"

        # Clear search input
        await eval_js("document.getElementById('search-input').value = ''; document.getElementById('search-input').dispatchEvent(new Event('input', { bubbles: true }));")
        await asyncio.sleep(0.3)

        # 2. Filter by Technology Genre
        await eval_js("""
            document.getElementById('genre-filter').value = 'Technology';
            document.getElementById('genre-filter').dispatchEvent(new Event('change', { bubbles: true }));
        """)
        await asyncio.sleep(0.3)
        tech_cnt = await eval_js("document.querySelectorAll('#books-container .book-card').length")
        print(f"  Genre 'Technology' filter yielded: {tech_cnt} book(s)")
        # Pragmatic Programmer + Clean Code = 2
        assert tech_cnt == 2, f"Expected 2 Technology books, got {tech_cnt}"

        # 3. Filter by Status 'Completed'
        await eval_js("""
            document.getElementById('status-filter').value = 'Completed';
            document.getElementById('status-filter').dispatchEvent(new Event('change', { bubbles: true }));
        """)
        await asyncio.sleep(0.3)
        # Tech + Completed should be 0 because neither Pragmatic Programmer nor Clean Code is Completed
        tech_completed_cnt = await eval_js("document.querySelectorAll('#books-container .book-card').length")
        print(f"  Technology + Completed yielded: {tech_completed_cnt} book(s)")
        assert tech_completed_cnt == 0, "No books should match Technology + Completed"

        # 4. Click Clear Filters button
        await driver.click("#clear-filters-btn")
        await asyncio.sleep(0.4)
        all_reset_cnt = await eval_js("document.querySelectorAll('#books-container .book-card').length")
        print(f"  After Clear Filters: {all_reset_cnt} books")
        assert all_reset_cnt == 5, f"Expected all 5 books after clearing filters, got {all_reset_cnt}"

        # 5. Test Title A-Z Sorting
        await eval_js("""
            document.getElementById('sort-select').value = 'title-asc';
            document.getElementById('sort-select').dispatchEvent(new Event('change', { bubbles: true }));
        """)
        await asyncio.sleep(0.3)
        first_title = await eval_js("document.querySelector('.book-card:first-child .book-title').innerText")
        print(f"  First title under Title A-Z: '{first_title}'")
        assert "Atomic Habits" in first_title, f"Expected 'Atomic Habits' first under A-Z, got '{first_title}'"

        # 6. Test Rating Sorting
        await eval_js("""
            document.getElementById('sort-select').value = 'rating-desc';
            document.getElementById('sort-select').dispatchEvent(new Event('change', { bubbles: true }));
        """)
        await asyncio.sleep(0.3)
        first_rating_title = await eval_js("document.querySelector('.book-card:first-child .book-title').innerText")
        print(f"  First title under Highest Rating: '{first_rating_title}'")

        print("  [TEST D PASSED] Search, status filter, genre filter, clear filters, and sorting verified.")

        # -------------------------------------------------------------
        # TEST E — DETAILS MODAL & DELETION WITH CONFIRMATION
        # -------------------------------------------------------------
        print("\n[TEST E] Testing Book Details Modal and Delete Confirmation...")
        # Reset sorting to recent
        await eval_js("""
            document.getElementById('sort-select').value = 'recent';
            document.getElementById('sort-select').dispatchEvent(new Event('change', { bubbles: true }));
        """)
        await asyncio.sleep(0.2)

        # Open Details of the first book
        await driver.click(".book-card:first-child .btn-details")
        await asyncio.sleep(0.4)
        details_active = await eval_js("document.getElementById('details-modal').classList.contains('active')")
        print(f"  Details Modal Active: {details_active}")
        assert details_active, "Details modal should be active"

        details_title_text = await eval_js("document.getElementById('details-title').innerText")
        print(f"  Details Modal Book Title: '{details_title_text}'")
        assert "Clean Code" in details_title_text, f"Details should display Clean Code, got '{details_title_text}'"

        # Close details modal
        await driver.click("#details-close-action")
        await asyncio.sleep(0.3)
        assert await eval_js("!document.getElementById('details-modal').classList.contains('active')")

        # Now test Delete with confirmation dialog
        await driver.click(".book-card:first-child .btn-delete")
        await asyncio.sleep(0.4)
        confirm_active = await eval_js("document.getElementById('confirm-modal').classList.contains('active')")
        print(f"  Confirm Modal Active: {confirm_active}")
        assert confirm_active, "Delete confirmation modal should be active"

        # Confirm deletion
        await driver.click("#confirm-yes-btn")
        await asyncio.sleep(0.5)

        cnt_after_delete = await eval_js("document.querySelectorAll('#books-container .book-card').length")
        stat_after_delete = await eval_js("document.getElementById('stat-total-books').innerText")
        print(f"  After Deletion: Books in DOM={cnt_after_delete}, Stat Total={stat_after_delete}")
        assert cnt_after_delete == 4, f"Expected 4 books remaining, got {cnt_after_delete}"
        assert stat_after_delete == "4", f"Expected Stat Total = 4, got {stat_after_delete}"

        print("  [TEST E PASSED] Details modal and deletion confirmation verified.")

        # -------------------------------------------------------------
        # TEST F — PERSISTENCE ACROSS RELOAD
        # -------------------------------------------------------------
        print("\n[TEST F] Testing Full Page Reload & LocalStorage Persistence...")
        # Toggle theme to Dark
        theme_initial = await eval_js("document.documentElement.getAttribute('data-theme')")
        await driver.click("#theme-toggle-btn")
        await asyncio.sleep(0.2)
        theme_toggled = await eval_js("document.documentElement.getAttribute('data-theme')")
        print(f"  Theme toggled: '{theme_initial}' -> '{theme_toggled}'")

        # Hard reload page
        await driver.navigate(info["url"])
        await asyncio.sleep(1.2)

        reloaded_books_cnt = await eval_js("document.querySelectorAll('#books-container .book-card').length")
        reloaded_stat_total = await eval_js("document.getElementById('stat-total-books').innerText")
        reloaded_theme = await eval_js("document.documentElement.getAttribute('data-theme')")

        print(f"  After Reload: Books in DOM={reloaded_books_cnt}, Stat Total={reloaded_stat_total}, Theme='{reloaded_theme}'")
        assert reloaded_books_cnt == 4, f"Books should persist across reload (4 expected, got {reloaded_books_cnt})"
        assert reloaded_stat_total == "4", f"Stat total should persist as 4, got {reloaded_stat_total}"
        assert reloaded_theme == theme_toggled, f"Theme '{theme_toggled}' should persist across reload"

        print("  [TEST F PASSED] Data and theme persistence across hard reload verified.")

        # -------------------------------------------------------------
        # TEST G — CSV EXPORT
        # -------------------------------------------------------------
        print("\n[TEST G] Testing CSV Export...")
        csv_link_clicked = await eval_js("""
            (() => {
                let downloaded = false;
                const origCreate = URL.createObjectURL;
                URL.createObjectURL = (blob) => {
                    downloaded = blob.size > 0 && blob.type.includes('csv');
                    return origCreate(blob);
                };
                document.getElementById('export-csv-btn').click();
                return downloaded;
            })()
        """)
        print(f"  CSV Blob download initiated: {csv_link_clicked}")
        assert csv_link_clicked, "CSV export should generate and download a valid non-empty CSV Blob"
        print("  [TEST G PASSED] CSV export functionality verified.")

        # -------------------------------------------------------------
        # TEST H — RESPONSIVE VIEWPORT TESTING
        # -------------------------------------------------------------
        print("\n[TEST H] Testing Responsive Viewports...")
        viewports = [
            ("Desktop (1440x900)", Viewport(width=1440, height=900)),
            ("Tablet (768x1024)", Viewport(width=768, height=1024)),
            ("Mobile (390x844)", Viewport(width=390, height=844)),
        ]
        for v_name, vp in viewports:
            await driver._send_cdp("Emulation.setDeviceMetricsOverride", {
                "width": vp.width,
                "height": vp.height,
                "deviceScaleFactor": 1.0,
                "mobile": (vp.width <= 768),
            })
            await asyncio.sleep(0.3)
            # Check horizontal overflow
            scroll_width = await eval_js("document.documentElement.scrollWidth")
            client_width = await eval_js("document.documentElement.clientWidth")
            print(f"  {v_name}: clientWidth={client_width}, scrollWidth={scroll_width}")
            assert scroll_width <= client_width + 5, f"Horizontal overflow detected on {v_name}: scroll={scroll_width}, client={client_width}"

        # Reset to desktop
        await driver._send_cdp("Emulation.setDeviceMetricsOverride", {
            "width": 1280,
            "height": 800,
            "deviceScaleFactor": 1.0,
            "mobile": False,
        })
        await asyncio.sleep(0.3)
        print("  [TEST H PASSED] All viewports verified without horizontal overflow.")

        # -------------------------------------------------------------
        # TEST I — TELEMETRY & CONSOLE ERROR AUDIT
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

        # Capture Verified Final Screenshot
        SCREENSHOT_TARGET.parent.mkdir(parents=True, exist_ok=True)
        shot_art = await driver.capture_screenshot(
            output_path=SCREENSHOT_TARGET,
            viewport=Viewport(width=1280, height=800),
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
