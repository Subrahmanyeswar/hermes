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
            warnings.append(iss["message"])
        for iss in resp_issues:
            if iss.get("type") == "MISSING_RESPONSIVE_MEDIA_QUERIES":
                warnings.append(iss["message"])
            else:
                warnings.append(iss["message"])
        for iss in img_issues:
            warnings.append(iss["message"])
        for iss in modal_issues:
            errors.append(iss["message"])

        is_valid = len(errors) == 0

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
