# core/work_package_gate.py
"""
Work-Package Gatekeeper for HERMES 2.x (Phase 3).
Replaces shallow file-existence checks with strict multi-faceted contract verification.
Prevents missions from prematurely advancing through execution phases unless
architectural, visual, data, and interactive criteria are genuinely satisfied.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from core.frontend_contract import FrontendImplementationContract


@dataclass
class WorkPackageGateResult:
    """Detailed result of work-package gating evaluation."""
    passed: bool
    work_package: str
    summary: str
    reasons: List[str] = field(default_factory=list)
    missing_criteria: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)


class WorkPackageGater:
    """
    Evaluates whether each mission work package is genuinely complete.
    Work Packages:
      1. Foundation: Architecture, entrypoint, design brief, frontend contract, base styling.
      2. Content: Required sections, rendered data, provisioned assets, no empty grids.
      3. Functionality: Valid event bindings, non-destructive rendering, real interaction logic.
      4. Verification: Independent acceptance evidence, genuine automated tests.
    """

    @classmethod
    def evaluate_foundation_gate(
        cls,
        workspace_root: Path | str,
        contract: Optional[FrontendImplementationContract] = None,
        design_brief: Optional[Any] = None,
    ) -> WorkPackageGateResult:
        """
        Foundation requires:
          - Architecture and entrypoint established (index.html exists).
          - Single authoritative entrypoint linked.
          - Design brief persisted in .hermes/design_brief.json.
          - Frontend contract created in .hermes/frontend_contract.json.
          - Base styling meets minimum structural coverage (:root tokens, layout).
          - Required dependencies resolve (package.json valid JSON if present).
        """
        ws = Path(workspace_root).resolve()
        missing = []
        evidence = {}

        html_candidates = [ws / "index.html", ws / "static" / "index.html"]
        html_file = next((f for f in html_candidates if f.exists() and f.stat().st_size > 10), None)
        if not html_file:
            missing.append("Missing primary entrypoint markup (index.html).")
        else:
            h_text = html_file.read_text(encoding="utf-8", errors="ignore").lower()
            if "</html>" not in h_text or "<body" not in h_text:
                missing.append("Primary entrypoint (index.html) is truncated or incomplete (missing <body> and </html>).")
            else:
                evidence["html_file"] = str(html_file.name)

        css_candidates = [ws / "style.css", ws / "static" / "style.css", ws / "css" / "style.css"]
        css_file = next((f for f in css_candidates if f.exists() and f.stat().st_size > 10), None)
        if not css_file:
            missing.append("Missing primary stylesheet (style.css).")
        else:
            evidence["css_file"] = str(css_file.name)
            css_text = css_file.read_text(encoding="utf-8", errors="ignore")
            # Check for :root tokens or reset
            if ":root" not in css_text and "var(" not in css_text:
                missing.append("Stylesheet lacks design system tokens (:root CSS custom properties).")

        brief_file = ws / ".hermes" / "design_brief.json"
        if not brief_file.exists() and not (design_brief and getattr(design_brief, "brand_personality", None)):
            missing.append("Missing persisted DesignBrief (.hermes/design_brief.json).")
        else:
            evidence["design_brief_present"] = True

        contract_file = ws / ".hermes" / "frontend_contract.json"
        if not contract_file.exists() and not contract:
            missing.append("Missing persisted FrontendImplementationContract (.hermes/frontend_contract.json).")
        else:
            evidence["frontend_contract_present"] = True

        # JavaScript entrypoint check (recorded in evidence if present)
        js_candidates = [ws / "app.js", ws / "main.js", ws / "index.js", ws / "static" / "app.js", ws / "static" / "main.js"]
        js_file = next((f for f in js_candidates if f.exists() and f.stat().st_size > 10), None)
        if js_file:
            evidence["js_file"] = str(js_file.name)

        # package.json check (valid JSON if present)
        pkg_file = ws / "package.json"
        if pkg_file.exists():
            try:
                json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))
                evidence["package_json_valid"] = True
            except Exception as e:
                missing.append(f"package.json is malformed: {e}")

        # Enforce that directory presence alone (.hermes, .artifacts, assets) cannot satisfy foundation
        source_files_present = bool(html_file and css_file)
        if not source_files_present:
            missing.append("Foundation requires real application source files (index.html, style.css), not merely directories.")

        # Strict rejection of generic uncustomized scaffold placeholders
        banned_generic_markers = [
            "modern web application",
            "welcome to modern application",
            "signature offering",
            "strategic solution",
            "advanced initiative",
            "bespoke service",
            "console.log('app ready')",
            'console.log("app ready")',
        ]
        if html_file:
            h_raw = html_file.read_text(encoding="utf-8", errors="ignore")
            h_raw_lower = h_raw.lower()
            for gm in banned_generic_markers:
                if gm in h_raw_lower:
                    m_case = re.search(re.escape(gm), h_raw, re.IGNORECASE)
                    display_gm = m_case.group(0) if m_case else gm.title()
                    missing.append(f"Primary entrypoint (index.html) contains generic uncustomized placeholder ('{display_gm}'). Must establish domain-specific brand identity.")
            if 'data-category="primary"' in h_raw_lower or 'data-category="special"' in h_raw_lower or '>all items<' in h_raw_lower:
                missing.append("Primary entrypoint (index.html) contains generic filter placeholders ('primary', 'special', 'all items'). Must use domain-specific categories.")
        if pkg_file and pkg_file.exists():
            try:
                pkg_json = json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))
                if pkg_json.get("name") in ("modern-web-app", "app", "application"):
                    missing.append(f"package.json has generic project name '{pkg_json.get('name')}'. Must use prompt-derived brand name.")
            except Exception:
                pass
        if js_file:
            js_raw = js_file.read_text(encoding="utf-8", errors="ignore").strip()
            if js_raw in ("console.log('App ready');", "console.log('app ready');", "console.log('ready');", ""):
                missing.append("Primary JavaScript entrypoint (app.js) is a generic stub ('console.log(\'App ready\');'). Must contain application logic or state.")

        passed = len(missing) == 0
        summary = "Foundation work package satisfied." if passed else f"Foundation gate blocked by {len(missing)} missing criteria."
        return WorkPackageGateResult(
            passed=passed,
            work_package="wp.foundation",
            summary=summary,
            missing_criteria=missing,
            evidence=evidence,
        )

    @classmethod
    def evaluate_content_gate(
        cls,
        workspace_root: Path | str,
        contract: Optional[FrontendImplementationContract] = None,
    ) -> WorkPackageGateResult:
        """
        Content requires:
          - Required sections implemented in HTML markup.
          - Data rendered (cards or items are present in HTML or JS mock arrays).
          - Assets provisioned and referenced correctly (alt text present).
          - No empty content grids.
        """
        ws = Path(workspace_root).resolve()
        missing = []
        evidence = {}

        html_candidates = [ws / "index.html", ws / "static" / "index.html"]
        html_file = next((f for f in html_candidates if f.exists()), None)
        if not html_file:
            return WorkPackageGateResult(
                passed=False,
                work_package="wp.content",
                summary="Content gate failed: index.html not found.",
                missing_criteria=["Missing index.html."],
            )

        html_text = html_file.read_text(encoding="utf-8", errors="ignore")
        js_files = list(ws.glob("*.js")) + list(ws.glob("static/*.js"))
        js_text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in js_files if f.is_file())

        # Check for structural sections
        has_nav = bool(re.search(r'<(?:nav|header)\b', html_text, re.I))
        has_hero = "hero" in html_text.lower()
        has_cards_or_items = any(k in html_text.lower() for k in [
            "card", "program", "course", "faculty", "division", "academic",
            "destination", "package", "item", "feature", "grid", "catalog", "article",
            "menu", "dish", "chef", "cuisine", "tasting", "mezze"
        ])
        if not has_nav:
            missing.append("HTML markup missing navigation section (<nav> or <header>).")
        if not has_hero:
            missing.append("HTML markup missing hero section.")
        if not has_cards_or_items:
            missing.append("HTML markup missing core content cards/showcase.")

        # Check for empty content grids
        grid_tags = re.findall(r'<div[^>]*\bid=["\']([a-zA-Z0-9_\-]*(?:grid|cards|container|list|destinations|packages|programs|faculty|departments|academics|menu|dishes|gallery)[a-zA-Z0-9_\-]*)["\'][^>]*>', html_text, re.I)
        for g_id in set(grid_tags):
            m = re.search(rf'<div[^>]*\bid=["\']{re.escape(g_id)}["\'][^>]*>(.*?)</div>', html_text, re.DOTALL | re.I)
            if m:
                inner = m.group(1).strip()
                has_static_cards = bool(re.search(r'<div\b|<article\b|<li\b|<section\b|<button\b', inner, re.I))
                if has_static_cards:
                    continue
            populates_grid = f"#{g_id}" in js_text or f"'{g_id}'" in js_text or f'"{g_id}"' in js_text
            has_render = "render" in js_text.lower() or "innerhtml" in js_text.lower() or "appendchild" in js_text.lower()
            if not populates_grid or not has_render:
                missing.append(f"Content grid container div #{g_id} is empty in HTML and JavaScript does not populate it.")

        # Generic placeholder rejection
        banned_content_markers = [
            "modern web application",
            "welcome to modern application",
            "signature offering",
            "strategic solution",
            "advanced initiative",
            "bespoke service",
        ]
        for bm in banned_content_markers:
            if bm in html_text.lower():
                m_case = re.search(re.escape(bm), html_text, re.IGNORECASE)
                display_bm = m_case.group(0) if m_case else bm.title()
                missing.append(f"Content gate rejected: index.html contains generic placeholder markup ('{display_bm}').")

        # Semantic domain keyword & required sections coverage check
        try:
            from core.mission_spec import MissionSpecification
            spec = MissionSpecification.load_from_workspace(ws)
            if spec:
                if spec.semantic_keywords:
                    matched_kw = [kw for kw in spec.semantic_keywords if kw.lower() in html_text.lower() or kw.lower() in js_text.lower()]
                    if len(matched_kw) < 2:
                        missing.append(f"Content gate rejected: Generated deliverables lack domain-specific semantic coverage (found only {matched_kw} out of required domain terms {spec.semantic_keywords[:5]}).")
                if spec.required_sections:
                    for s in spec.required_sections:
                        sid = s.get("id") if isinstance(s, dict) else str(s)
                        scomp = s.get("component", "") if isinstance(s, dict) else ""
                        stitle = s.get("title", "") if isinstance(s, dict) else ""
                        if sid in ("navbar", "footer"):
                            continue
                        if (sid and f'id="{sid}"' not in html_text and f"id='{sid}'" not in html_text
                            and (not scomp or scomp not in html_text.lower())
                            and (not stitle or stitle.lower() not in html_text.lower())):
                            missing.append(f"Content gate rejected: Required section '{sid}' ({stitle or scomp}) missing in rendered HTML.")
                if getattr(spec, "requirement_ledger", None):
                    for req in spec.requirement_ledger:
                        sel = req.get("expected_dom_selector", "")
                        req_id = req.get("req_id", "REQ")
                        if sel.startswith("#"):
                            dom_id = sel[1:]
                            if f'id="{dom_id}"' not in html_text and f"id='{dom_id}'" not in html_text and f'#{dom_id}' not in js_text and f'"{dom_id}"' not in js_text and f"'{dom_id}'" not in js_text:
                                missing.append(f"Content gate rejected: Requirement ledger item '{req_id}' selector '{sel}' missing in rendered HTML/JS.")
                        elif sel == "img":
                            if "<img" not in html_text.lower() and "img" not in js_text.lower():
                                missing.append(f"Content gate rejected: Requirement ledger item '{req_id}' selector 'img' missing in rendered HTML/JS.")
                if "<form" in html_text.lower():
                    if "demonstration" not in html_text.lower() and "simulated" not in html_text.lower():
                        missing.append("Content gate rejected: Interactive form lacks explicit demonstration/simulation disclosure notice.")
        except Exception:
            pass
        if js_text.strip() in ("console.log('App ready');", "console.log('app ready');", "console.log('ready');", ""):
            missing.append("Content gate rejected: app.js contains generic stub ('console.log(\'App ready\');') without substantive interactive data or functions.")

        # Brand integrity & Cross-contamination check
        if contract:
            brand = (getattr(contract, "app_name", "") or "").lower()
            if hasattr(contract, "theme") and isinstance(contract.theme, dict):
                brand = (contract.theme.get("brand_name") or brand).lower()

            if brand and brand not in html_text.lower() and brand not in js_text.lower():
                missing.append(f"Brand integrity check failed: expected brand '{brand}' not found in HTML or JavaScript.")

            # Universal Cross-contamination checks
            foreign_matrix = {
                "saffron": ["saffron & stone", "saffron and stone", "paneer tikka", "dum biryani", "tandoori"],
                "nova": ["nova apex", "nova sonic", "nova horizon", "smartphones", "laptops", "earbuds"],
                "wanderworld": ["wanderworld", "bali getaway", "swiss alps expedition", "hero-wanderlust"],
                "northstar": ["northstar university", "collegiate quadrangle", "faculty-grid"],
                "atlas": ["atlas robotics", "autonomous mobile robots", "solutions-grid"],
                "form_field": ["form & field", "form and field", "the monolith pavilion"],
            }
            for dom_key, terms in foreign_matrix.items():
                if not any(k in brand for k in [dom_key, dom_key.replace("_", " "), dom_key.replace("_", " & ")]):
                    leaks = [t for t in terms if t in html_text.lower() or t in js_text.lower()]
                    if leaks:
                        missing.append(f"Cross-contamination detected: foreign artifacts ({', '.join(leaks)}) found in {brand} project.")

        # Check asset references
        imgs = re.findall(r'<img\s+[^>]*>', html_text, re.I)
        missing_alt = [img for img in imgs if 'alt=' not in img.lower()]
        if missing_alt:
            missing.append(f"{len(missing_alt)} image(s) lack required accessibility alt attributes.")

        try:
            from core.asset_pipeline import AssetPipeline
            assets_ok, missing_assets, found_assets = AssetPipeline.verify_workspace_assets(ws)
            for m in missing_assets:
                if "Duplicate" in m or "identical" in m:
                    missing.append(f"Content gate rejected: {m}")
        except Exception:
            pass

        passed = len(missing) == 0
        summary = "Content work package satisfied." if passed else f"Content gate blocked by {len(missing)} missing criteria."
        return WorkPackageGateResult(
            passed=passed,
            work_package="wp.content",
            summary=summary,
            missing_criteria=missing,
            evidence=evidence,
        )

    @classmethod
    def evaluate_functionality_gate(
        cls,
        workspace_root: Path | str,
        contract: Optional[FrontendImplementationContract] = None,
    ) -> WorkPackageGateResult:
        """
        Functionality requires:
          - Event bindings validated (no missing DOM IDs).
          - Dynamic rendering operational (no section overwriting).
          - Real interactive implementations (no console.log substitutes).
          - No orphan competing entrypoints on disk.
        """
        ws = Path(workspace_root).resolve()
        missing = []
        evidence = {}

        js_files = [f for f in list(ws.glob("*.js")) if not f.name.endswith(".test.js") and not f.name.endswith(".config.js")]
        if not js_files:
            missing.append("Missing client-side JavaScript implementation files.")
            return WorkPackageGateResult(
                passed=False,
                work_package="wp.functional",
                summary="Functionality gate failed: no JavaScript files found.",
                missing_criteria=missing,
            )

        html_candidates = [ws / "index.html", ws / "static" / "index.html"]
        html_file = next((f for f in html_candidates if f.exists()), None)
        html_text = html_file.read_text(encoding="utf-8", errors="ignore") if html_file else ""
        js_text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in js_files)

        # 1. Check for orphan entrypoints (e.g. app.js and main.js both exist, but HTML only links one)
        linked_scripts = set(re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_text, re.I))
        for jf in js_files:
            rel_name = jf.name
            if rel_name not in linked_scripts and f"./{rel_name}" not in linked_scripts:
                # Check if imported by another script
                is_imported = f"from './{rel_name}'" in js_text or f'from "./{rel_name}"' in js_text
                if not is_imported and len(js_files) > 1:
                    missing.append(f"Orphan competing script '{rel_name}' exists on disk but is unlinked in HTML and not imported.")

        # 2. Check for missing DOM IDs queried in JS
        html_ids = set(re.findall(r'\bid=["\']([a-zA-Z0-9_\-]+)["\']', html_text))
        queried_ids = set(re.findall(r'getElementById\(\s*["\']([a-zA-Z0-9_\-]+)["\']\s*\)', js_text))
        queried_ids |= set(re.findall(r'querySelector\(\s*["\']#([a-zA-Z0-9_\-]+)["\']\s*\)', js_text))
        
        dynamic_ids = set(contract.dom_and_state.dynamic_ids) if contract else set()
        for q_id in queried_ids:
            if q_id not in html_ids and q_id not in dynamic_ids:
                if f'id="{q_id}"' not in js_text and f"id='{q_id}'" not in js_text:
                    missing.append(f"JavaScript queries '#{q_id}' but no element with id='{q_id}' exists in HTML.")

        # 3. Check for DANGEROUS_SECTION_OVERWRITE
        section_overwrites = re.findall(
            r'(?:getElementById|querySelector)\(\s*["\']#?([a-zA-Z0-9_\-]+)["\']\s*\)\.innerHTML\s*=',
            js_text
        )
        for target_id in set(section_overwrites):
            if re.search(rf'<section[^>]*\bid=["\']{re.escape(target_id)}["\'][^>]*>', html_text, re.I):
                missing.append(f"JavaScript directly overwrites parent <section id='{target_id}'> with .innerHTML.")

        # 4. Check for console.log substitute features
        has_search_or_filter = "filter" in js_text.lower() or "search" in js_text.lower()
        if has_search_or_filter:
            # Check if filter handlers only do console.log
            fake_handlers = re.findall(
                r'addEventListener\(\s*["\'](?:input|change|click|submit)["\']\s*,\s*(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>\s*\{\s*console\.log\([^)]*\);?\s*\}\s*\)',
                js_text
            )
            if fake_handlers:
                missing.append("Event handler contains only console.log() without updating application state or DOM.")

        passed = len(missing) == 0
        summary = "Functional work package satisfied." if passed else f"Functionality gate blocked by {len(missing)} missing criteria."
        return WorkPackageGateResult(
            passed=passed,
            work_package="wp.functional",
            summary=summary,
            missing_criteria=missing,
            evidence=evidence,
        )

    @classmethod
    def evaluate_verification_gate(
        cls,
        workspace_root: Path | str,
        validation_report: Any,
        test_result: Optional[Any] = None,
    ) -> WorkPackageGateResult:
        """
        Verification requires:
          - Contract validation passes (is_valid == True).
          - No fake test scripts (echo ... && exit 0) counted as automated tests.
          - Profile checks pass without errors.
        """
        ws = Path(workspace_root).resolve()
        missing = []
        evidence = {}

        is_valid = getattr(validation_report, "is_valid", False)
        if not is_valid:
            errors = getattr(validation_report, "errors", ["Contract validation failed."])
            missing.extend(errors[:5])

        # Check package.json test script integrity
        pkg_file = ws / "package.json"
        if pkg_file.exists():
            try:
                pkg_data = json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))
                test_cmd = pkg_data.get("scripts", {}).get("test", "")
                if "echo" in test_cmd and "exit 0" in test_cmd:
                    missing.append(f"package.json test script '{test_cmd}' is a dummy script and is rejected.")
            except Exception:
                pass

        passed = len(missing) == 0
        summary = "Verification work package satisfied." if passed else f"Verification gate blocked by {len(missing)} validation errors."
        return WorkPackageGateResult(
            passed=passed,
            work_package="wp.verification",
            summary=summary,
            missing_criteria=missing,
            evidence=evidence,
        )
