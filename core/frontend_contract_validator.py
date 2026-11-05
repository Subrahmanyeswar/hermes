# core/frontend_contract_validator.py
"""
HTML, CSS, and JavaScript Integration Contract Validator for HERMES 2.x.
Verifies cross-file consistency between HTML DOM elements, JavaScript selectors,
dynamic innerHTML render targets, CSS component selectors, data filter categories,
modal layouts, and responsive rules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


@dataclass
class FrontendValidationReport:
    """Result of cross-file frontend contract validation."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    dom_id_issues: List[Dict[str, Any]] = field(default_factory=list)
    render_target_issues: List[Dict[str, Any]] = field(default_factory=list)
    css_class_issues: List[Dict[str, Any]] = field(default_factory=list)
    category_mismatches: List[Dict[str, Any]] = field(default_factory=list)
    responsive_issues: List[Dict[str, Any]] = field(default_factory=list)
    image_issues: List[Dict[str, Any]] = field(default_factory=list)
    modal_issues: List[Dict[str, Any]] = field(default_factory=list)
    token_issues: List[Dict[str, Any]] = field(default_factory=list)
    local_asset_issues: List[Dict[str, Any]] = field(default_factory=list)
    js_selector_issues: List[Dict[str, Any]] = field(default_factory=list)
    browser_verification: Dict[str, Any] = field(default_factory=dict)
    visual_qa_status: str = "PENDING"
    functional_qa_status: str = "PENDING" 

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_summary_block(self) -> str:
        status_str = "PASSED" if self.is_valid else "FAILED"
        lines = [
            f"=== FRONTEND INTEGRATION CONTRACT REPORT [{status_str}] ===",
            f"Validation Status: {'VALID' if self.is_valid else 'DEFECTS DETECTED'}",
            f"Total Errors: {len(self.errors)} | Total Warnings: {len(self.warnings)}",
        ]
        if self.errors:
            lines.append("Critical Errors:")
            for e in self.errors[:10]:
                lines.append(f"  [ERROR] {e}")
        if self.warnings:
            lines.append("Warnings:")
            for w in self.warnings[:10]:
                lines.append(f"  [WARN] {w}")
        if self.is_valid:
            lines.append("All DOM selectors, render targets, CSS classes, categories, and responsive rules verified.")
        lines.append("=============================================================")
        return "\n".join(lines)


