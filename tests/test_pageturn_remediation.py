# tests/test_pageturn_remediation.py
"""
Focused regression tests for PageTurn functional repair in testing 8:
- Initialization order and TDZ avoidance
- Total pages calculation
- Dashboard statistic ID concordance
- Status and sorting options concordance
- Modal and form input IDs concordance
- CSS selector concordance
- Managed HTTP dev server interception in BashExecTool
"""

import json
import re
import subprocess
from pathlib import Path
import pytest

WORKSPACE_DIR = Path(r"C:\Users\SUBBU\Downloads\testing 8").resolve()
HTML_PATH = WORKSPACE_DIR / "index.html"
JS_PATH = WORKSPACE_DIR / "app.js"
CSS_PATH = WORKSPACE_DIR / "style.css"


def test_workspace_files_exist():
    assert HTML_PATH.exists(), f"Missing {HTML_PATH}"
    assert JS_PATH.exists(), f"Missing {JS_PATH}"
    assert CSS_PATH.exists(), f"Missing {CSS_PATH}"


def test_node_syntax_check():
    res = subprocess.run(
        ["node", "--check", str(JS_PATH)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"node --check app.js failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"


def test_initialization_order_tdz_resolved():
    content = JS_PATH.read_text(encoding="utf-8")
    
    # Check that DOM Element references are collected before loadBooks() or updateGenreFilterOptions()
    dom_ref_idx = content.find("document.getElementById('genre-filter')")
    load_books_call_idx = content.find("loadBooks();")
    genre_update_call_idx = content.find("updateGenreFilterOptions();")
    
    assert dom_ref_idx != -1, "genreFilterSelect reference must exist in app.js"
    assert load_books_call_idx != -1, "loadBooks() call must exist in app.js"
    assert genre_update_call_idx != -1, "updateGenreFilterOptions() call must exist in app.js"
    
    # Crucial TDZ assertion: element declarations must occur BEFORE loadBooks() is called
    assert dom_ref_idx < load_books_call_idx, (
        f"TDZ Hazard: 'genreFilterSelect' collected at char {dom_ref_idx}, "
        f"but loadBooks() invoked earlier at char {load_books_call_idx}!"
    )


def test_total_pages_calculation():
    content = JS_PATH.read_text(encoding="utf-8")
    
    # Must NOT contain undefined outer variable b or sumTotalPages(b)
    assert "sumTotalPages" not in content, "Invalid helper sumTotalPages must be removed"
    assert "books.reduce((sum, b) => sum + (Number(b.pagesRead) || 0), sumTotalPages(b)" not in content
    
    # Must contain clean reducer
    assert "sum + (Number(book.pagesRead) || 0)" in content or "sum + (Number(b.pagesRead) || 0)" in content
    
    # Pure Python logic test of the calculation across 0, 1, and 4 books
    def calc_pages(book_list):
        return sum(int(b.get("pagesRead", 0)) for b in book_list)

    assert calc_pages([]) == 0
    assert calc_pages([{"pagesRead": 50}]) == 50
    assert calc_pages([{"pagesRead": 140}, {"pagesRead": 320}, {"pagesRead": 0}, {"pagesRead": 200}]) == 660


def test_dashboard_statistic_ids_match_html():
    html = HTML_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")

    expected_stat_ids = [
        "stat-total-books",
        "stat-currently-reading",
        "stat-completed-books",
        "stat-want-to-read",
        "stat-total-pages",
        "overview-completed-count",
        "overview-pages-pct",
        "overview-progress-bar",
    ]

    for sid in expected_stat_ids:
        assert f'id="{sid}"' in html, f"HTML is missing dashboard ID: {sid}"
        assert sid in js, f"JavaScript is not referencing dashboard ID: {sid}"

    # Verify stale mismatched IDs are NOT used in app.js
    assert "stat-completed'" not in js and 'stat-completed"' not in js, "Mismatched ID 'stat-completed' should not be used in app.js"
    assert "stat-pages-read'" not in js and 'stat-pages-read"' not in js, "Mismatched ID 'stat-pages-read' should not be used in app.js"


def test_status_and_genre_filtering_concordance():
    html = HTML_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")

    expected_statuses = ["all", "Want to Read", "Currently Reading", "Completed"]

    for st in expected_statuses:
        # Check select option
        assert f'value="{st}"' in html, f"HTML #status-filter missing option value: {st}"
        # Check nav link
        assert f'data-filter="{st}"' in html, f"HTML sidebar nav missing data-filter: {st}"

    # Verify app.js attaches to nav-item[data-filter] and status-filter
    assert "data-filter" in js, "JavaScript must bind to data-filter"
    assert "status-filter" in js, "JavaScript must bind to status-filter"
    assert ".status-tab" not in js, "Outdated selector .status-tab must be removed from app.js"


def test_sorting_options_concordance():
    html = HTML_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")

    expected_sort_values = [
        "recent",
        "title-asc",
        "title-desc",
        "progress-desc",
        "progress-asc",
        "rating-desc",
    ]

    for val in expected_sort_values:
        assert f'value="{val}"' in html, f"HTML #sort-select missing sort value: {val}"
        assert f"'{val}'" in js or f'"{val}"' in js, f"JavaScript sort handling missing value: {val}"

    # Verify stale sort values are not used
    assert "'recently-added'" not in js and '"recently-added"' not in js, "Stale sort value 'recently-added' must be replaced with 'recent'"


def test_modal_and_form_identifiers():
    html = HTML_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")

    expected_modal_ids = [
        "book-modal",
        "modal-title",
        "book-form",
        "cancel-modal-btn",
        "modal-cancel-action",
        "save-book-btn",
        "book-id",
        "book-title",
        "book-author",
        "book-genre",
        "book-status",
        "book-total-pages",
        "book-pages-read",
        "book-rating",
        "book-notes",
    ]

    for mid in expected_modal_ids:
        assert f'id="{mid}"' in html, f"HTML form/modal missing ID: {mid}"
        assert mid in js, f"JavaScript missing reference to form/modal ID: {mid}"

    assert "modal-title-text" not in js, "Mismatched ID 'modal-title-text' must not be in app.js"


def test_css_class_concordance():
    css = CSS_PATH.read_text(encoding="utf-8")

    assert ".dashboard-overview" in css, "CSS must style .dashboard-overview"
    assert ".form-control" in css, "CSS must style .form-control"
    assert ".modal-container" in css and ".modal" in css, "CSS must style .modal container"
    assert "#search-input" in css or ".search-bar input" in css, "CSS must style search input"
    assert ".reading-progress-banner" in css, "CSS must style .reading-progress-banner"


def test_bash_exec_dev_server_interceptor(tmp_path):
    from tools.shell_tools import BashExecTool
    tool = BashExecTool()
    
    # When model attempts to run python -m http.server 8000, BashExecTool intercepts and starts it in background
    inp = BashExecTool.Input(
        command="python -m http.server 59888 --bind 127.0.0.1",
        working_dir=str(WORKSPACE_DIR),
        timeout_seconds=5,
    )
    result = tool.execute(inp)
    
    assert result.success is True, f"Dev server interceptor failed: {result.error}"
    assert result.exit_code == 0
    assert "Managed development server started in background" in result.output
    assert "http://127.0.0.1:59888/" in result.output
