# core/integration_validator.py
"""
Cross-Artifact Integration Validator for HERMES.
Enforces structural coherence across deliverables:
  - Web: Verifies HTML element IDs match CSS selectors and JS DOM queries;
         verifies referenced scripts/styles exist on disk.
  - Python: Verifies internal module imports, symbol definitions, and syntax.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


@dataclass
class StructuredDefect:
    """Detailed record of a structured validation defect."""
    kind: str
    target_file: str
    counterpart_file: Optional[str]
    message: str
    severity: str = "blocking"
    missing_id: Optional[str] = None
    action_directive: str = ""
    postcondition: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "target_file": self.target_file,
            "counterpart_file": self.counterpart_file,
            "message": self.message,
            "severity": self.severity,
            "missing_id": self.missing_id,
            "action_directive": self.action_directive,
            "postcondition": self.postcondition,
        }


@dataclass
class IntegrationReport:
    """Outcome of a cross-artifact integration validation."""
    valid: bool
    task_type: str  # "web", "python", "general"
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    defects: List[StructuredDefect] = field(default_factory=list)
    fingerprint: str = ""

    def __post_init__(self):
        if not self.fingerprint and self.issues:
            canonical = json.dumps(sorted(self.issues))
            self.fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    @property
    def summary(self) -> str:
        if self.valid:
            warn_str = f" ({len(self.warnings)} warning(s))" if self.warnings else ""
            return f"Integration valid for {self.task_type}{warn_str}"
        return f"Integration failed for {self.task_type}: {len(self.issues)} issue(s): {'; '.join(self.issues[:3])}"


class CrossArtifactValidator:
    """Validates structural and referential integrity between project files."""

    @classmethod
    def validate_web_integration(cls, workspace_root: Path) -> IntegrationReport:
        """
        Validate cross-artifact coherence for web projects:
        1. HTML references exist on disk (scripts and stylesheets).
        2. CSS ID selectors match HTML element IDs.
        3. JavaScript DOM lookups (getElementById, querySelector) match HTML IDs.
        """
        ws = Path(workspace_root)
        issues: List[str] = []
        warnings: List[str] = []
        details: Dict[str, Any] = {}

        html_files = list(ws.glob("*.html")) + list(ws.glob("src/**/*.html"))
        if not html_files:
            return IntegrationReport(
                valid=True,
                task_type="web",
                warnings=["No HTML files found to validate"],
                details={"html_files": 0},
            )

        # Primary HTML
        primary_html = ws / "index.html" if (ws / "index.html").exists() else html_files[0]
        html_txt = ""
        try:
            html_txt = primary_html.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return IntegrationReport(
                valid=False,
                task_type="web",
                issues=[f"Failed to read primary HTML file {primary_html.name}: {e}"],
            )

        # 1. Extract HTML IDs, Classes, and Form Control Names
        html_ids: Set[str] = set(re.findall(r'\bid=["\']([a-zA-Z0-9_\-]+)["\']', html_txt))
        html_classes: Set[str] = set()
        for cls_match in re.findall(r'\bclass=["\']([^"\']+)["\']', html_txt):
            for c in cls_match.split():
                if c.strip():
                    html_classes.add(c.strip())

        html_form_names: Set[str] = set(re.findall(r'\bname=["\']([a-zA-Z0-9_\-]+)["\']', html_txt))

        details["html_ids_count"] = len(html_ids)
        details["html_classes_count"] = len(html_classes)
        details["html_form_names_count"] = len(html_form_names)

        # 2. Check script tags
        script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_txt, re.I)
        details["referenced_scripts"] = script_srcs
        for src in script_srcs:
            if src.startswith(("http://", "https://", "//")):
                continue
            clean_src = src.lstrip("/").lstrip("./")
            script_path = ws / clean_src
            if not script_path.exists():
                issues.append(f"Broken script reference in {primary_html.name}: '{src}' not found on disk")
            elif script_path.stat().st_size == 0:
                issues.append(f"Referenced script '{src}' exists but is empty (0 bytes)")

        # 3. Check link stylesheets
        css_hrefs = re.findall(r'<link[^>]+(?:rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\']|href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet["\'])', html_txt, re.I)
        flattened_hrefs = [h[0] or h[1] for h in css_hrefs if (h[0] or h[1])]
        details["referenced_stylesheets"] = flattened_hrefs
        for href in flattened_hrefs:
            if href.startswith(("http://", "https://", "//")):
                continue
            clean_href = href.lstrip("/").lstrip("./")
            css_path = ws / clean_href
            if not css_path.exists():
                issues.append(f"Broken stylesheet reference in {primary_html.name}: '{href}' not found on disk")
            elif css_path.stat().st_size == 0:
                issues.append(f"Referenced stylesheet '{href}' exists but is empty (0 bytes)")

        # 4. Check CSS ID selectors against HTML IDs
        css_files = list(ws.glob("*.css")) + list(ws.glob("src/**/*.css"))
        css_ids: Set[str] = set()
        for cf in css_files:
            try:
                c_txt = cf.read_text(encoding="utf-8", errors="ignore")
                # Strip comments
                c_clean = re.sub(r'/\*.*?\*/', '', c_txt, flags=re.DOTALL)
                # Match #identifier
                found = re.findall(r'#([a-zA-Z][a-zA-Z0-9_\-]*)', c_clean)
                for fid in found:
                    # Ignore hex color codes (3, 6, or 8 hex characters following : or in values)
                    css_ids.add(fid)
            except Exception:
                pass

        # Exclude common hex color false-positives
        filtered_css_ids = {i for i in css_ids if not (len(i) in (3, 6, 8) and all(c in "0123456789abcdefABCDEF" for c in i))}
        details["css_ids_count"] = len(filtered_css_ids)

        if html_ids and filtered_css_ids:
            common_ids = html_ids.intersection(filtered_css_ids)
            details["common_ids_count"] = len(common_ids)
            # If CSS specifies 5+ IDs and less than 10% match HTML IDs, strong indicator of mismatched layout
            if len(filtered_css_ids) >= 5:
                match_ratio = len(common_ids) / len(filtered_css_ids)
                if match_ratio < 0.15 and len(common_ids) <= 2:
                    mismatched_css = list(filtered_css_ids - html_ids)[:5]
                    issues.append(
                        f"HTML/CSS layout ID mismatch: only {len(common_ids)} of {len(filtered_css_ids)} CSS IDs match HTML. "
                        f"CSS targets non-existent IDs like: {mismatched_css}. Ensure style.css matches index.html element IDs."
                    )
                elif match_ratio < 0.4:
                    warnings.append(
                        f"Partial CSS ID mismatch: {len(common_ids)} of {len(filtered_css_ids)} IDs matched HTML."
                    )

        # 5. Check JS DOM queries
        js_files = [ws / "main.js", ws / "src/main.js", ws / "app.js", ws / "src/app.js"]
        for jf in js_files:
            if jf.exists() and jf.stat().st_size > 0:
                try:
                    j_txt = jf.read_text(encoding="utf-8", errors="ignore")
                    # getElementById
                    geb_ids = re.findall(r'getElementById\(["\']([a-zA-Z0-9_\-]+)["\']\)', j_txt)
                    for gid in geb_ids:
                        if html_ids and gid not in html_ids:
                            issues.append(
                                f"JavaScript DOM mismatch: {jf.name} calls getElementById('{gid}'), but #{gid} does not exist in {primary_html.name}"
                            )

                    # querySelector('#id')
                    qs_ids = re.findall(r'querySelector(?:All)?\(["\']#([a-zA-Z0-9_\-]+)["\']\)', j_txt)
                    for qid in qs_ids:
                        if html_ids and qid not in html_ids:
                            issues.append(
                                f"JavaScript DOM mismatch: {jf.name} queries '#{qid}', but #{qid} does not exist in {primary_html.name}"
                            )

                    # FormData name lookups
                    has_form_elements = ("<form" in html_txt.lower() or "<input" in html_txt.lower())
                    fd_gets = re.findall(r'formData\.get\(["\']([a-zA-Z0-9_\-]+)["\']\)', j_txt)
                    for fd in fd_gets:
                        if has_form_elements and fd not in html_form_names:
                            issues.append(
                                f"FormData name mismatch: {jf.name} accesses formData.get('{fd}'), but no form input/select/textarea in {primary_html.name} has name='{fd}'"
                            )

                    # Placeholder / Stub logic detection in domain functions
                    if "function calculateCategoryProgress" in j_txt or "calculateCategoryProgress = " in j_txt or "calculateCategoryProgress(" in j_txt:
                        if re.search(r'calculateCategoryProgress[^{]*\{[^}]*(?:return\s+(?:50|100|0\.5|\[\])|TODO|placeholder)', j_txt, re.I):
                            issues.append(
                                f"Incomplete placeholder function in {jf.name}: calculateCategoryProgress contains static placeholder logic instead of calculating real category totals"
                            )
                except Exception:
                    pass

        # 6. Check package.json entrypoint agreement
        pkg_path = ws / "package.json"
        if pkg_path.exists():
            try:
                pkg_data = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
                pkg_main = pkg_data.get("main")
                if pkg_main and isinstance(pkg_main, str):
                    clean_pkg_main = pkg_main.lstrip("./")
                    if not (ws / clean_pkg_main).exists() and any((ws / f).exists() for f in ("main.js", "app.js", "index.js")):
                        issues.append(
                            f"Package entrypoint mismatch: package.json specifies main='{pkg_main}', but '{clean_pkg_main}' does not exist on disk"
                        )
            except Exception:
                pass

        # Convert issues to StructuredDefects
        defects: List[StructuredDefect] = []
        for iss in issues:
            target_f = primary_html.name
            c_part = None
            k = "general"
            m_id = None
            act = "Repair the identified cross-file discrepancy."
            post = "File references and element IDs match exactly."

            if "JavaScript DOM mismatch" in iss:
                k = "missing_dom_id"
                match_id = re.search(r"calls getElementById\('([^']+)'\)|queries '#([^']+)'", iss)
                if match_id:
                    m_id = match_id.group(1) or match_id.group(2)
                match_js = re.search(r"(\w+\.js)", iss)
                c_part = match_js.group(1) if match_js else "app.js"
                target_f = c_part
                act = f"Update '{c_part}' to use the correct DOM ID from {primary_html.name}, or add #{m_id} to {primary_html.name}."
                post = f"DOM element #{m_id} is correctly bound between HTML and JS."
            elif "Broken script reference" in iss:
                k = "missing_script_file"
                match_script = re.search(r"'([^']+)' not found on disk", iss)
                missing_s = match_script.group(1) if match_script else "app.js"
                target_f = missing_s
                c_part = primary_html.name
                act = f"Create '{missing_s}' using fs.write with full implementation as referenced in {primary_html.name}."
                post = f"Script '{missing_s}' exists on disk and is non-empty."
            elif "FormData name mismatch" in iss:
                k = "form_data_mismatch"
                match_name = re.search(r"formData\.get\('([^']+)'\)", iss)
                f_name = match_name.group(1) if match_name else "field"
                target_f = primary_html.name
                match_js = re.search(r"(\w+\.js)", iss)
                c_part = match_js.group(1) if match_js else "app.js"
                act = f"Add name='{f_name}' to the corresponding form input/select in {primary_html.name} so {c_part} can read it."
                post = f"Form input with name='{f_name}' exists in {primary_html.name}."
            elif "Incomplete placeholder" in iss:
                k = "placeholder_stub"
                match_js = re.search(r"(\w+\.js)", iss)
                target_f = match_js.group(1) if match_js else "app.js"
                act = f"Implement real calculations in '{target_f}' instead of returning static placeholder values."
                post = f"Function in '{target_f}' computes dynamic values."
            elif "Package entrypoint mismatch" in iss:
                k = "package_mismatch"
                target_f = "package.json"
                act = "Align package.json 'main' with the actual JavaScript file on disk."
                post = "package.json entrypoint exists on disk."

            defects.append(
                StructuredDefect(
                    kind=k,
                    target_file=target_f,
                    counterpart_file=c_part,
                    message=iss,
                    severity="blocking",
                    missing_id=m_id,
                    action_directive=act,
                    postcondition=post,
                )
            )

        canonical = json.dumps(sorted(issues))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16] if issues else ""

        is_valid = len(issues) == 0
        return IntegrationReport(
            valid=is_valid,
            task_type="web",
            issues=issues,
            warnings=warnings,
            details=details,
            defects=defects,
            fingerprint=fingerprint,
        )

    @classmethod
    def validate_python_integration(cls, workspace_root: Path) -> IntegrationReport:
        """
        Validate cross-artifact coherence for Python projects:
        1. All .py files parse into valid AST without SyntaxError.
        2. Local intra-workspace imports resolve to existing modules and exported symbols.
        """
        ws = Path(workspace_root)
        issues: List[str] = []
        warnings: List[str] = []
        details: Dict[str, Any] = {}

        py_files = [f for f in ws.glob("**/*.py") if "venv" not in f.parts and ".git" not in f.parts]
        details["python_files_count"] = len(py_files)
        if not py_files:
            return IntegrationReport(
                valid=True,
                task_type="python",
                warnings=["No Python files found to validate"],
                details=details,
            )

        module_asts: Dict[str, ast.AST] = {}
        module_exports: Dict[str, Set[str]] = {}

        # First pass: parse AST and collect defined functions, classes, and top-level names
        for pf in py_files:
            rel_mod = pf.relative_to(ws).with_suffix("").as_posix().replace("/", ".")
            try:
                code_txt = pf.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(code_txt, filename=pf.name)
                module_asts[rel_mod] = tree

                # Simple name: e.g. "calculator" from "tests/test_calculator.py" or "calculator.py"
                simple_mod = pf.stem
                exports: Set[str] = set()
                for node in ast.iter_child_nodes(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        exports.add(node.name)
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                exports.add(target.id)

                module_exports[rel_mod] = exports
                if simple_mod not in module_exports:
                    module_exports[simple_mod] = exports
            except SyntaxError as syn_err:
                issues.append(f"Python syntax error in {pf.name} (line {syn_err.lineno}): {syn_err.msg}")
            except Exception as exc:
                issues.append(f"Failed to parse Python file {pf.name}: {exc}")

        # Second pass: check imports across local modules
        for pf in py_files:
            rel_mod = pf.relative_to(ws).with_suffix("").as_posix().replace("/", ".")
            tree = module_asts.get(rel_mod)
            if not tree:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    mod_name = node.module or ""
                    # Check if imported module matches a local file
                    matching_mod = None
                    if mod_name in module_exports:
                        matching_mod = mod_name
                    elif mod_name.split(".")[-1] in module_exports:
                        matching_mod = mod_name.split(".")[-1]

                    if matching_mod:
                        avail = module_exports[matching_mod]
                        for alias in node.names:
                            sym = alias.name
                            if sym != "*" and sym not in avail:
                                issues.append(
                                    f"Import mismatch in {pf.name}: '{sym}' imported from '{mod_name}', "
                                    f"but '{mod_name}' does not define '{sym}' (available: {sorted(list(avail))[:6]})"
                                )

        is_valid = len(issues) == 0
        return IntegrationReport(
            valid=is_valid,
            task_type="python",
            issues=issues,
            warnings=warnings,
            details=details,
        )

    @classmethod
    def validate_workspace(
        cls,
        workspace_root: Path,
        prompt: Optional[str] = None,
    ) -> IntegrationReport:
        """Auto-detect workspace type and execute appropriate integration validation."""
        ws = Path(workspace_root)
        prompt_lower = (prompt or "").lower()

        is_web = (ws / "index.html").exists() or any(k in prompt_lower for k in ("website", "web page", "html", "three.js", "frontend"))
        is_python = any(ws.glob("*.py")) or any(k in prompt_lower for k in ("python", "pytest", "cli"))

        if is_web:
            return cls.validate_web_integration(ws)
        elif is_python:
            return cls.validate_python_integration(ws)

        return IntegrationReport(valid=True, task_type="general", details={"status": "no_specific_validator"})
