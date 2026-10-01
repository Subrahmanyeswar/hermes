# tests/test_prompt17_functional_evaluator.py
"""
Test Suite: Prompt 17 Functional Evaluator.
Validates multi-layer evaluation: Static, Tests, Runtime, Browser, and Persistence.
Verifies outcome-first verification and structured repair feedback.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.browser.manager import BrowserManager
from core.evaluation.functional.evaluator import FunctionalEvaluator
from core.evaluation.functional.models import (
    CheckLayer,
    CheckStatus,
    FunctionalCheck,
    FunctionalRequirement,
)


@pytest.mark.asyncio
async def test_functional_evaluator_static_and_test_layers(tmp_path: Path):
    """Verify static code checks and test runner checks."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create a valid Python file
    valid_file = workspace / "math_mod.py"
    valid_file.write_text("def multiply(a: int, b: int) -> int:\n    return a * b\n", encoding="utf-8")

    # Create a broken Python file
    broken_file = workspace / "broken.py"
    broken_file.write_text("def bad_func(\n    return 42\n", encoding="utf-8")

    evaluator = FunctionalEvaluator(workspace_root=workspace)

    # 1. Static check on clean file
    chk_clean = FunctionalCheck(
        check_id="chk_clean",
        name="Valid syntax",
        layer=CheckLayer.STATIC,
        expected="math_mod.py",
    )
    req1 = FunctionalRequirement(req_id="r1", title="Clean code", checks=[chk_clean])
    await evaluator.evaluate_requirement(req1)
    assert chk_clean.status == CheckStatus.PASS

    # 2. Static check on broken file
    chk_broken = FunctionalCheck(
        check_id="chk_broken",
        name="Syntax check",
        layer=CheckLayer.STATIC,
        expected="broken.py",
    )
    req2 = FunctionalRequirement(req_id="r2", title="Syntax check", checks=[chk_broken])
    await evaluator.evaluate_requirement(req2)
    assert chk_broken.status == CheckStatus.FAIL
    assert chk_broken.suspected_location is not None
    assert "broken.py:1" in chk_broken.suspected_location

    # 3. Test layer check (using python -c "exit(0)" vs "exit(1)")
    chk_test_ok = FunctionalCheck(
        check_id="chk_t_ok",
        name="Passing test command",
        layer=CheckLayer.TESTS,
        expected='python -c "exit(0)"',
    )
    req3 = FunctionalRequirement(req_id="r3", title="Unit tests", checks=[chk_test_ok])
    await evaluator.evaluate_requirement(req3)
    assert chk_test_ok.status == CheckStatus.PASS

    chk_test_fail = FunctionalCheck(
        check_id="chk_t_fail",
        name="Failing test command",
        layer=CheckLayer.TESTS,
        expected='python -c "exit(1)"',
    )
    req4 = FunctionalRequirement(req_id="r4", title="Failing test", checks=[chk_test_fail])
    await evaluator.evaluate_requirement(req4)
    assert chk_test_fail.status == CheckStatus.FAIL
    assert "exit code" in chk_test_fail.failure_reason.lower()


@pytest.mark.asyncio
async def test_functional_evaluator_browser_and_persistence_layers(tmp_path: Path):
    """Verify browser UI checks and state persistence verification across reload."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # HTML page containing a saved item
    page_html = (
        "<!DOCTYPE html><html><head><title>App</title></head><body>"
        "  <h1>Dashboard</h1>"
        "  <div id='items'><span>Transaction #101 - $50</span></div>"
        "</body></html>"
    )
    page_file = workspace / "index.html"
    page_file.write_text(page_html, encoding="utf-8")
    page_url = page_file.as_uri()

    browser = BrowserManager(artifacts_dir=tmp_path / "artifacts", prefer_cdp=False)
    await browser.navigate(page_url)

    evaluator = FunctionalEvaluator(workspace_root=workspace, browser_manager=browser)

    # 1. Browser check for existing item
    chk_browser = FunctionalCheck(
        check_id="chk_item_present",
        name="Verify item rendered",
        layer=CheckLayer.BROWSER,
        expected="Transaction #101",
    )
    req = FunctionalRequirement(req_id="r_browser", title="UI check", checks=[chk_browser])
    await evaluator.evaluate_requirement(req)
    assert chk_browser.status == CheckStatus.PASS

    # 2. Persistence check across reload
    chk_persist = FunctionalCheck(
        check_id="chk_item_persisted",
        name="Verify persistence across reload",
        layer=CheckLayer.PERSISTENCE,
        expected="Transaction #101",
    )
    req_p = FunctionalRequirement(req_id="r_persist", title="Persistence check", checks=[chk_persist])
    await evaluator.evaluate_requirement(req_p)
    assert chk_persist.status == CheckStatus.PASS

    # 3. Persistence failure check (expecting an unsaved transaction that disappears)
    chk_lost = FunctionalCheck(
        check_id="chk_lost",
        name="Verify lost item fails",
        layer=CheckLayer.PERSISTENCE,
        expected="Transaction #999",
    )
    req_lost = FunctionalRequirement(req_id="r_lost", title="Lost item check", checks=[chk_lost])
    await evaluator.evaluate_requirement(req_lost)
    assert chk_lost.status == CheckStatus.FAIL
    assert "lost after page reload" in chk_lost.actual

    await browser.close()