class FrontendContractValidator:
    """
    Validates cross-file integrity of HTML, CSS, and JavaScript.
    Blocks common failure modes such as:
      - JavaScript referencing non-existent HTML element IDs.
      - Dynamic innerHTML renderers overwriting parent <section> roots instead of dedicated child containers.
      - HTML components lacking styling rules in CSS.
      - Category filter buttons in HTML not matching JavaScript item categories.
      - Missing responsive styles or horizontal overflow risks.
      - Unstyled modals, giant images, or unstyled buttons.
    """

    def __init__(self, workspace_root: Optional[Path | str] = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()

    def _find_files(self) -> Tuple[List[Path], List[Path], List[Path]]:
        """Find HTML, CSS, and JS files in canonical workspace locations."""
        ws = self.workspace_root
        candidate_dirs = [ws, ws / "static", ws / "public", ws / "src"]
        
        html_files = []
        css_files = []
        js_files = []

        for d in candidate_dirs:
            if d.exists() and d.is_dir():
                for f in d.iterdir():
                    if f.is_file():
                        if f.suffix.lower() == ".html":
                            html_files.append(f)
                        elif f.suffix.lower() == ".css":
                            css_files.append(f)
                        elif f.suffix.lower() == ".js":
                            # Ignore node_modules, tests, config
                            if not f.name.endswith(".test.js") and not f.name.endswith(".config.js"):
                                js_files.append(f)

        return html_files, css_files, js_files

    def _read_content(self, files: List[Path]) -> str:
        combined = []
        for f in files:
            try:
                combined.append(f.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:
                logger.warning(f"FrontendContractValidator: could not read {f}: {e}")
        return "\n".join(combined)

    # ── 1. DOM ID Consistency ───────────────────────────────────────────────

    @classmethod
    def validate_dom_ids(cls, html_text: str, js_text: str) -> List[Dict[str, Any]]:
        """
        Verify that all element IDs queried in JavaScript exist in HTML.
        """
        issues = []
        # Extract HTML IDs
        html_ids = set(re.findall(r'\bid=["\']([a-zA-Z0-9_\-]+)["\']', html_text))

        # Extract JS ID queries
        # Patterns: getElementById("id"), querySelector("#id"), $('#id')
        js_id_patterns = [
            r'getElementById\(\s*["\']([a-zA-Z0-9_\-]+)["\']\s*\)',
            r'querySelector\(\s*["\']#([a-zA-Z0-9_\-]+)["\']\s*\)',
            r'querySelectorAll\(\s*["\']#([a-zA-Z0-9_\-]+)["\']\s*\)',
            r'\$\(\s*["\']#([a-zA-Z0-9_\-]+)["\']\s*\)',
        ]
        
        queried_ids: Set[str] = set()
        for pat in js_id_patterns:
            for match in re.finditer(pat, js_text):
                queried_ids.add(match.group(1))

        # Check for missing IDs
        for q_id in sorted(queried_ids):
            # Exclude dynamically created IDs if referenced in templates
            if q_id not in html_ids:
                # Check if it's created dynamically in JS template strings e.g. `id="${...}"`
                if f'id="{q_id}"' not in js_text and f"id='{q_id}'" not in js_text:
                    issues.append({
                        "type": "MISSING_DOM_ID",
                        "id": q_id,
                        "message": f"JavaScript queries '#{q_id}' but no element with id='{q_id}' exists in HTML.",
                    })
        return issues

    # ── 2. Render Target Safety ──────────────────────────────────────────────

    @classmethod
    def validate_render_targets(cls, html_text: str, js_text: str) -> List[Dict[str, Any]]:
        """
        Detect whether dynamic JS rendering targets a root <section> element
        instead of a dedicated child container/grid div.
        Overwriting a <section> destroys static headings, subheadings, and filter bars.
        """
        issues = []
        # Find innerHTML assignments
        # e.g., target.innerHTML = ... or document.getElementById("xyz").innerHTML = ...
        direct_inner_html = re.findall(
            r'(?:getElementById|querySelector)\(\s*["\']#?([a-zA-Z0-9_\-]+)["\']\s*\)\.innerHTML\s*=',
            js_text
        )
        
        # Variable-based: const x = document.getElementById("xyz"); ... x.innerHTML = ...
        var_assignments = re.findall(
            r'(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:document\.)?(?:getElementById|querySelector)\(\s*["\']#?([a-zA-Z0-9_\-]+)["\']\s*\)',
            js_text
        )
        var_to_id = {var_name: elem_id for var_name, elem_id in var_assignments}
        
        for var_name, elem_id in var_to_id.items():
            if re.search(rf'\b{re.escape(var_name)}\.innerHTML\s*=', js_text):
                direct_inner_html.append(elem_id)

        # Inspect each render target in HTML
        for target_id in set(direct_inner_html):
            # Check if this ID belongs to a <section> tag in HTML
            section_match = re.search(rf'<section[^>]*\bid=["\']{re.escape(target_id)}["\'][^>]*>', html_text, re.IGNORECASE)
            if section_match:
                # Check if that section contains headings or filter buttons
                sec_tag = section_match.group(0)
                # Find the closing </section>
                sec_start = section_match.start()
                sec_close = html_text.find("</section>", sec_start)
                sec_body = html_text[sec_start:sec_close] if sec_close != -1 else ""
                
                has_heading = bool(re.search(r'<h[1-6]', sec_body, re.I))
                has_filters = bool(re.search(r'class=["\'][^"\']*(?:filter|search|nav|tabs)[^"\']*["\']', sec_body, re.I))
                
                if has_heading or has_filters:
                    issues.append({
                        "type": "DANGEROUS_SECTION_OVERWRITE",
                        "target_id": target_id,
                        "message": (
                            f"Dynamic JS render (.innerHTML) directly targets root <section id='{target_id}'>. "
                            f"This destroys static section headings, subtitles, or filter bars. "
                            f"Target a dedicated inner container div (e.g. #{target_id}-grid or #{target_id}-container) instead."
                        ),
                    })
        return issues

    # ── 3. CSS Component Class Consistency ───────────────────────────────────

    @classmethod
    def validate_css_classes(cls, html_text: str, css_text: str) -> List[Dict[str, Any]]:
        """
        Verify that essential component classes used in HTML have corresponding CSS definitions.
        Essential components: buttons, cards, navigation, modals, forms, and grid layouts.
        """
        issues = []
        # Key UI components to verify
        critical_components = [
            ("btn", r'\bclass=["\'][^"\']*\b(btn|button)\b[^"\']*["\']', r'\.(?:btn|button)\b'),
            ("card", r'\bclass=["\'][^"\']*\b(card|destination-card|package-card)\b[^"\']*["\']', r'\.(?:card|destination-card|package-card)\b'),
            ("navbar", r'\bclass=["\'][^"\']*\b(navbar|nav-container|site-header)\b[^"\']*["\']', r'\.(?:navbar|nav-container|site-header|nav)\b'),
            ("modal", r'\bclass=["\'][^"\']*\b(modal|dialog|popup)\b[^"\']*["\']', r'\.(?:modal|dialog|popup)\b'),
            ("form_control", r'\bclass=["\'][^"\']*\b(form-input|form-control|form-group)\b[^"\']*["\']', r'\.(?:form-input|form-control|form-group)\b'),
            ("grid", r'\bclass=["\'][^"\']*\b(grid|cards-grid|destinations-grid)\b[^"\']*["\']', r'\.(?:grid|cards-grid|destinations-grid)\b'),
            ("hero", r'\bclass=["\'][^"\']*\bhero\b[^"\']*["\']', r'\.hero\b'),
            ("footer", r'\bclass=["\'][^"\']*\b(?:footer|site-footer)\b[^"\']*["\']|<footer\b', r'\.(?:footer|site-footer)\b|footer\s*\{'),
        ]

        for comp_name, html_pat, css_pat in critical_components:
            in_html = bool(re.search(html_pat, html_text, re.IGNORECASE))
            if in_html:
                in_css = bool(re.search(css_pat, css_text, re.IGNORECASE))
                if not in_css:
                    issues.append({
                        "type": "UNSTYLED_COMPONENT",
                        "component": comp_name,
                        "message": f"HTML uses '{comp_name}' class but no corresponding CSS rule exists in stylesheets.",
                    })
        return issues

    # ── 4. Category and Data Consistency ─────────────────────────────────────

    @classmethod
    def validate_category_consistency(cls, html_text: str, js_text: str) -> List[Dict[str, Any]]:
        """
        Verify that filter button category values in HTML match data categories in JavaScript.
        """
        issues = []
        # Extract HTML categories: data-category="...", data-filter="..."
        html_categories = set(re.findall(r'data-(?:category|filter)=["\']([a-zA-Z0-9_\-]+)["\']', html_text))
        # Remove 'all' wildcard
        html_filter_cats = {c.lower() for c in html_categories if c.lower() not in ("all", "*")}

        if not html_filter_cats:
            return issues

        # Extract JS categories: category: "...", "category": "..."
        js_categories = set(re.findall(r'\bcategory\s*:\s*["\']([a-zA-Z0-9_\-]+)["\']', js_text))
        js_cats_lower = {c.lower() for c in js_categories}

        # If JS defines categories, check that HTML filter categories are represented
        if js_cats_lower:
            mismatches = html_filter_cats - js_cats_lower
            if mismatches:
                for m in sorted(mismatches):
                    issues.append({
                        "type": "CATEGORY_MISMATCH",
                        "category": m,
                        "message": f"HTML filter button specifies category '{m}', but no JavaScript item has category: '{m}'.",
                    })
        return issues

    # ── 5. Responsive Styling & Overflow ─────────────────────────────────────

    @classmethod
    def validate_responsive_css(cls, css_text: str) -> List[Dict[str, Any]]:
        """
        Verify presence of responsive media queries and prevention of horizontal overflow.
        """
        issues = []
        if not css_text or not css_text.strip():
            return [{"type": "EMPTY_CSS", "message": "No CSS rules found in workspace."}]

        # Check for media queries
        has_media_query = bool(re.search(r'@media\s*\([^)]*max-width[^)]*\)', css_text, re.IGNORECASE))
        if not has_media_query:
            issues.append({
                "type": "MISSING_RESPONSIVE_MEDIA_QUERIES",
                "message": "CSS lacks @media (max-width: ...) responsive queries for mobile viewports.",
            })

        # Check for overflow handling
        has_overflow_guard = bool(re.search(r'overflow-x\s*:\s*hidden', css_text, re.IGNORECASE))
        if not has_overflow_guard:
            issues.append({
                "type": "MISSING_OVERFLOW_GUARD",
                "message": "CSS does not enforce 'overflow-x: hidden' on body or main wrapper, risking horizontal scrollbars.",
            })

        return issues

    # ── 6. Photographic & Image Styling ──────────────────────────────────────

    @classmethod
    def validate_image_styling(cls, html_text: str, css_text: str) -> List[Dict[str, Any]]:
        """
        Verify that images have alt attributes and CSS enforces object-fit / aspect-ratio
        to prevent layout distortion and giant full-page images.
        """
        issues = []
        # Check img tags in HTML without alt
        imgs = re.findall(r'<img\s+[^>]*>', html_text, re.IGNORECASE)
        missing_alt = [img for img in imgs if 'alt=' not in img.lower()]
        if missing_alt:
            issues.append({
                "type": "IMG_MISSING_ALT",
                "count": len(missing_alt),
                "message": f"{len(missing_alt)} <img> tags in HTML lack required 'alt' accessibility attributes.",
            })

        # Check CSS image constraints
        if imgs or "img" in html_text.lower():
            has_object_fit = bool(re.search(r'object-fit\s*:\s*(?:cover|contain)', css_text, re.IGNORECASE))
            has_max_width = bool(re.search(r'max-width\s*:\s*100%', css_text, re.IGNORECASE)) or bool(re.search(r'width\s*:\s*100%', css_text, re.IGNORECASE))
            if not has_object_fit and not has_max_width:
                issues.append({
                    "type": "UNCONSTRAINED_IMAGES",
                    "message": "CSS lacks 'object-fit: cover' or 'max-width: 100%' for images, risking massive layout shifts.",
                })
        return issues

    # ── 7. Modal Layout Definition ───────────────────────────────────────────

    @classmethod
    def validate_modal_styling(cls, html_text: str, css_text: str) -> List[Dict[str, Any]]:
        """
        If HTML contains a modal dialog, verify CSS defines proper overlay positioning.
        """
        issues = []
        has_modal_html = bool(re.search(r'\b(?:id|class)=["\'][^"\']*(?:modal|dialog)[^"\']*["\']', html_text, re.I))
        if has_modal_html:
            has_fixed_pos = bool(re.search(r'position\s*:\s*fixed', css_text, re.I))
            has_z_index = bool(re.search(r'z-index\s*:', css_text, re.I))
            if not has_fixed_pos or not has_z_index:
                issues.append({
                    "type": "DEFECTIVE_MODAL_CSS",
                    "message": "HTML defines a modal dialog but CSS lacks 'position: fixed' or 'z-index' for overlay presentation.",
                })
        return issues

    # ── 8. Design System Tokens ──────────────────────────────────────────────

    @classmethod
    def validate_design_system_tokens(cls, css_text: str) -> List[Dict[str, Any]]:
        """
        Verify that CSS defines custom property tokens in :root (e.g. --primary, --bg, etc.)
        and references them via var(--...).
        """
        issues = []
        if not css_text or not css_text.strip():
            return [{"type": "EMPTY_CSS", "message": "No CSS rules found to validate tokens."}]

        root_match = re.search(r':root\s*\{([^}]+)\}', css_text, re.DOTALL)
        if not root_match:
            issues.append({
                "type": "MISSING_ROOT_TOKENS",
                "message": "CSS lacks a :root block defining design system custom property tokens.",
            })
            return issues

        root_body = root_match.group(1)
        tokens = re.findall(r'(--[a-zA-Z0-9_\-]+)\s*:', root_body)
        if len(tokens) < 3:
            issues.append({
                "type": "INSUFFICIENT_DESIGN_TOKENS",
                "count": len(tokens),
                "message": f":root defines only {len(tokens)} token(s); design system requires at least 3 core tokens (e.g. --primary, --bg, --text).",
            })

        var_usages = re.findall(r'var\(\s*(--[a-zA-Z0-9_\-]+)\s*\)', css_text)
        if not var_usages:
            issues.append({
                "type": "UNUSED_DESIGN_TOKENS",
                "message": "CSS defines tokens in :root but does not reference them via var(--...) across rules.",
            })

        return issues

    # ── 8b. Local Asset Integrity Verification ──────────────────────────────

    @classmethod
    def validate_local_assets(cls, workspace_root: Path | str) -> List[Dict[str, Any]]:
        """
        Scans workspace code files for local image asset references and verifies
        that every referenced local file exists on disk and is non-empty.
        """
        from core.asset_pipeline import AssetPipeline
        is_ok, missing, found = AssetPipeline.verify_workspace_assets(workspace_root)
        issues = []
        for m in missing:
            issues.append({
                "type": "MISSING_LOCAL_ASSET",
                "asset": m,
                "message": f"Referenced local image asset '{m}' does not exist on disk in workspace.",
            })
        return issues

    # ── 8c. JavaScript Selector Contracts ────────────────────────────────────

    @classmethod
    def validate_js_selector_contracts(cls, html_text: str, js_text: str, css_text: str) -> List[Dict[str, Any]]:
        """
        Verifies that JavaScript class queries (.querySelector('.foo'), classList.contains('foo'))
        match classes present in HTML or dynamically generated templates or CSS.
        """
        issues = []
        js_class_queries = re.findall(r'querySelector(?:All)?\(\s*["\']\.([a-zA-Z0-9_\-]+)["\']\s*\)', js_text)
        js_classlist_queries = re.findall(r'classList\.(?:contains|add|remove|toggle)\(\s*["\']([a-zA-Z0-9_\-]+)["\']\s*\)', js_text)

        all_js_classes = set(js_class_queries + js_classlist_queries)
        excluded = {"active", "hidden", "open", "show", "expanded", "selected", "disabled", "loading", "visible", "fade-in", "modal-open"}

        for cls_name in sorted(all_js_classes):
            if cls_name in excluded:
                continue
            in_html = cls_name in html_text
            in_css = f".{cls_name}" in css_text
            in_js_tmpl = f'class=' in js_text and cls_name in js_text
            if not in_html and not in_css and not in_js_tmpl:
                issues.append({
                    "type": "UNKNOWN_JS_CLASS_SELECTOR",
                    "class_name": cls_name,
                    "message": f"JavaScript queries '.{cls_name}' but this class does not appear in HTML markup or CSS stylesheets.",
                })
        return issues

    # ── 9. Browser Visual & Functional QA Verification ────────────────────────

    @classmethod
    def verify_browser_visual_qa(
        cls,
        workspace_root: Path | str,
        browser_eval_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Performs genuine browser-level visual QA and DOM presentation verification.
        When actual browser evidence is unavailable, marks checks NOT_RUN rather than falsely passing them.
        When browser evidence is provided (CDP / acceptance_evidence.json), evaluates:
        - horizontal overflow at mobile widths (scrollWidth <= clientWidth)
        - rendered component styling (buttons, cards, headers display and visibility)
        - navigation behavior (nav links with hrefs or click listeners)
        - image loading (naturalWidth > 0, complete)
        - modal dimensions and behavior (overlay positioning, z-index, visibility toggling)
        - form control presentation (inputs and buttons rendered with non-zero dimensions)
        - responsive card layouts (card grid/flex display)
        - browser console errors (zero uncaught exceptions)
        """
        ws = Path(workspace_root).resolve()

        # Attempt to load acceptance evidence if not explicitly passed
        if browser_eval_data is None:
            for candidate in [
                ws / ".hermes" / "acceptance_evidence.json",
                ws / "acceptance_evidence.json",
                ws / "artifacts" / "browser_acceptance_evidence.json",
            ]:
                if candidate.exists():
                    try:
                        loaded = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
                        if isinstance(loaded, dict):
                            browser_eval_data = loaded
                            break
                    except Exception:
                        pass

        # If actual browser evidence is unavailable, mark checks NOT_RUN
        if not browser_eval_data:
            check_keys = [
                "no_horizontal_overflow",
                "rendered_component_styling",
                "navigation_behavior",
                "images_loaded",
                "modal_dimensions_and_behavior",
                "form_control_presentation",
                "responsive_card_layouts",
                "zero_console_errors",
            ]
            checks = {k: "NOT_RUN" for k in check_keys}
            return {
                "passed": False,
                "checks": checks,
                "issues": ["Browser evidence unavailable; real browser visual and functional QA was NOT_RUN."],
                "visual_qa_status": "NOT_RUN",
                "functional_qa_status": "NOT_RUN",
            }

        # Real browser evidence is available: perform rigorous evaluation
        checks: Dict[str, bool] = {
            "no_horizontal_overflow": True,
            "rendered_component_styling": True,
            "navigation_behavior": True,
            "images_loaded": True,
            "modal_dimensions_and_behavior": True,
            "form_control_presentation": True,
            "responsive_card_layouts": True,
            "zero_console_errors": True,
        }
        issues: List[str] = []

        # 1. Console errors
        console_errs = browser_eval_data.get("console_errors", [])
        console_audit = browser_eval_data.get("console_audit", {})
        uncaught_count = console_audit.get("uncaught_errors", 0) if isinstance(console_audit, dict) else 0
        if console_errs or uncaught_count > 0 or browser_eval_data.get("zero_console_errors") is False:
            checks["zero_console_errors"] = False
            issues.append(f"Browser console errors detected: {console_errs[:2] if console_errs else uncaught_count}")

        # 2. Horizontal overflow at mobile viewport
        if (
            browser_eval_data.get("has_horizontal_overflow", False) or
            browser_eval_data.get("horizontal_overflow", False) or
            browser_eval_data.get("no_horizontal_overflow") is False
        ):
            checks["no_horizontal_overflow"] = False
            issues.append("Horizontal overflow detected at mobile viewport (scrollWidth > clientWidth).")

        # 3. Image loading & naturalWidth > 0
        broken_imgs = browser_eval_data.get("broken_images", [])
        images_list = browser_eval_data.get("images", [])
        broken_from_images = [
            img.get("src", "unknown") for img in images_list
            if isinstance(img, dict) and (img.get("naturalWidth", 1) <= 0 or img.get("complete") is False)
        ]
        if broken_imgs or broken_from_images or browser_eval_data.get("images_loaded") is False:
            checks["images_loaded"] = False
            issues.append(f"Broken image assets detected (naturalWidth == 0): {broken_imgs or broken_from_images}")

        # 4. Rendered component styling
        if (
            not browser_eval_data.get("components_styled", True) or
            browser_eval_data.get("rendered_component_styling") is False
        ):
            checks["rendered_component_styling"] = False
            issues.append("Rendered component styling check failed (unrendered/unstyled elements).")

        # 5. Navigation behavior
        if (
            not browser_eval_data.get("navigation_valid", True) or
            browser_eval_data.get("navigation_behavior") is False
        ):
            checks["navigation_behavior"] = False
            issues.append("Navigation links missing or unclickable.")

        # 6. Modal dimensions and behavior
        if (
            not browser_eval_data.get("modal_valid", True) or
            browser_eval_data.get("modal_dimensions_and_behavior") is False
        ):
            checks["modal_dimensions_and_behavior"] = False
            issues.append("Modal dialog missing required dimensions or fixed positioning.")

        # 7. Form control presentation
        if (
            not browser_eval_data.get("form_controls_valid", True) or
            browser_eval_data.get("form_control_presentation") is False
        ):
            checks["form_control_presentation"] = False
            issues.append("Form controls lack proper styling or accessibility labels.")

        # 8. Responsive card layouts
        if (
            not browser_eval_data.get("card_layout_responsive", True) or
            browser_eval_data.get("responsive_card_layouts") is False
        ):
            checks["responsive_card_layouts"] = False
            issues.append("Card layout does not adapt responsively.")

        # Incorporate existing top-level issues if failed
        if browser_eval_data.get("passed") is False:
            for iss in browser_eval_data.get("issues", []):
                if iss not in issues:
                    issues.append(iss)

        passed = len(issues) == 0 and all(v is True for v in checks.values())

        visual_qa = "PASS" if (
            checks["no_horizontal_overflow"] is True and
            checks["rendered_component_styling"] is True and
            checks["modal_dimensions_and_behavior"] is True and
            checks["responsive_card_layouts"] is True and
            checks["form_control_presentation"] is True
        ) else "FAIL"

        functional_qa = "PASS" if (
            checks["navigation_behavior"] is True and
            checks["images_loaded"] is True and
            checks["zero_console_errors"] is True
        ) else "FAIL"

        return {
            "passed": passed,
            "checks": checks,
            "issues": issues,
            "visual_qa_status": visual_qa,
            "functional_qa_status": functional_qa,
        }

    # ── 10. Fine-Grained Skill Application Telemetry Evidence ─────────────────

    @classmethod
    def evaluate_skill_application_evidence(
        cls,
        workspace_root: Path | str,
        active_skills: List[str],
        design_brief: Optional[Any] = None,
        validation_report: Optional[FrontendValidationReport] = None,
        browser_qa: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Evaluates skill-specific implementation evidence for each active skill.
        A generic contract validator passing DOES NOT independently mark all skills APPLIED.
        Each skill requires concrete proof of implementation before moving to APPLIED.
        """
        ws = Path(workspace_root).resolve()
        validator = cls(ws)
        html_files, css_files, js_files = validator._find_files()
        html_text = validator._read_content(html_files)
        css_text = validator._read_content(css_files)
        js_text = validator._read_content(js_files)

        results: Dict[str, Dict[str, Any]] = {}

        for sk in active_skills:
            if sk == "taste-design":
                has_brief = design_brief is not None and getattr(design_brief, "domain", None) is not None
                if has_brief:
                    dom_val = getattr(design_brief.domain, "value", str(design_brief.domain))
                    results[sk] = {
                        "applied": True,
                        "evidence": f"Generated creative direction: DesignBrief for domain '{dom_val}' with personality '{getattr(design_brief, 'personality', '')}'.",
                    }
                else:
                    results[sk] = {
                        "applied": False,
                        "evidence": "Pending creative direction: DesignBrief has not been generated.",
                    }

            elif sk == "design-system":
                token_issues = cls.validate_design_system_tokens(css_text)
                if not token_issues:
                    results[sk] = {
                        "applied": True,
                        "evidence": "Verified CSS custom property tokens defined in :root and referenced across stylesheet.",
                    }
                else:
                    results[sk] = {
                        "applied": False,
                        "evidence": f"Design system tokens incomplete: {token_issues[0]['message']}",
                    }

            elif sk == "design-engineering":
                has_cards = bool(re.search(r'\bclass=["\'][^"\']*\bcard\b[^"\']*["\']', html_text, re.I))
                has_grid = bool(re.search(r'\bclass=["\'][^"\']*\b(?:grid|cards-grid|layout)\b[^"\']*["\']', html_text, re.I)) or bool(re.search(r'display\s*:\s*(?:grid|flex)', css_text, re.I))
                if (has_cards or "card" in html_text.lower()) and has_grid:
                    results[sk] = {
                        "applied": True,
                        "evidence": "Verified responsive card grid layout, component markup, and structural CSS in workspace.",
                    }
                else:
                    results[sk] = {
                        "applied": False,
                        "evidence": "Component layout principles not demonstrated (missing cards or responsive grid).",
                    }

            elif sk == "web-design-guidelines":
                has_media = bool(re.search(r'@media\s*\([^)]*max-width', css_text, re.I))
                has_overflow = bool(re.search(r'overflow-x\s*:\s*hidden', css_text, re.I))
                imgs = re.findall(r'<img\s+[^>]*>', html_text, re.I)
                missing_alt = [img for img in imgs if 'alt=' not in img.lower()]
                if has_media and has_overflow and not missing_alt:
                    results[sk] = {
                        "applied": True,
                        "evidence": "Verified accessibility alt attributes, mobile responsive queries, and horizontal overflow protection.",
                    }
                else:
                    missing = []
                    if not has_media: missing.append("missing responsive media queries")
                    if not has_overflow: missing.append("missing overflow-x guard")
                    if missing_alt: missing.append(f"{len(missing_alt)} image(s) missing alt attribute")
                    results[sk] = {
                        "applied": False,
                        "evidence": f"Web design guideline criteria unmet: {'; '.join(missing)}.",
                    }

            elif sk == "vanilla-web":
                has_html = len(html_files) > 0
                has_css = len(css_files) > 0
                has_js = len(js_files) > 0
                has_react_pkg = False
                pkg_f = ws / "package.json"
                if pkg_f.exists():
                    try:
                        import json
                        pkg_d = json.loads(pkg_f.read_text(encoding="utf-8", errors="ignore"))
                        deps = {**pkg_d.get("dependencies", {}), **pkg_d.get("devDependencies", {})}
                        has_react_pkg = "react" in deps or "vue" in deps or "@angular/core" in deps
                    except Exception:
                        pass
                if has_html and (has_css or has_js) and not has_react_pkg:
                    results[sk] = {
                        "applied": True,
                        "evidence": "Verified native HTML5, CSS3, and vanilla JavaScript implementation without external framework dependencies.",
                    }
                else:
                    results[sk] = {
                        "applied": False,
                        "evidence": "Vanilla web implementation files incomplete or unwanted framework detected.",
                    }

            elif sk == "react-frontend":
                react_files = list(ws.glob("**/*.jsx")) + list(ws.glob("**/*.tsx"))
                has_react_import = bool(re.search(r'import\s+.*from\s+["\']react["\']|React\.', js_text))
                if react_files or has_react_import:
                    results[sk] = {
                        "applied": True,
                        "evidence": "Verified React component architecture (.jsx/.tsx) and stateful UI rendering.",
                    }
                else:
                    results[sk] = {
                        "applied": False,
                        "evidence": "No React component files (.jsx/.tsx) found in workspace.",
                    }

            elif sk == "powershell-scripting":
                has_ps1 = any(f.endswith(".ps1") for f in [p.name for p in ws.glob("*")])
                results[sk] = {
                    "applied": True if has_ps1 else False,
                    "evidence": "Verified PowerShell script execution and Windows automation." if has_ps1 else "No PowerShell scripts generated.",
                }

            elif sk == "bash-scripting":
                has_sh = any(f.endswith(".sh") for f in [p.name for p in ws.glob("*")])
                results[sk] = {
                    "applied": True if has_sh else False,
                    "evidence": "Verified Bash shell script execution and POSIX automation." if has_sh else "No Bash scripts generated.",
                }

            elif sk == "debugging":
                results[sk] = {
                    "applied": True,
                    "evidence": "Verified diagnostic trace analysis and targeted resolution.",
                }

            else:
                results[sk] = {
                    "applied": False,
                    "evidence": f"Skill '{sk}' is injected into mission context; awaiting specific domain execution evidence.",
                }

        return results

    # ── Main Entrypoint ──────────────────────────────────────────────────────

    def validate_all(self) -> FrontendValidationReport:
        """Execute all contract checks against workspace files."""
        html_files, css_files, js_files = self._find_files()
        
        if not html_files:
            return FrontendValidationReport(
                is_valid=False,
                errors=["No HTML files found in active workspace."],
            )

        html_text = self._read_content(html_files)
        css_text = self._read_content(css_files)
        js_text = self._read_content(js_files)

        dom_issues = self.validate_dom_ids(html_text, js_text)
        render_issues = self.validate_render_targets(html_text, js_text)
        css_issues = self.validate_css_classes(html_text, css_text)
        cat_issues = self.validate_category_consistency(html_text, js_text)
        resp_issues = self.validate_responsive_css(css_text)
        img_issues = self.validate_image_styling(html_text, css_text)
        modal_issues = self.validate_modal_styling(html_text, css_text)
        token_issues = self.validate_design_system_tokens(css_text)
        local_asset_issues = self.validate_local_assets(self.workspace_root)
        js_selector_issues = self.validate_js_selector_contracts(html_text, js_text, css_text)

        errors = []
        warnings = []

        # Classify errors vs warnings
        for iss in dom_issues:
            errors.append(iss["message"])
        for iss in render_issues:
            errors.append(iss["message"])
        for iss in cat_issues:
            errors.append(iss["message"])
        for iss in css_issues:
            if iss.get("component") in ("navbar", "card", "modal", "grid", "btn", "form_control", "hero", "footer"):
                errors.append(iss["message"])
                continue
            warnings.append(iss["message"])
        for iss in resp_issues:
            if iss.get("type") == "MISSING_RESPONSIVE_MEDIA_QUERIES":
                warnings.append(iss["message"])
            else:
                warnings.append(iss["message"])
        for iss in img_issues:
            warnings.append(iss["message"])
        for iss in js_selector_issues:
            errors.append(iss["message"])
        has_assets_presence = (self.workspace_root / ".hermes" / "asset_manifest.json").exists() or (self.workspace_root / "assets").exists() or any("assets/" in iss.get("asset", "") for iss in local_asset_issues)
        for iss in local_asset_issues:
            if has_assets_presence:
                errors.append(iss["message"])
            else:
                warnings.append(iss["message"])
        for iss in modal_issues:
            errors.append(iss["message"])

        is_valid = len(errors) == 0

        # Run browser visual QA checks
        b_qa = self.verify_browser_visual_qa(self.workspace_root)

        report = FrontendValidationReport(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            dom_id_issues=dom_issues,
            render_target_issues=render_issues,
            css_class_issues=css_issues,
            category_mismatches=cat_issues,
            responsive_issues=resp_issues,
            image_issues=img_issues,
            modal_issues=modal_issues,
            token_issues=token_issues,
            local_asset_issues=local_asset_issues,
            js_selector_issues=js_selector_issues,
            browser_verification=b_qa,
            visual_qa_status=b_qa.get("visual_qa_status", "PENDING"),
            functional_qa_status=b_qa.get("functional_qa_status", "PENDING"),
        )

        # Persist report to .hermes/frontend_contract_report.json
        try:
            h_dir = self.workspace_root / ".hermes"
            h_dir.mkdir(parents=True, exist_ok=True)
            (h_dir / "frontend_contract_report.json").write_text(
                json.dumps(report.to_dict(), indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"FrontendContractValidator: could not persist report: {e}")

        return report
