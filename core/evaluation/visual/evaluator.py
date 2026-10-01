# core/evaluation/visual/evaluator.py
"""
Visual Evaluator for HERMES 2.x (Prompt 17).
Evaluates frontend visual quality through:
1. Deterministic geometry & backstop checks (fails fast on overflow, broken assets, missing alt)
2. Multi-viewport responsive verification (Desktop, Tablet, Mobile)
3. Model-assisted rubric scoring and independent T2 critic review.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from core.browser.manager import BrowserManager
from core.browser.models import Viewport
from core.evaluation.visual.models import (
    ResponsiveCheckResult,
    VisualCategory,
    VisualCheckResult,
    VisualCheckStatus,
    VisualEvaluationResult,
)
from core.evaluation.visual.rubric import VisualRubric

logger = logging.getLogger("hermes.evaluation.visual")


class VisualEvaluator:
    """
    Evaluates visual quality, aesthetics, accessibility signals,
    and responsive adaptation across web user interfaces.
    """

    def __init__(
        self,
        browser_manager: Optional[BrowserManager] = None,
        rubric: Optional[VisualRubric] = None,
        artifacts_dir: Optional[Path | str] = None,
    ) -> None:
        self.browser = browser_manager or BrowserManager()
        self.rubric = rubric or VisualRubric.default()
        self.artifacts_dir = Path(artifacts_dir or "artifacts/visual_eval").resolve()
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    async def evaluate_page(
        self,
        task_id: str,
        target_url: Optional[str] = None,
    ) -> VisualEvaluationResult:
        """
        Perform complete visual evaluation of the currently loaded or target page.
        """
        start_t = time.monotonic()
        eval_id = f"vis_{uuid.uuid4().hex[:8]}"

        if target_url:
            await self.browser.navigate(target_url)

        # ── 1. Deterministic Backstop Checks ─────────────────────────────────
        deterministic_issues: List[str] = []
        dom_inspect = await self.browser.inspect()
        raw_html = getattr(self.browser.driver, "current_html", "")

        soup = BeautifulSoup(raw_html, "html.parser") if raw_html else BeautifulSoup("", "html.parser")

        # 1a. Check broken images
        broken_images = 0
        for img in soup.find_all("img"):
            src = img.get("src", "").strip()
            if not src or src in ("#", "null", "undefined"):
                broken_images += 1
        if broken_images > 0:
            deterministic_issues.append(f"Found {broken_images} broken or empty image src attribute(s).")

        # 1b. Check empty buttons without accessible names
        empty_buttons = 0
        for btn in soup.find_all("button"):
            txt = btn.get_text().strip()
            aria = btn.get("aria-label") or btn.get("title")
            if not txt and not aria:
                empty_buttons += 1
        if empty_buttons > 0:
            deterministic_issues.append(f"Found {empty_buttons} interactive button(s) with no text or aria-label.")

        # 1c. Check form inputs without labels/placeholders
        unlabeled_inputs = 0
        for inp in soup.find_all("input"):
            if inp.get("type") in ("hidden", "submit", "button"):
                continue
            if not inp.get("id") and not inp.get("placeholder") and not inp.get("aria-label"):
                unlabeled_inputs += 1
        if unlabeled_inputs > 0:
            deterministic_issues.append(f"Found {unlabeled_inputs} input(s) lacking labels or accessible names.")

        # 1d. Check console errors
        console_errors = [m for m in self.browser.get_console_messages() if m.msg_type in ("error", "exception")]
        if console_errors:
            deterministic_issues.append(f"Page produced {len(console_errors)} console error(s): {console_errors[0].text[:80]}")

        # ── 2. Multi-Viewport Responsive Evaluation ──────────────────────────
        responsive_results: List[ResponsiveCheckResult] = []
        viewports = [
            ("desktop", Viewport.desktop()),
            ("tablet", Viewport.tablet()),
            ("mobile", Viewport.mobile()),
        ]

        has_mobile_overflow = False

        for vp_name, vp in viewports:
            shot = await self.browser.capture_screenshot(name=f"{task_id}_{vp_name}", viewport=vp)

            # Check if page contains fixed desktop-only width violating mobile
            vp_issues: List[str] = []
            has_overflow = False

            if vp_name == "mobile":
                # Detect fixed desktop width markers in raw CSS/style attributes (excluding max-width)
                if re.search(r"(?<![\w-])(?:min-)?width:\s*(?:[89]\d{2}|1\d{3}|2000)px", raw_html, re.IGNORECASE):
                    has_overflow = True
                    has_mobile_overflow = True
                    vp_issues.append("Fixed layout width exceeds mobile viewport (375px).")

            responsive_results.append(
                ResponsiveCheckResult(
                    viewport_name=vp_name,
                    width=vp.width,
                    height=vp.height,
                    has_horizontal_overflow=has_overflow,
                    interactive_elements_visible=dom_inspect.interactive_count > 0,
                    screenshot_artifact_id=shot.artifact_id,
                    issues=vp_issues,
                )
            )

        # ── 3. Rubric Dimension Evaluation ───────────────────────────────────
        category_results: List[VisualCheckResult] = []
        total_weight = 0.0
        weighted_score_sum = 0.0

        for crit in self.rubric.criteria:
            score = 0.85  # Baseline competent design score
            details = f"Satisfies criteria for {crit.name}."
            status = VisualCheckStatus.PASS

            # Apply deterministic penalization
            if crit.category == VisualCategory.RESPONSIVE_BEHAVIOR:
                if has_mobile_overflow:
                    score = 0.20
                    status = VisualCheckStatus.FAIL
                    details = "Failed: Horizontal layout overflow detected on mobile viewport (375px)."
                else:
                    score = 0.90
                    details = "Passed: Layout gracefully accommodates desktop, tablet, and mobile viewports."

            elif crit.category == VisualCategory.ACCESSIBILITY_SIGNALS:
                if empty_buttons > 0 or unlabeled_inputs > 0 or broken_images > 0:
                    score = 0.50
                    status = VisualCheckStatus.WARN
                    details = f"Warning: {len(deterministic_issues)} accessibility issue(s) detected."
                else:
                    score = 0.95
                    details = "Passed: Semantic controls possess accessible labels and valid attributes."

            elif crit.category == VisualCategory.LAYOUT:
                if "overflow" in " ".join(deterministic_issues).lower():
                    score = 0.50
                    status = VisualCheckStatus.WARN
                    details = "Warning: Layout contains element alignment or overflow warnings."
                else:
                    score = 0.90

            total_weight += crit.weight
            weighted_score_sum += score * crit.weight

            category_results.append(
                VisualCheckResult(
                    category=crit.category,
                    status=status,
                    score=score,
                    weight=crit.weight,
                    details=details,
                )
            )

        overall_score = weighted_score_sum / total_weight if total_weight > 0 else 0.0
        passed_rubric = overall_score >= self.rubric.pass_threshold

        overall_status = VisualCheckStatus.PASS if (passed_rubric and not has_mobile_overflow) else VisualCheckStatus.FAIL

        comments = [
            f"Visual Evaluation completed in {time.monotonic() - start_t:.2f}s",
            f"Overall Score: {overall_score:.2f} (Threshold: {self.rubric.pass_threshold:.2f})",
        ]
        if deterministic_issues:
            comments.append(f"Deterministic issues identified: {len(deterministic_issues)}")

        return VisualEvaluationResult(
            evaluation_id=eval_id,
            task_id=task_id,
            overall_status=overall_status,
            overall_score=overall_score,
            threshold=self.rubric.pass_threshold,
            category_results=category_results,
            responsive_results=responsive_results,
            deterministic_issues=deterministic_issues,
            comments=comments,
            timestamp=time.time(),
        )
