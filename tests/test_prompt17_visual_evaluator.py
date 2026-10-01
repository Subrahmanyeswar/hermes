# tests/test_prompt17_visual_evaluator.py
"""
Test Suite: Prompt 17 Visual Evaluator.
Validates deterministic backstops, responsive viewport checks,
and rubric-based evaluation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.browser.manager import BrowserManager
from core.evaluation.visual.evaluator import VisualEvaluator
from core.evaluation.visual.models import VisualCategory, VisualCheckStatus
from core.evaluation.visual.rubric import VisualRubric


@pytest.mark.asyncio
async def test_visual_evaluator_clean_responsive_page(tmp_path: Path):
    """Verify clean responsive page passes visual evaluation."""
    clean_html = (
        "<!DOCTYPE html>"
        "<html><head><title>Clean Dashboard</title>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        "<style>body { font-family: sans-serif; margin: 0; padding: 1rem; } "
        ".card { max-width: 100%; border: 1px solid #ddd; padding: 1rem; border-radius: 8px; }</style>"
        "</head><body>"
        "  <div class='card'>"
        "    <h1>Analytics Overview</h1>"
        "    <p>Monthly recurring revenue is tracking on schedule.</p>"
        "    <button id='action-btn' aria-label='Refresh data'>Refresh</button>"
        "  </div>"
        "</body></html>"
    )

    page_file = tmp_path / "clean.html"
    page_file.write_text(clean_html, encoding="utf-8")

    browser = BrowserManager(artifacts_dir=tmp_path / "artifacts", prefer_cdp=False)
    await browser.navigate(page_file.as_uri())

    evaluator = VisualEvaluator(
        browser_manager=browser,
        artifacts_dir=tmp_path / "artifacts",
    )

    res = await evaluator.evaluate_page(task_id="clean_task")
    assert res.overall_status == VisualCheckStatus.PASS
    assert res.overall_score >= 0.70
    assert len(res.responsive_results) == 3
    assert all(r.is_passed for r in res.responsive_results)
    assert len(res.deterministic_issues) == 0

    await browser.close()


@pytest.mark.asyncio
async def test_visual_evaluator_mobile_overflow_failure(tmp_path: Path):
    """Verify fixed width causing mobile overflow triggers VisualCheckStatus.FAIL."""
    overflow_html = (
        "<!DOCTYPE html>"
        "<html><head><title>Broken Mobile App</title>"
        "<style>body { width: 1400px; } .fixed-table { width: 1200px; }</style>"
        "</head><body>"
        "  <div class='fixed-table'><h1>Big Wide Grid</h1><button>Action</button></div>"
        "</body></html>"
    )

    page_file = tmp_path / "overflow.html"
    page_file.write_text(overflow_html, encoding="utf-8")

    browser = BrowserManager(artifacts_dir=tmp_path / "artifacts", prefer_cdp=False)
    await browser.navigate(page_file.as_uri())

    evaluator = VisualEvaluator(
        browser_manager=browser,
        artifacts_dir=tmp_path / "artifacts",
    )

    res = await evaluator.evaluate_page(task_id="overflow_task")
    assert res.overall_status == VisualCheckStatus.FAIL

    # Verify mobile result recorded overflow
    mobile_res = next(r for r in res.responsive_results if r.viewport_name == "mobile")
    assert mobile_res.has_horizontal_overflow is True

    # Verify responsive category failed
    resp_cat = next(c for c in res.category_results if c.category == VisualCategory.RESPONSIVE_BEHAVIOR)
    assert resp_cat.status == VisualCheckStatus.FAIL
    assert resp_cat.score < 0.50

    await browser.close()


@pytest.mark.asyncio
async def test_visual_evaluator_deterministic_accessibility_backstop(tmp_path: Path):
    """Verify empty buttons and broken images trigger deterministic warnings."""
    inaccessible_html = (
        "<!DOCTYPE html>"
        "<html><head><title>Bad A11y</title></head><body>"
        "  <h1>Site</h1>"
        "  <img src='' />"
        "  <button id='empty-btn'></button>"
        "  <input type='text' />"
        "</body></html>"
    )

    page_file = tmp_path / "a11y.html"
    page_file.write_text(inaccessible_html, encoding="utf-8")

    browser = BrowserManager(artifacts_dir=tmp_path / "artifacts", prefer_cdp=False)
    await browser.navigate(page_file.as_uri())

    evaluator = VisualEvaluator(
        browser_manager=browser,
        artifacts_dir=tmp_path / "artifacts",
    )

    res = await evaluator.evaluate_page(task_id="a11y_task")
    assert len(res.deterministic_issues) >= 2
    assert any("broken or empty image" in issue for issue in res.deterministic_issues)
    assert any("interactive button(s) with no text" in issue for issue in res.deterministic_issues)

    # Verify accessibility signals category penalized
    a11y_cat = next(c for c in res.category_results if c.category == VisualCategory.ACCESSIBILITY_SIGNALS)
    assert a11y_cat.status == VisualCheckStatus.WARN
    assert a11y_cat.score <= 0.60

    await browser.close()


def test_visual_rubric_yaml_loader(tmp_path: Path):
    """Verify loading custom YAML rubric file."""
    rubric_yaml = (
        "version: '2.0.0'\n"
        "name: 'Strict Rubric'\n"
        "pass_threshold: 0.85\n"
        "criteria:\n"
        "  - id: 'DESIGN_QUALITY'\n"
        "    name: 'Aesthetic Purity'\n"
        "    weight: 2.0\n"
    )
    rubric_file = tmp_path / "custom_rubric.yaml"
    rubric_file.write_text(rubric_yaml, encoding="utf-8")

    rubric = VisualRubric.load_from_yaml(rubric_file)
    assert rubric.version == "2.0.0"
    assert rubric.name == "Strict Rubric"
    assert rubric.pass_threshold == 0.85
    assert len(rubric.criteria) == 1
    assert rubric.criteria[0].weight == 2.0
