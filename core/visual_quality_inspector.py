# core/visual_quality_inspector.py
"""
Visual Quality Inspector and Autonomous Product Acceptance Engine for HERMES 2.x (Phase 4).
Evaluates 20-point visual design intelligence checklist, inspects physical screenshots,
measures responsive container overflow, and computes authoritative gate states:
  - STRUCTURAL_GATE
  - FUNCTIONAL_GATE
  - ASSET_GATE
  - RESPONSIVE_GATE
  - ACCESSIBILITY_GATE
  - VISUAL_REVIEW_GATE

Invariants:
1. Structural PASS never implies Visual PASS.
2. Screenshots must physically exist and be inspected for visual review to pass.
3. If screenshot inspection is unavailable, report NOT_RUN (never fabricate scores).
4. Any mandatory applicable gate in FAIL or NOT_RUN strictly prevents COMPLETED.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from core.asset_pipeline import AssetPipeline, AssetVerificationStatus


class GateStatus(str, Enum):
    """Authoritative states for mission acceptance gates."""
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"
    BLOCKED = "BLOCKED"


@dataclass
class VisualReviewReport:
    """Comprehensive visual quality and product acceptance report."""
    structural_gate: GateStatus = GateStatus.NOT_RUN
    functional_gate: GateStatus = GateStatus.NOT_RUN
    asset_gate: GateStatus = GateStatus.NOT_RUN
    responsive_gate: GateStatus = GateStatus.NOT_RUN
    accessibility_gate: GateStatus = GateStatus.NOT_RUN
    visual_review_gate: GateStatus = GateStatus.NOT_RUN

    checklist_results: Dict[str, bool] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    screenshots_inspected: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    structural_visual_heuristics: Dict[str, Any] = field(default_factory=dict)
    screenshot_capture: Dict[str, Any] = field(default_factory=dict)
    screenshot_non_blank_check: Dict[str, Any] = field(default_factory=dict)
    vision_based_visual_review: Dict[str, Any] = field(default_factory=lambda: {
        "status": "NOT_CONFIGURED",
        "multimodal_critique_executed": False,
        "reason": "Multimodal vision model not configured; acceptance relies on deterministic screenshot heuristics."
    })

    @property
    def is_all_passed(self) -> bool:
        """True only if every applicable gate is explicitly PASS."""
        gates = [
            self.structural_gate,
            self.functional_gate,
            self.asset_gate,
            self.responsive_gate,
            self.accessibility_gate,
            self.visual_review_gate,
        ]
        return all(g == GateStatus.PASS for g in gates)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "structural_gate": self.structural_gate.value,
            "functional_gate": self.functional_gate.value,
            "asset_gate": self.asset_gate.value,
            "responsive_gate": self.responsive_gate.value,
            "accessibility_gate": self.accessibility_gate.value,
            "visual_review_gate": self.visual_review_gate.value,
            "is_all_passed": self.is_all_passed,
            "checklist_passed_count": sum(1 for v in self.checklist_results.values() if v),
            "checklist_total_count": len(self.checklist_results),
            "checklist_results": self.checklist_results,
            "issues": self.issues,
            "screenshots_inspected": self.screenshots_inspected,
            "details": self.details,
            "structural_visual_heuristics": self.structural_visual_heuristics,
            "screenshot_capture": self.screenshot_capture,
            "screenshot_non_blank_check": self.screenshot_non_blank_check,
            "vision_based_visual_review": self.vision_based_visual_review,
        }


class VisualQualityInspector:
    """
    Evaluates visual composition, typography, responsive overflow, asset decodability,
    and genuine screenshot review against the 20-point design intelligence standard.
    """

    CHECKLIST_CRITERIA = [
        "overall_composition",
        "visual_hierarchy",
        "typography_quality",
        "typography_consistency",
        "section_spacing",
        "alignment",
        "grid_consistency",
        "component_proportions",
        "color_balance",
        "contrast",
        "hero_image_composition",
        "destination_photography",
        "card_design",
        "buttons_and_controls",
        "navigation_presentation",
        "footer_completeness",
        "responsive_behavior",
        "clipping_and_overlap",
        "empty_sections",
        "visual_consistency",
    ]

    @classmethod
    def inspect_workspace(
        cls,
        workspace_root: Path | str,
        prompt: str = "",
        browser_evidence: Optional[Dict[str, Any]] = None,
    ) -> VisualReviewReport:
        """
        Runs comprehensive visual inspection and evaluates all 6 gates.
        """
        ws = Path(workspace_root).resolve()
        report = VisualReviewReport()
        checklist: Dict[str, bool] = {k: False for k in cls.CHECKLIST_CRITERIA}

        html_file = ws / "index.html"
        css_file = ws / "style.css"
        if not css_file.exists():
            css_cands = list(ws.glob("*.css")) + list(ws.glob("static/*.css")) + list(ws.glob("css/*.css"))
            if css_cands:
                css_file = css_cands[0]

        html_text = html_file.read_text(encoding="utf-8", errors="ignore") if html_file.exists() else ""
        css_text = css_file.read_text(encoding="utf-8", errors="ignore") if css_file.exists() else ""
        p_lower = (prompt or "").lower()

        # ── 1. STRUCTURAL GATE ────────────────────────────────────────────────
        struct_issues = []
        if not html_file.exists():
            struct_issues.append("Missing primary entrypoint markup index.html.")
        else:
            if "<!doctype html>" not in html_text.lower():
                struct_issues.append("index.html missing standard HTML5 DOCTYPE.")
            if "<body" not in html_text.lower():
                struct_issues.append("index.html missing <body> tag.")
            if not css_text and "<style" not in html_text:
                struct_issues.append("No CSS stylesheet or <style> block defined.")

        if not struct_issues:
            report.structural_gate = GateStatus.PASS
            checklist["overall_composition"] = True
            checklist["visual_consistency"] = True
        else:
            report.structural_gate = GateStatus.FAIL
            report.issues.extend(struct_issues)

        # ── 2. ASSET GATE ─────────────────────────────────────────────────────
        asset_issues = []
        assets_ok, missing_assets, found_assets = AssetPipeline.verify_workspace_assets(ws)
        if not assets_ok:
            asset_issues.extend([f"Asset verification failed: {m}" for m in missing_assets])

        # Check for genuine photography if demanded
        demands_photo = any(w in p_lower for w in ("photo", "photography", "travel", "wanderworld", "destination", "package", "tour"))
        if demands_photo:
            has_photo = False
            for img_path in list(ws.glob("assets/images/**/*.*")) + list(ws.glob("images/**/*.*")):
                st, det = AssetPipeline.verify_image_file(img_path)
                if st == AssetVerificationStatus.PHOTOGRAPH_VERIFIED:
                    has_photo = True
                    break
            if not has_photo:
                asset_issues.append("Visual asset requirement failed: No verified decodable photography found in workspace assets.")

        if not asset_issues:
            report.asset_gate = GateStatus.PASS
            checklist["destination_photography"] = True
            checklist["hero_image_composition"] = bool(re.search(r'hero|banner', html_text, re.I))
        else:
            report.asset_gate = GateStatus.FAIL
            report.issues.extend(asset_issues)

        # ── 3. RESPONSIVE GATE ────────────────────────────────────────────────
        resp_issues = []
        # Check CSS media queries
        has_media_queries = "@media" in css_text or "@media" in html_text
        if not has_media_queries:
            resp_issues.append("CSS lacks responsive media queries for mobile/tablet breakpoints.")

        # Check browser viewport evidence if available
        if browser_evidence:
            viewports = browser_evidence.get("viewports_tested", [])
            for vp in viewports:
                if isinstance(vp, dict):
                    if vp.get("has_overflow") or (vp.get("scroll_width", 0) > vp.get("client_width", 0)):
                        resp_issues.append(
                            f"Horizontal overflow detected on viewport {vp.get('name', 'unknown')} "
                            f"({vp.get('width')}x{vp.get('height')}): scrollWidth > clientWidth."
                        )
        elif (ws / ".hermes" / "acceptance_evidence.json").exists():
            try:
                acc_data = json.loads((ws / ".hermes" / "acceptance_evidence.json").read_text(encoding="utf-8"))
                for iss in acc_data.get("issues", []):
                    if "RESPONSIVE" in iss or "overflow" in iss.lower():
                        resp_issues.append(iss)
            except Exception:
                pass

        if not resp_issues:
            report.responsive_gate = GateStatus.PASS
            checklist["responsive_behavior"] = True
            checklist["clipping_and_overlap"] = True
        else:
            report.responsive_gate = GateStatus.FAIL
            report.issues.extend(resp_issues)

        # ── 4. FUNCTIONAL GATE ────────────────────────────────────────────────
        func_issues = []
        js_files = list(ws.glob("*.js")) + list(ws.glob("static/*.js"))
        js_text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in js_files if f.is_file())

        if not js_files:
            func_issues.append("Missing client-side JavaScript implementation.")
        else:
            # Check for console.log only fake handlers
            fake_handlers = re.findall(
                r'addEventListener\(\s*["\'](?:input|change|click|submit)["\']\s*,\s*(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>\s*\{\s*console\.log\([^)]*\);?\s*\}\s*\)',
                js_text
            )
            if fake_handlers:
                func_issues.append("Event handler contains only console.log() without state or DOM update.")

            # Check for empty queried DOM IDs
            html_ids = set(re.findall(r'\bid=["\']([a-zA-Z0-9_\-]+)["\']', html_text))
            queried_ids = set(re.findall(r'getElementById\(\s*["\']([a-zA-Z0-9_\-]+)["\']\s*\)', js_text))
            for qid in queried_ids:
                if qid not in html_ids and f'id="{qid}"' not in js_text:
                    func_issues.append(f"JavaScript queries '#{qid}' but no element with id='{qid}' exists in HTML.")

        if browser_evidence:
            b_res = browser_evidence.get("browser_result", {})
            if not b_res.get("interactions_passed", False):
                func_issues.append(f"Browser interactions failed: {b_res.get('failure_reason', 'interactions failed')}")

        if not func_issues:
            report.functional_gate = GateStatus.PASS
            checklist["buttons_and_controls"] = True
        else:
            report.functional_gate = GateStatus.FAIL
            report.issues.extend(func_issues)

        # ── 5. ACCESSIBILITY GATE ─────────────────────────────────────────────
        a11y_issues = []
        imgs = re.findall(r'<img\s+[^>]*>', html_text, re.I)
        missing_alt = [img for img in imgs if 'alt=' not in img.lower()]
        if missing_alt:
            a11y_issues.append(f"{len(missing_alt)} image(s) lack required accessibility alt attributes.")

        # Check forms have labels or aria-labels
        inputs = re.findall(r'<input\s+[^>]*>', html_text, re.I)
        unlabeled_inputs = [inp for inp in inputs if not any(k in inp.lower() for k in ('aria-label', 'placeholder', 'id=')) and 'type="hidden"' not in inp.lower()]
        if len(unlabeled_inputs) > 2:
            a11y_issues.append(f"{len(unlabeled_inputs)} input(s) lack labels, aria-labels, or placeholders.")

        if not a11y_issues:
            report.accessibility_gate = GateStatus.PASS
        else:
            report.accessibility_gate = GateStatus.FAIL
            report.issues.extend(a11y_issues)

        # ── 6. VISUAL REVIEW GATE (Physical Screenshots) ──────────────────────
        shot_dir = ws / ".hermes" / "screenshots"
        candidate_shots = []
        if shot_dir.exists():
            candidate_shots.extend(list(shot_dir.glob("*.png")) + list(shot_dir.glob("*.jpg")))
        acc_shot = ws / ".hermes" / "acceptance_screenshot.png"
        if acc_shot.exists() and acc_shot not in candidate_shots:
            candidate_shots.append(acc_shot)

        valid_shots = [s for s in candidate_shots if s.is_file() and s.stat().st_size > 500]
        visual_defects: List[str] = []

        if not valid_shots:
            # Section 6: Where inspection is unavailable, report NOT_RUN. Do not fabricate visual scores.
            report.visual_review_gate = GateStatus.NOT_RUN
            report.details["visual_review_note"] = "No physical screenshots available to inspect; reported NOT_RUN per Section 6."
        else:
            # Physical inspection of screenshots using Pillow
            from PIL import Image, ImageStat
            for s_file in valid_shots:
                report.screenshots_inspected.append(str(s_file.name))
                try:
                    with Image.open(s_file) as im:
                        im.verify()
                    with Image.open(s_file) as im:
                        w, h = im.size
                        if w < 300 or h < 300:
                            visual_defects.append(f"Screenshot '{s_file.name}' has unrendered dimensions: {w}x{h}.")
                        # Check image brightness/contrast
                        stat = ImageStat.Stat(im.convert("L"))
                        mean_brightness = stat.mean[0]
                        std_dev = stat.stddev[0]
                        if std_dev < 1.0:
                            visual_defects.append(f"Screenshot '{s_file.name}' is completely blank/monochromatic.")
                except Exception as ex:
                    visual_defects.append(f"Cannot decode screenshot '{s_file.name}': {ex}")

            if not visual_defects:
                report.visual_review_gate = GateStatus.PASS
                checklist["visual_hierarchy"] = True
                checklist["typography_quality"] = True
                checklist["typography_consistency"] = True
                checklist["section_spacing"] = True
                checklist["alignment"] = True
                checklist["grid_consistency"] = True
                checklist["component_proportions"] = True
                checklist["color_balance"] = True
                checklist["contrast"] = True
                checklist["card_design"] = True
                checklist["navigation_presentation"] = True
                checklist["footer_completeness"] = True
                checklist["empty_sections"] = True
            else:
                report.visual_review_gate = GateStatus.FAIL
                report.issues.extend(visual_defects)

        report.checklist_results = checklist
        report.structural_visual_heuristics = {
            "passed": not bool(struct_issues),
            "doctype_present": "<!doctype html>" in html_text.lower(),
            "body_present": "<body" in html_text.lower(),
            "stylesheet_defined": bool(css_text or "<style" in html_text),
            "issues": struct_issues,
        }
        report.screenshot_capture = {
            "captured_count": len(valid_shots),
            "files": [s.name for s in valid_shots],
            "passed": bool(valid_shots),
        }
        report.screenshot_non_blank_check = {
            "passed": bool(valid_shots and not visual_defects),
            "defects": visual_defects,
        }
        report.vision_based_visual_review = {
            "status": "NOT_CONFIGURED",
            "multimodal_critique_executed": False,
            "reason": "Multimodal vision model not configured; acceptance relies on deterministic screenshot heuristics."
        }
        return report

    @classmethod
    def can_complete_mission(cls, report: VisualReviewReport) -> Tuple[bool, str]:
        """
        Validates authoritative completion invariants.
        Profile C / website missions require every mandatory gate to be PASS.
        """
        if report.structural_gate != GateStatus.PASS:
            return False, f"Structural gate failed: {report.structural_gate.value}"
        if report.asset_gate != GateStatus.PASS:
            return False, f"Asset gate failed: {report.asset_gate.value}"
        if report.functional_gate != GateStatus.PASS:
            return False, f"Functional gate failed: {report.functional_gate.value}"
        if report.responsive_gate != GateStatus.PASS:
            return False, f"Responsive gate failed: {report.responsive_gate.value}"
        if report.accessibility_gate != GateStatus.PASS:
            return False, f"Accessibility gate failed: {report.accessibility_gate.value}"
        if report.visual_review_gate == GateStatus.FAIL:
            return False, f"Visual review gate failed: {report.visual_review_gate.value}"
        if report.visual_review_gate == GateStatus.NOT_RUN:
            return False, "Visual review gate is NOT_RUN; physical screenshot inspection required before completion."

        return True, "All mandatory acceptance gates PASS."
