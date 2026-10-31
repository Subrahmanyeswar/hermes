# tests/test_focusforge_remediation.py
"""
Regression test suite for FocusForge functional repair and HERMES false completion gate remediation.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
import pytest

from core.verification_profiles import (
    VerificationProfile,
    VerificationProfileEvaluator,
    classify_verification_profile,
)
from tools.shell_tools import _command_for_platform

FOCUSFORGE_DIR = Path(r"C:\Users\SUBBU\Downloads\testing 9")


def test_focusforge_files_exist():
    """Verify all required FocusForge deliverable files exist and are non-empty."""
    assert FOCUSFORGE_DIR.exists(), f"FocusForge directory not found at {FOCUSFORGE_DIR}"
    for fname in ["index.html", "app.js", "style.css", "package.json"]:
        p = FOCUSFORGE_DIR / fname
        assert p.exists(), f"Missing required file: {fname}"
        assert p.stat().st_size > 0, f"File {fname} is empty (0 bytes)"


def test_focusforge_node_syntax_check():
    """Verify that node --check succeeds on app.js with zero syntax errors."""
    app_js = FOCUSFORGE_DIR / "app.js"
    res = subprocess.run(["node", "--check", str(app_js)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check failed: {res.stderr or res.stdout}"


def test_section_visibility_contract_in_css():
    """Verify style.css contains the required .app-section hiding and active display rules."""
    style_css = (FOCUSFORGE_DIR / "style.css").read_text(encoding="utf-8")
    assert ".app-section" in style_css
    # Must have display: none rule for .app-section
    assert re.search(r'\.app-section\s*\{[^}]*display\s*:\s*none', style_css, re.IGNORECASE)
    # Must have active display rule
    assert re.search(r'\.app-section\.active\s*\{[^}]*display\s*:\s*block', style_css, re.IGNORECASE)


def test_html_and_js_identifier_concordance():
    """Verify contracted DOM IDs in index.html match bindings in app.js."""
    html_content = (FOCUSFORGE_DIR / "index.html").read_text(encoding="utf-8")
    js_content = (FOCUSFORGE_DIR / "app.js").read_text(encoding="utf-8")

    contracted_ids = [
        "section-dashboard",
        "section-tasks",
        "section-timer",
        "section-habits",
        "section-analytics",
        "section-settings",
        "stat-tasks-completed",
        "stat-tasks-pending",
        "stat-focus-time",
        "habits-completed-today",
        "habits-total-today",
        "daily-progress-fill",
        "daily-progress-text",
        "dashboard-task-list",
        "dashboard-habit-list",
        "open-task-modal",
        "task-search",
        "filter-status",
        "filter-priority",
        "tasks-container",
        "task-modal",
        "task-form",
        "timer-display",
        "timer-start",
        "timer-pause",
        "timer-reset",
        "focus-sessions-count",
        "open-habit-modal",
        "habit-streak-display",
        "habits-container",
        "habit-modal",
        "habit-form",
        "analytics-focus-week",
        "analytics-sessions-count",
        "analytics-tasks-week",
        "analytics-habit-rate",
        "chart-focus-weekly",
        "chart-tasks-daily",
        "theme-toggle",
        "reset-data-btn",
    ]

    for elem_id in contracted_ids:
        assert f'id="{elem_id}"' in html_content, f"index.html missing contracted ID: {elem_id}"
        assert elem_id in js_content, f"app.js missing reference to contracted ID: {elem_id}"


def test_profile_c_rejects_syntax_error(tmp_path):
    """Verify Profile C evaluation fails when a JS file has a syntax error."""
    (tmp_path / "index.html").write_text(
        "<!DOCTYPE html><html><body><script src='app.js'></script></body></html>",
        encoding="utf-8"
    )
    (tmp_path / "style.css").write_text("body { color: red; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("const a = 1; let broken = (;", encoding="utf-8")

    res = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_C,
        tmp_path,
        "Build a web application"
    )
    assert not res.passed, "Profile C should fail on JavaScript syntax errors"
    assert any("syntax error" in iss.lower() for iss in res.issues), f"Issues: {res.issues}"


def test_profile_c_rejects_missing_section_visibility(tmp_path):
    """Verify Profile C evaluation fails when sections are defined without CSS visibility hiding."""
    (tmp_path / "index.html").write_text(
        """<!DOCTYPE html>
        <html><body>
            <section class="app-section active">Section 1</section>
            <section class="app-section">Section 2</section>
            <script src="app.js"></script>
        </body></html>""",
        encoding="utf-8"
    )
    (tmp_path / "style.css").write_text("body { color: #fff; }", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('Valid JS');", encoding="utf-8")

    res = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_C,
        tmp_path,
        "Build a web application"
    )
    assert not res.passed, "Profile C should fail when section visibility contract is violated"
    assert any("visibility" in iss.lower() for iss in res.issues), f"Issues: {res.issues}"


def test_profile_c_passes_repaired_focusforge():
    """Verify that Profile C passes completely on the repaired FocusForge workspace."""
    res = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_C,
        FOCUSFORGE_DIR,
        "Build a personal productivity command center web application with tasks, habits, timer, and analytics"
    )
    assert res.passed, f"Profile C failed on repaired FocusForge: {res.issues}"
    assert "javascript_syntax_validation" in res.checks_run
    assert "section_visibility_contract" in res.checks_run
    assert "interactive_bindings_check" in res.checks_run


def test_shell_wc_translation():
    """Verify that bash_exec translates wc -l to cross-platform python on Windows."""
    translated = _command_for_platform("wc -l index.html")
    assert "python" in translated.lower()
    assert "-c" in translated
    assert "sys.argv" in translated
