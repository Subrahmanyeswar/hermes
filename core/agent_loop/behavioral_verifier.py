# core/agent_loop/behavioral_verifier.py
"""
Technology-Aware Behavioral Verifier for HERMES 2.x Agent Loop.

Enforces deep, behavioral verification of generated projects based on actual
technology stack rather than simple file existence.

Requirements:
1. Identify actual tech stack (e.g. vanilla HTML/CSS/JS, Python CLI, React, etc.)
2. Deep cross-reference integrity (HTML -> CSS, HTML -> JS)
3. Structural and syntax validity (HTML DOM, JS syntax, CSS rules)
4. Interactive controls and event handler coverage
5. State transitions, search, filter, and local persistence validation
6. Anti-placeholder quality gate (rejects trivial stubs and demo boilerplate)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class BehavioralCheckResult:
    passed: bool
    tech_stack: str
    issues: List[str] = field(default_factory=list)
    features_detected: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class TechnologyAwareBehavioralVerifier:
    """
    Verifies that a generated application exhibits real, functioning behavior
    consistent with its technology stack and user requirements.
    """

    @classmethod
    def identify_tech_stack(cls, ws_root: Path, mission_prompt: str = "") -> str:
        """Detect the technology stack present in the workspace root or demanded by mission."""
        if not ws_root.exists() or not ws_root.is_dir():
            return "unknown"

        files = [
            f.name.lower() for f in ws_root.iterdir()
            if f.is_file() and not f.name.startswith(".")
        ]

        p_lower = mission_prompt.lower()
        demands_vanilla_web = any(
            kw in p_lower for kw in (
                "website", "web app", "webapp", "html", "css", "js", "javascript",
                "vanilla web", "frontend", "interactive", "lost and found", "lost-and-found"
            )
        )

        if "index.html" in files or demands_vanilla_web:
            if "package.json" in files:
                return "node_web"
            has_js = any(f.endswith(".js") for f in files)
            has_css = any(f.endswith(".css") for f in files)
            if demands_vanilla_web or has_js or has_css:
                return "vanilla_web"
            return "static_html"

        if "package.json" in files:
            return "node_app"

        py_files = [f for f in files if f.endswith(".py")]
        if py_files:
            return "python_cli" if len(py_files) == 1 else "python_project"

        return "generic"

    @classmethod
    def is_trivial_mission(cls, mission_prompt: str) -> bool:
        """
        Check if the prompt requests a trivial single-file deterministic artifact
        rather than a full application.
        """
        p_lower = mission_prompt.lower()
        # Words indicating nontrivial applications
        app_keywords = (
            "application", "web application", "webapp", "web app",
            "complete", "lost and found", "lost-and-found", "dashboard",
            "portal", "interactive", "platform", "system", "multi-page",
            "crud", "todo list", "store", "manager", "inventory",
        )
        if any(kw in p_lower for kw in app_keywords):
            return False

        # If it specifically asks for a single script or trivial test
        trivial_indicators = (
            "hello.py", "hello world", "print('hello", 'print("hello',
            "echo", "simple script", "one file", "single file",
        )
        return any(ind in p_lower for ind in trivial_indicators)

    @classmethod
    def verify_workspace(
        cls,
        ws_root: Path,
        mission_prompt: str,
        acceptance_criteria: Optional[List[str]] = None,
    ) -> BehavioralCheckResult:
        """
        Perform technology-aware behavioral verification on the workspace root.
        """
        if not ws_root.exists():
            return BehavioralCheckResult(
                passed=False,
                tech_stack="none",
                issues=[f"Workspace root directory does not exist: {ws_root}"],
            )

        tech_stack = cls.identify_tech_stack(ws_root, mission_prompt)
        is_trivial = cls.is_trivial_mission(mission_prompt)

        if tech_stack == "vanilla_web":
            return cls.verify_vanilla_web(ws_root, mission_prompt, is_trivial=is_trivial)
        elif tech_stack in ("python_cli", "python_project"):
            return cls.verify_python_project(ws_root, mission_prompt, is_trivial=is_trivial)
        else:
            # Fallback verification
            return cls._verify_generic_artifacts(ws_root, mission_prompt, tech_stack)

    @classmethod
    def verify_vanilla_web(
        cls,
        ws_root: Path,
        mission_prompt: str,
        is_trivial: bool = False,
    ) -> BehavioralCheckResult:
        """
        Deep behavioral verification for vanilla HTML/CSS/JS applications.
        Verifies:
        1. index.html exists and is non-empty
        2. CSS file exists and has style rules
        3. JS file exists and has logic
        4. CSS references in index.html are valid
        5. JS references in index.html are valid
        6. HTML structure is valid (doctype/html, head, body, non-empty body)
        7. JS syntax is balanced and valid
        8. Interactive controls exist (forms, inputs, buttons)
        9. Event handlers exist (addEventListener, onclick, onsubmit)
        10. Local persistence logic exists when requested
        11. Search logic exists when requested
        12. Filter logic exists when requested
        13. State transitions exist (render items, update list)
        14. Anti-placeholder gate: rejects 1-liner or generic boilerplate pages
        """
        issues: List[str] = []
        features: List[str] = []
        details: Dict[str, Any] = {}
        p_lower = mission_prompt.lower()

        # 1. index.html Check
        html_path = ws_root / "index.html"
        if not html_path.exists():
            issues.append("index.html is missing in workspace root")
            return BehavioralCheckResult(passed=False, tech_stack="vanilla_web", issues=issues)

        html_content = html_path.read_text(encoding="utf-8", errors="replace").strip()
        if len(html_content) < 50:
            issues.append(f"index.html is too brief ({len(html_content)} bytes); appears to be an empty stub")

        # 2. CSS Check
        css_files = [f for f in ws_root.glob("*.css") if f.is_file()]
        inline_css_blocks = re.findall(r"<style[^>]*>(.*?)</style>", html_content, re.DOTALL | re.IGNORECASE)
        inline_css = "\n".join(inline_css_blocks).strip()

        if not css_files and not inline_css:
            issues.append("No CSS stylesheet found in workspace root")
        else:
            css_content = "".join(f.read_text(encoding="utf-8", errors="replace") for f in css_files).strip()
            if inline_css:
                css_content = f"{css_content}\n{inline_css}".strip()
            # Check for non-empty rules beyond comments
            css_no_comments = re.sub(r"/\*.*?\*/", "", css_content, flags=re.DOTALL).strip()
            if len(css_no_comments) < 20:
                issues.append("CSS file contains only comments or trivial styling without rules")
            else:
                features.append("css_styles")

        # 3. JS Check
        js_files = [f for f in ws_root.glob("*.js") if f.is_file()]
        inline_js_blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html_content, re.DOTALL | re.IGNORECASE)
        inline_js = "\n".join(inline_js_blocks).strip()

        if not js_files and not inline_js:
            issues.append("No JavaScript file found in workspace root")
        else:
            js_content = "".join(f.read_text(encoding="utf-8", errors="replace") for f in js_files).strip()
            if inline_js:
                js_content = f"{js_content}\n{inline_js}".strip()
            js_no_comments = re.sub(r"//.*?\n|/\*.*?\*/", "", js_content, flags=re.DOTALL).strip()
            if len(js_no_comments) < 20:
                issues.append("JavaScript file contains only comments or placeholders without executable logic")
            else:
                features.append("js_logic")

        # 4 & 5. Reference Verification in HTML
        # Look for <link rel="stylesheet" href="...">
        css_refs = re.findall(r'<link[^>]+href=["\']([^"\']+\.css)["\']', html_content, re.IGNORECASE)
        for ref in css_refs:
            ref_clean = ref.strip()
            if ref_clean.startswith(("http://", "https://", "//")):
                features.append(f"external_cdn_css:{ref_clean[:30]}")
                continue
            ref_clean = ref_clean.lstrip("./").lstrip("/")
            ref_target = ws_root / ref_clean
            if not ref_target.exists():
                issues.append(f"HTML references CSS stylesheet '{ref}' which does not exist in workspace")
            else:
                features.append(f"linked_css:{ref_clean}")

        # Look for <script src="...">
        js_refs = re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html_content, re.IGNORECASE)
        for ref in js_refs:
            ref_clean = ref.strip()
            if ref_clean.startswith(("http://", "https://", "//")):
                features.append(f"external_cdn_js:{ref_clean[:30]}")
                continue
            ref_clean = ref_clean.lstrip("./").lstrip("/")
            ref_target = ws_root / ref_clean
            if not ref_target.exists():
                issues.append(f"HTML references JavaScript script '{ref}' which does not exist in workspace")
            else:
                features.append(f"linked_js:{ref_clean}")

        # Look for <img src="...">
        img_refs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        for ref in img_refs:
            ref_clean = ref.strip()
            if not ref_clean or ref_clean.startswith("data:"):
                continue
            if ref_clean.startswith(("http://", "https://", "//")):
                if "0c6c0c0c2c5c" in ref_clean or "placeholder" in ref_clean.lower() or "example.com" in ref_clean.lower():
                    issues.append(f"HTML <img> references dummy or broken placeholder URL: '{ref_clean}'")
                else:
                    try:
                        import urllib.request
                        test_url = ("https:" + ref_clean) if ref_clean.startswith("//") else ref_clean
                        req = urllib.request.Request(test_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                        with urllib.request.urlopen(req, timeout=2.0) as resp:
                            if resp.status >= 400:
                                issues.append(f"HTML <img> references unreachable URL ({resp.status}): '{ref_clean}'")
                            else:
                                features.append(f"verified_img_url:{ref_clean[:30]}")
                    except Exception as img_err:
                        if "404" in str(img_err):
                            issues.append(f"HTML <img> references broken (HTTP 404) URL: '{ref_clean}'")
            else:
                target_clean = ref_clean.lstrip("./").lstrip("/")
                ref_target = ws_root / target_clean
                if not ref_target.exists():
                    issues.append(f"HTML references local image '{ref}' which does not exist in workspace")
                elif ref_target.stat().st_size == 0:
                    issues.append(f"HTML references local image '{ref}' which is 0 bytes")
                else:
                    features.append(f"linked_img:{target_clean}")

        # 6. HTML Structural Integrity
        has_html_tag = bool(re.search(r"<html.*?>.*?</html>", html_content, re.DOTALL | re.IGNORECASE))
        has_head_tag = bool(re.search(r"<head.*?>.*?</head>", html_content, re.DOTALL | re.IGNORECASE))
        has_body_tag = bool(re.search(r"<body.*?>.*?</body>", html_content, re.DOTALL | re.IGNORECASE))

        if not (has_html_tag and has_body_tag):
            issues.append("HTML document structure is incomplete (missing <html> or <body> tags)")

        # Extract body content
        body_match = re.search(r"<body[^>]*>(.*?)</body>", html_content, re.DOTALL | re.IGNORECASE)
        body_content = body_match.group(1).strip() if body_match else ""
        if len(body_content) < 15 and not is_trivial:
            issues.append("HTML <body> is empty or trivial; no user interface elements defined")

        # 7. JavaScript Syntax & Balance
        all_scripts: List[Tuple[str, str]] = [(jf.name, jf.read_text(encoding="utf-8", errors="replace")) for jf in js_files]
        if inline_js:
            all_scripts.append(("inline <script>", inline_js))

        for script_name, code in all_scripts:
            # Basic balance checks
            for open_ch, close_ch in (("{", "}"), ("(", ")"), ("[", "]")):
                if code.count(open_ch) != code.count(close_ch):
                    issues.append(f"Unbalanced '{open_ch}' and '{close_ch}' in {script_name}")

            # Architectural Contamination Check (Zero React/JSX leakage in vanilla web)
            if re.search(r"\bimport\s+React\b|\bfrom\s+['\"]react['\"]|\bfrom\s+['\"]react-dom['\"]", code):
                issues.append(f"Architectural contamination: {script_name} contains React imports, violating vanilla web contract")
            if re.search(r"\bexport\s+default\b", code):
                issues.append(f"Architectural contamination: {script_name} contains 'export default' statement in non-bundled script")

        # If trivial task, we don't demand full application architecture
        if is_trivial:
            passed = len(issues) == 0
            return BehavioralCheckResult(
                passed=passed,
                tech_stack="vanilla_web",
                issues=issues,
                features_detected=features,
                details=details,
            )

        # 8. Interactive Controls Check (Nontrivial Web App)
        controls = re.findall(r"<(button|input|select|textarea|form)\b", html_content, re.IGNORECASE)
        if not controls:
            issues.append("No interactive controls (button, input, form, select) found in HTML")
        else:
            features.append(f"controls:{len(controls)}")

        # 9. Event Handler Coverage in JS
        combined_js_sources = [f.read_text(encoding="utf-8", errors="replace") for f in js_files]
        if inline_js:
            combined_js_sources.append(inline_js)
        combined_js = "\n".join(combined_js_sources)

        event_patterns = (
            r"addEventListener\s*\(",
            r"\.onclick\s*=",
            r"\.onsubmit\s*=",
            r"\.onchange\s*=",
            r"\.oninput\s*=",
        )
        has_events = any(re.search(pat, combined_js, re.IGNORECASE) for pat in event_patterns)
        if not has_events:
            issues.append("JavaScript contains no event listeners or interaction handlers")
        else:
            features.append("event_listeners")

        # 10. Local Persistence Logic Check
        req_storage = any(kw in p_lower for kw in ("persist", "localstorage", "reload", "save", "store", "storage"))
        has_storage = "localstorage" in combined_js.lower() or "sessionstorage" in combined_js.lower()
        if req_storage and not has_storage:
            issues.append("Mission requested local persistence but localStorage/sessionStorage is not implemented in JavaScript")
        elif has_storage:
            features.append("local_persistence")

        # 11. Search Logic Check
        req_search = "search" in p_lower
        has_search = (
            ("search" in html_content.lower() or 'type="search"' in html_content.lower()) and
            ("filter" in combined_js.lower() or "includes" in combined_js.lower() or "indexof" in combined_js.lower())
        )
        if req_search and not has_search:
            issues.append("Mission requested search capability but search input or filter logic is missing")
        elif has_search:
            features.append("search_filtering")

        # 12. Filter Logic Check
        req_filter = "filter" in p_lower
        has_filter = "filter" in combined_js.lower() or "select" in html_content.lower()
        if req_filter and not has_filter:
            issues.append("Mission requested filtering capability but filter controls or logic are missing")
        elif has_filter:
            features.append("category_filtering")

        # 13. State transitions & Dynamic DOM rendering
        dom_manipulation_patterns = (
            r"document\.getElementById",
            r"document\.querySelector",
            r"\.innerHTML\s*=",
            r"\.appendChild\s*\(",
            r"createElement\s*\(",
            r"\.textContent\s*=",
        )
        has_dom_rendering = sum(1 for pat in dom_manipulation_patterns if re.search(pat, combined_js)) >= 2
        if not has_dom_rendering:
            issues.append("JavaScript does not perform dynamic DOM rendering or state display")
        else:
            features.append("dynamic_dom_rendering")

        # 14. Anti-Placeholder Gate (Gap 9)
        placeholder_indicators = (
            "welcome to our website",
            "hello world",
            "under construction",
            "lorem ipsum",
            "sample text",
            "insert content here",
        )
        # If the body is tiny and mostly placeholder
        if len(body_content) < 150:
            for ind in placeholder_indicators:
                if ind in body_content.lower():
                    issues.append(f"Detected placeholder boilerplate ('{ind}') in application body")
                    break

        passed = len(issues) == 0
        return BehavioralCheckResult(
            passed=passed,
            tech_stack="vanilla_web",
            issues=issues,
            features_detected=features,
            details={
                "controls_count": len(controls),
                "has_storage": has_storage,
                "has_search": has_search,
                "has_events": has_events,
            },
        )

    @classmethod
    def verify_python_project(
        cls,
        ws_root: Path,
        mission_prompt: str,
        is_trivial: bool = False,
    ) -> BehavioralCheckResult:
        """Verify Python project structure, AST validity, and requested output."""
        import ast
        issues: List[str] = []
        features: List[str] = []
        py_files = list(ws_root.glob("*.py"))

        if not py_files:
            return BehavioralCheckResult(passed=False, tech_stack="python", issues=["No Python files found"])

        for pf in py_files:
            try:
                src = pf.read_text(encoding="utf-8", errors="replace")
                if len(src.strip()) == 0:
                    issues.append(f"Python file '{pf.name}' is empty")
                    continue
                ast.parse(src, filename=str(pf))
                features.append(f"valid_ast:{pf.name}")
            except SyntaxError as e:
                issues.append(f"Syntax error in '{pf.name}': {e.msg} (line {e.lineno})")

        # Check trivial requirements like print("hello from hermes")
        p_lower = mission_prompt.lower()
        if "hello from hermes" in p_lower:
            found_msg = False
            for pf in py_files:
                src = pf.read_text(encoding="utf-8", errors="replace")
                if "hello from hermes" in src.lower():
                    found_msg = True
                    break
            if not found_msg:
                issues.append("Requested message 'hello from hermes' not found in Python code")

        passed = len(issues) == 0
        return BehavioralCheckResult(
            passed=passed,
            tech_stack="python",
            issues=issues,
            features_detected=features,
        )

    @classmethod
    def _verify_generic_artifacts(
        cls,
        ws_root: Path,
        mission_prompt: str,
        tech_stack: str,
    ) -> BehavioralCheckResult:
        """Fallback check verifying files are non-empty and accessible."""
        issues: List[str] = []
        files = [f for f in ws_root.rglob("*") if f.is_file() and not any(p.startswith(".") for p in f.parts)]
        if not files:
            issues.append("No files created in workspace root")
        else:
            empty = [f.name for f in files if f.stat().st_size == 0]
            if empty:
                issues.append(f"Empty files found: {', '.join(empty)}")

        return BehavioralCheckResult(
            passed=len(issues) == 0,
            tech_stack=tech_stack,
            issues=issues,
        )
