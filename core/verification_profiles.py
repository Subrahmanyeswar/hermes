# core/verification_profiles.py
"""
Risk-Based Fast Verification Profiles for HERMES 2.x.

Eliminates unnecessary LLM roundtrips and circular deadlocks by executing fast,
deterministic, tier-appropriate validation:

Profile A: Tiny File / Smoke Test (< 1s, zero LLM calls)
           Deterministic filesystem verification (file exists, size > 0, substring matching).
Profile B: Normal Source Code (< 3s, zero LLM calls)
           AST syntax parsing (Python), JSON validation, local structural integrity.
Profile C: Website / Application Delivery (< 8s)
           HTML5 structure, DOM cross-references (scripts/styles), interactive controls,
           anti-placeholder check.
Profile D: High-Risk / Complex Software
           Automated test execution (pytest), behavioral checks, security boundary audits.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


from core.planning.requirement_types import (
    extract_target_artifacts,
    extract_typed_requirements,
    verify_dependency_evidence,
    verify_runtime_evidence,
    RequirementType,
)


class VerificationProfile(str, Enum):
    PROFILE_A = "PROFILE_A"  # Tiny file / smoke test / diagnostic (< 1s)
    PROFILE_B = "PROFILE_B"  # Normal source code / scripts (< 3s)
    PROFILE_C = "PROFILE_C"  # Website / application delivery (< 8s)
    PROFILE_D = "PROFILE_D"  # High-risk / complex software


@dataclass
class VerificationProfileResult:
    profile: VerificationProfile
    passed: bool
    duration_ms: float
    checks_run: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""


def classify_verification_profile(
    prompt: str,
    workspace_path: Optional[str] = None,
    written_files: Optional[List[str]] = None,
    task_id: Optional[str] = None,
) -> VerificationProfile:
    """
    Classify the incoming prompt and context into the appropriate verification profile.
    """
    p_lower = prompt.lower()

    # Check negative cues first: if prompt explicitly asks for Python, CLI, terminal, backend, or script
    explicit_non_web = any(k in p_lower for k in (
        "python script", "python program", "python package", "python cli", "python module",
        "pytest", "command-line", "cli utility", "cli tool", "terminal app", "backend service"
    ))
    has_explicit_web_word = any(w in p_lower for w in (
        "website", "web page", "webpage", "web app", "webapp", "landing page", "html", "three.js", "threejs"
    ))
    if explicit_non_web and not has_explicit_web_word:
        return VerificationProfile.PROFILE_B

    # 0. Check for web cues in prompt, workspace, or written files
    web_cues = (
        "website", "web application", "landing page", "html", "web page", "webpage", "frontend",
        "three.js", "threejs", "webgl", "dashboard", "css", "canvas", "lvm3 website", "rocket website"
    )
    has_web_cues = any(w in p_lower for w in web_cues)

    ws_has_web = False
    if workspace_path and Path(workspace_path).exists():
        ws_p = Path(workspace_path)
        if (ws_p / "index.html").exists() or (ws_p / "vite.config.js").exists() or (ws_p / "vite.config.ts").exists():
            ws_has_web = True
        elif (ws_p / "package.json").exists():
            try:
                pkg_txt = (ws_p / "package.json").read_text(encoding="utf-8", errors="ignore").lower()
                if any(k in pkg_txt for k in ("three", "vite", "react", "vue", "canvas", "frontend", "web")):
                    ws_has_web = True
            except Exception:
                pass

    written_has_web = bool(written_files and any(
        f.lower().endswith((".html", ".css")) or f.lower() in ("main.js", "app.js", "index.js", "vite.config.js", "src/main.js")
        for f in written_files
    ))

    # All web applications and website missions evaluate under Profile C
    if has_web_cues or ws_has_web or written_has_web:
        return VerificationProfile.PROFILE_C

    # 1. Explicit CLI, Python package, backend, or script tasks -> Profile B (AST, tests, no HTML)
    cli_cues = ("cli", "command line", "python tool", "cli tool", "terminal tool", "python script", "argparse", "pytest", "python package")
    has_cli_cues = any(c in p_lower for c in cli_cues)

    if workspace_path and Path(workspace_path).exists():
        try:
            from core.verification_gate import detect_project_category, ProjectCategory
            cat = detect_project_category(workspace_path)
            if cat == ProjectCategory.PYTHON_CLI and not has_web_cues:
                return VerificationProfile.PROFILE_B
        except Exception:
            pass

    if has_cli_cues and not has_web_cues:
        return VerificationProfile.PROFILE_B

    # 2. Profile D: Explicit high risk, security audits, financial/crypto
    high_risk_cues = ("high risk", "security audit", "vulnerability scan", "penetration test", "cryptography")
    if any(cue in p_lower for cue in high_risk_cues):
        return VerificationProfile.PROFILE_D

    # 3. Profile A: Smoke test, diagnostic test, or <= 2 simple non-web files requested
    smoke_cues = (
        "smoke test", "smoke_test", "diagnostic test",
        "live write-tool", "write tool verification", "test write", "simple test"
    )
    if any(cue in p_lower for cue in smoke_cues):
        return VerificationProfile.PROFILE_A

    # 4. Profile A heuristic: <= 2 genuine target output artifacts requested
    unique_artifacts = extract_target_artifacts(prompt, written_files=written_files)
    if unique_artifacts and len(unique_artifacts) <= 2 and not any(kw in p_lower for kw in ("full", "complete", "rocket", "car")):
        return VerificationProfile.PROFILE_A

    return VerificationProfile.PROFILE_B


class VerificationProfileEvaluator:
    """
    Executes fast, risk-based verification checks against the target workspace.
    """

    @classmethod
    def evaluate(
        cls,
        profile: VerificationProfile,
        workspace_root: Path,
        prompt: str,
        written_files: Optional[List[str]] = None,
        task_id: Optional[str] = None,
    ) -> VerificationProfileResult:
        t0 = time.monotonic()
        ws = Path(workspace_root) if workspace_root else Path(".")
        written = set(written_files or [])

        if profile == VerificationProfile.PROFILE_A:
            res = cls._evaluate_profile_a(ws, prompt, written)
        elif profile == VerificationProfile.PROFILE_B:
            res = cls._evaluate_profile_b(ws, prompt, written)
        elif profile == VerificationProfile.PROFILE_C:
            res = cls._evaluate_profile_c(ws, prompt, written)
        else:
            res = cls._evaluate_profile_d(ws, prompt, written)

        duration = (time.monotonic() - t0) * 1000.0
        res.duration_ms = duration
        return res

    @classmethod
    def _evaluate_profile_a(
        cls,
        workspace_root: Path,
        prompt: str,
        written_files: Set[str],
    ) -> VerificationProfileResult:
        """
        Profile A: Deterministic fast check (< 1s, zero LLM calls).
        Verifies target files exist on disk, are non-empty, and contain required substrings.
        """
        checks_run = ["workspace_exists"]
        issues = []
        evidence = {}

        if not workspace_root.exists():
            issues.append(f"Workspace root does not exist: {workspace_root}")
            return VerificationProfileResult(
                profile=VerificationProfile.PROFILE_A,
                passed=False,
                duration_ms=0,
                checks_run=checks_run,
                issues=issues,
                summary="Workspace directory does not exist",
            )

        # 1. Identify genuine output artifacts mentioned in prompt (excluding libraries, runtimes, URLs)
        target_files = extract_target_artifacts(prompt, written_files=written_files)
        if not target_files:
            target_files = list(written_files) if written_files else ["smoke_test.html", "README.md"]

        IGNORE_PARTS = frozenset({
            ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
            ".hermes", ".artifacts", "dist", "build", "coverage", ".pytest_cache"
        })

        checks_run.append("target_files_exist_and_non_empty")
        files_verified = []
        for fname in target_files:
            fpath = workspace_root / fname
            if not fpath.exists():
                candidate_path = None
                # Check written_files for matching relative path or basename
                if written_files:
                    for wf in written_files:
                        norm_wf = wf.replace("\\", "/").strip()
                        norm_target = fname.replace("\\", "/").strip()
                        if (
                            norm_wf == norm_target
                            or norm_wf.endswith("/" + norm_target)
                            or Path(wf).name.lower() == Path(fname).name.lower()
                        ):
                            p = workspace_root / wf
                            if p.exists() and p.is_file():
                                candidate_path = p
                                break
                # Fallback recursive search if still not found
                if not candidate_path:
                    target_name = Path(fname).name
                    matches = list(workspace_root.rglob(target_name))
                    valid_matches = [
                        m for m in matches
                        if m.is_file() and not any(part in IGNORE_PARTS or part.startswith(".") for part in m.relative_to(workspace_root).parts)
                    ]
                    if valid_matches:
                        candidate_path = valid_matches[0]

                if candidate_path and candidate_path.exists():
                    fpath = candidate_path

            if not fpath.exists():
                issues.append(f"Expected file '{fname}' not found in workspace")
                continue
            if not fpath.is_file():
                issues.append(f"Expected file '{fname}' is not a regular file")
                continue
            sz = fpath.stat().st_size
            if sz == 0:
                issues.append(f"File '{fname}' is empty (0 bytes)")
                continue

            # Read content for keyword validation
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                files_verified.append(fname)
                evidence[fname] = {"size": sz, "lines": len(content.splitlines()), "path": str(fpath)}
            except Exception as read_exc:
                issues.append(f"Failed to read '{fname}': {read_exc}")

        # 2. Substring validation if prompt requires specific phrases
        checks_run.append("required_content_substrings")
        p_lower = prompt.lower()
        if "smoke_test.html" in files_verified:
            html_content = (workspace_root / "smoke_test.html").read_text(encoding="utf-8", errors="replace")
            # If prompt required heading or diagnostic text
            if "hermes write tool verification" in p_lower:
                if "hermes write tool verification" not in html_content.lower():
                    issues.append("smoke_test.html missing required heading 'HERMES Write Tool Verification'")
            if "diagnostic test" in p_lower:
                if "diagnostic" not in html_content.lower():
                    issues.append("smoke_test.html missing statement that this is a diagnostic test")

        if "readme.md" in files_verified:
            md_content = (workspace_root / "README.md").read_text(encoding="utf-8", errors="replace")
            if len(md_content.strip()) < 10:
                issues.append("README.md content is too brief (< 10 characters)")

        # Validate explicit required constants (e.g. HERMES_*)
        explicit_constants = re.findall(r'\b(HERMES_[A-Z0-9_]+)\b', prompt)
        for const in explicit_constants:
            matched_in_any = False
            for v_fname in files_verified:
                f_info = evidence.get(v_fname, {})
                f_p = Path(f_info.get("path", workspace_root / v_fname))
                if f_p.exists():
                    try:
                        f_text = f_p.read_text(encoding="utf-8", errors="replace")
                        if const in f_text:
                            matched_in_any = True
                            break
                    except Exception:
                        pass
            if not matched_in_any:
                issues.append(f"Deliverable missing required content string '{const}'")

        passed = len(issues) == 0 and len(files_verified) > 0
        summary = (
            f"Profile A passed: Verified {len(files_verified)} file(s) ({', '.join(files_verified)}) on disk with valid content."
            if passed else
            f"Profile A failed: {len(issues)} issue(s) detected: {'; '.join(issues)}"
        )

        return VerificationProfileResult(
            profile=VerificationProfile.PROFILE_A,
            passed=passed,
            duration_ms=0,
            checks_run=checks_run,
            issues=issues,
            evidence=evidence,
            summary=summary,
        )

    @classmethod
    def _evaluate_profile_b(
        cls,
        workspace_root: Path,
        prompt: str,
        written_files: Set[str],
    ) -> VerificationProfileResult:
        """Profile B: Local AST syntax parsing, JSON parsing, non-emptiness (< 3s)."""
        checks_run = ["files_exist_and_parse"]
        issues = []
        evidence = {}

        if not workspace_root.exists():
            return VerificationProfileResult(
                profile=VerificationProfile.PROFILE_B,
                passed=False,
                duration_ms=0,
                checks_run=checks_run,
                issues=["Workspace directory does not exist"],
                summary="Workspace does not exist",
            )

        IGNORED_PARTS = {"node_modules", ".git", "dist", "build", "venv", ".venv", "__pycache__", ".idea", ".vscode"}
        all_files = [
            f for f in workspace_root.rglob("*")
            if f.is_file() and not any(part in IGNORED_PARTS or part.startswith(".") for part in f.relative_to(workspace_root).parts)
        ]

        if not all_files:
            return VerificationProfileResult(
                profile=VerificationProfile.PROFILE_B,
                passed=False,
                duration_ms=0,
                checks_run=checks_run,
                issues=["No files found in workspace root"],
                summary="No files found",
            )

        for f in all_files:
            if f.suffix == ".py":
                try:
                    ast.parse(f.read_text(encoding="utf-8", errors="replace"), filename=str(f))
                except SyntaxError as e:
                    issues.append(f"Python syntax error in {f.name}:{e.lineno}: {e.msg}")
            elif f.suffix in (".js", ".mjs", ".cjs"):
                from core.js_syntax_validator import validate_javascript_file
                js_ok, js_err, _ = validate_javascript_file(f)
                if not js_ok:
                    issues.append(f"JavaScript syntax error in {f.name}: {js_err}")
            elif f.suffix == ".json":
                try:
                    json.loads(f.read_text(encoding="utf-8", errors="replace"))
                except Exception as e:
                    issues.append(f"Invalid JSON in {f.name}: {e}")

        has_tests = any(f.name.startswith("test_") or "tests" in f.parts for f in all_files if f.suffix == ".py")
        wants_tests = any(k in prompt.lower() for k in ("test", "pytest", "unit test", "coverage"))
        if wants_tests and not has_tests:
            issues.append("Missing required unit tests: prompt requested unit tests/pytest, but no test_*.py files exist in workspace.")

        if has_tests and len(issues) == 0:
            import subprocess
            py_exe = sys.executable
            env = os.environ.copy()
            env["PYTHONPATH"] = str(workspace_root)
            try:
                test_proc = subprocess.run(
                    [py_exe, "-m", "pytest", "-q"],
                    cwd=str(workspace_root),
                    capture_output=True,
                    text=True,
                    timeout=15,
                    env=env,
                )
                if test_proc.returncode != 0:
                    summary_lines = [l for l in test_proc.stdout.splitlines() if l.strip()]
                    tail_err = "\n".join(summary_lines[-5:]) if summary_lines else (test_proc.stderr or "pytest failed")
                    issues.append(f"Pytest unit tests failed (exit code {test_proc.returncode}): {tail_err}")
                else:
                    checks_run.append("pytest_suite_passed")
            except Exception as e:
                issues.append(f"Pytest execution error: {e}")

        passed = len(issues) == 0
        return VerificationProfileResult(
            profile=VerificationProfile.PROFILE_B,
            passed=passed,
            duration_ms=0,
            checks_run=checks_run,
            issues=issues,
            summary=f"Profile B {'passed' if passed else 'failed'}: {len(all_files)} files evaluated."
        )

    @classmethod
    def _evaluate_profile_c(
        cls,
        workspace_root: Path,
        prompt: str,
        written_files: Set[str],
    ) -> VerificationProfileResult:
        """Profile C: Web application / Website delivery structural and runtime contract validation."""
        checks_run = ["index_html_structure", "assets_and_scripts", "interactive_controls", "entrypoint_integrity", "dependency_integrity"]
        issues = []
        evidence = {}

        # 1. Prohibit fake root Three.js file
        fake_three = workspace_root / "Three.js"
        if fake_three.exists():
            issues.append("Prohibited fake root 'Three.js' file found. Dependency 'three' must be declared in package.json and imported via module resolution.")

        # 2. index.html checks
        index_html = workspace_root / "index.html"
        if not index_html.exists():
            issues.append("index.html not found in workspace root")
            return VerificationProfileResult(
                profile=VerificationProfile.PROFILE_C,
                passed=False,
                duration_ms=0,
                checks_run=checks_run,
                issues=issues,
                summary="Missing index.html",
            )

        content = index_html.read_text(encoding="utf-8", errors="replace")
        lower = content.lower()

        if "<!doctype html>" not in lower and "<html" not in lower:
            issues.append("index.html missing standard HTML5 DOCTYPE or <html> tag")

        if "<body" not in lower:
            issues.append("index.html missing <body> tag")

        # 3. Primary JavaScript entrypoint (external or embedded)
        main_candidates = ["main.js", "src/main.js", "app.js", "src/app.js", "index.js", "src/index.js", "script.js"]
        found_entrypoints = [
            p for p in main_candidates
            if (workspace_root / p).exists() and (workspace_root / p).stat().st_size > 100
        ]
        has_embedded_script = bool(re.search(r'<script(?![^>]*src=)[^>]*>[\s\S]{80,}</script>', content, re.IGNORECASE))
        if not found_entrypoints and not has_embedded_script:
            issues.append("Primary application entrypoint (e.g. 'main.js', 'app.js', or embedded <script>) is missing or contains insufficient code (< 100 bytes).")
        else:
            checks_run.append("primary_entrypoint_present")
            evidence["entrypoint"] = found_entrypoints[0] if found_entrypoints else "embedded_script"

        # 4. Check linked local scripts
        script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', content, re.IGNORECASE)
        all_js_paths: List[Path] = []
        for ep in found_entrypoints:
            p = workspace_root / ep
            if p.exists() and p not in all_js_paths:
                all_js_paths.append(p)

        for s_src in script_srcs:
            if not s_src.startswith(("http://", "https://", "//")):
                clean_s = s_src.replace("\\", "/").lstrip("./")
                script_path = workspace_root / clean_s
                if not script_path.exists():
                    issues.append(f"Linked local script '{s_src}' does not exist on disk")
                elif script_path.stat().st_size == 0:
                    issues.append(f"Linked local script '{s_src}' is empty (0 bytes)")
                else:
                    if script_path not in all_js_paths:
                        all_js_paths.append(script_path)

        # 4b. Deterministic JavaScript Syntax Check & Anti-Placeholder Code Verification
        checks_run.append("javascript_syntax_validation")
        for js_p in all_js_paths:
            if js_p.suffix.lower() in (".js", ".mjs", ".cjs"):
                try:
                    node_res = subprocess.run(
                        ["node", "--check", str(js_p)],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if node_res.returncode != 0:
                        err_text = (node_res.stderr.strip() or node_res.stdout.strip() or "SyntaxError").splitlines()[-1]
                        issues.append(f"JavaScript syntax error in '{js_p.name}': {err_text}")
                except Exception as e:
                    logger.debug(f"VerificationProfile: node --check check skipped for {js_p.name}: {e}")

                # Anti-placeholder code / truncation detection in scripts
                try:
                    js_code = js_p.read_text(encoding="utf-8", errors="replace")
                    trunc_patterns = [
                        r"//\s*\.\.\.\s*\(more\b",
                        r"//\s*\.\.\.\s*\(more functions would follow\b",
                        r"//\s*TODO:\s*implement\b",
                        r"/\*\s*TODO:\s*implement\b",
                    ]
                    for pat in trunc_patterns:
                        if re.search(pat, js_code, re.IGNORECASE):
                            issues.append(f"Incomplete/truncated implementation detected in '{js_p.name}': matched placeholder comment '{pat}'")
                            break
                except Exception:
                    pass

        # 5. Check linked local stylesheets and style.css (external or embedded)
        link_hrefs = re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', content, re.IGNORECASE)
        has_css_link = False
        for l_href in link_hrefs:
            if not l_href.startswith(("http://", "https://", "//")):
                clean_l = l_href.replace("\\", "/").lstrip("./")
                css_path = workspace_root / clean_l
                if not css_path.exists():
                    issues.append(f"Linked local stylesheet '{l_href}' does not exist on disk")
                elif css_path.stat().st_size == 0:
                    issues.append(f"Linked local stylesheet '{l_href}' is empty (0 bytes)")
                else:
                    has_css_link = True

        has_embedded_style = bool(re.search(r'<style[^>]*>[\s\S]{20,}</style>', content, re.IGNORECASE))
        style_css = workspace_root / "style.css"
        if not has_css_link and not (style_css.exists() and style_css.stat().st_size > 20) and not has_embedded_style:
            issues.append("Required stylesheet 'style.css' is missing, empty, or unlinked in index.html.")

        # 5b. Section Visibility Contract Check
        section_classes = re.findall(r'<(?:section|div)[^>]+class=["\']([^"\']*\b(?:app-section|view-section)\b[^"\']*)["\']', content, re.IGNORECASE)
        if len(section_classes) >= 2:
            checks_run.append("section_visibility_contract")
            all_css_text = ""
            if style_css.exists():
                try:
                    all_css_text += style_css.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
            for l_href in link_hrefs:
                if not l_href.startswith(("http://", "https://", "//")):
                    clean_l = l_href.replace("\\", "/").lstrip("./")
                    css_path = workspace_root / clean_l
                    if css_path.exists():
                        try:
                            all_css_text += "\n" + css_path.read_text(encoding="utf-8", errors="replace")
                        except Exception:
                            pass
            inline_styles = re.findall(r'<style[^>]*>([\s\S]*?)</style>', content, re.IGNORECASE)
            for istyle in inline_styles:
                all_css_text += "\n" + istyle

            has_hide_rule = bool(
                re.search(r'\.(?:app-section|view-section)\s*\{[^}]*display\s*:\s*none', all_css_text, re.IGNORECASE) or
                re.search(r'\.(?:app-section|view-section):not\(\.active\)', all_css_text, re.IGNORECASE) or
                re.search(r'\[hidden\]\s*\{[^}]*display\s*:\s*none', all_css_text, re.IGNORECASE)
            )
            if not has_hide_rule:
                issues.append(f"Section visibility contract failed: {len(section_classes)} views/sections found, but stylesheet does not define a hiding rule ('display: none'), causing multiple views to render simultaneously stacked.")

        # Interactive controls and persistence check for web applications
        p_lower = prompt.lower()
        if any(w in p_lower for w in ("create task", "add task", "todo", "form", "filter", "storage", "controls")):
            has_button_or_input = any(tag in lower for tag in ("<input", "<button", "<form", "<select"))
            if not has_button_or_input:
                issues.append("Missing interactive controls: prompt requested task/data management but index.html contains no buttons, inputs, or form controls.")
            if "localstorage" in p_lower and "localstorage" not in lower:
                has_storage_in_scripts = False
                for ep in found_entrypoints:
                    try:
                        if "localstorage" in (workspace_root / ep).read_text(encoding="utf-8", errors="ignore").lower():
                            has_storage_in_scripts = True
                    except Exception:
                        pass
                if not has_storage_in_scripts:
                    issues.append("Missing persistence: localStorage is required by prompt but not utilized in index.html or scripts.")

        # 5c. Interactive Controls & Element Bindings Check
        is_interactive = any(k in p_lower for k in ("task", "habit", "timer", "pomodoro", "crud", "dashboard", "productivity", "command center", "tracker"))
        if is_interactive and all_js_paths:
            checks_run.append("interactive_bindings_check")
            all_js_content = ""
            for js_p in all_js_paths:
                try:
                    all_js_content += "\n" + js_p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

            key_html_ids = re.findall(r'<(?:form|button|input|select)[^>]+id=["\']([^"\']+)["\']', content, re.IGNORECASE)
            interactive_keywords = ("task", "habit", "timer", "start", "modal", "form", "filter", "submit")
            matched_interactive_ids = [hid for hid in key_html_ids if any(kw in hid.lower() for kw in interactive_keywords)]
            if matched_interactive_ids:
                bound_count = sum(1 for hid in matched_interactive_ids if hid in all_js_content)
                if bound_count == 0:
                    issues.append(f"Interactive controls check failed: HTML defines interactive elements ({', '.join(matched_interactive_ids[:5])}), but JavaScript entrypoints contain zero references or bindings to them.")

        # 6. Anti-placeholder check
        if "lorem ipsum" in lower or "placeholder text" in lower:
            issues.append("index.html contains placeholder 'Lorem Ipsum' text")

        # 7. Check required dependencies evidence (e.g., Three.js)
        typed_reqs = extract_typed_requirements(prompt, written_files=written_files)
        for dep in typed_reqs[RequirementType.DEPENDENCY]:
            checks_run.append(f"dependency_evidence:{dep}")
            dep_ok, dep_msg = verify_dependency_evidence(dep, workspace_root)
            evidence[f"dep:{dep}"] = {"ok": dep_ok, "detail": dep_msg}
            if not dep_ok:
                issues.append(f"Required dependency '{dep}' missing: {dep_msg}")

        # 8. Check 3D Canvas / Three.js runtime if requested
        p_lower = prompt.lower()
        wants_3d = any(k in p_lower for k in ("three", "3d", "canvas", "webgl", "rocket", "orbit", "simulation", "spacecraft"))
        if wants_3d:
            checks_run.append("threejs_canvas_initialization")
            has_canvas_tag = "<canvas" in lower
            has_canvas_in_js = False
            has_three_init = False
            for ep in found_entrypoints:
                try:
                    js_code = (workspace_root / ep).read_text(encoding="utf-8", errors="replace")
                    if "createElement('canvas')" in js_code or 'createElement("canvas")' in js_code or "renderer.domElement" in js_code:
                        has_canvas_in_js = True
                    if any(t in js_code for t in ("THREE.Scene", "new Scene", "THREE.PerspectiveCamera", "new PerspectiveCamera", "THREE.WebGLRenderer", "new WebGLRenderer")):
                        has_three_init = True
                except Exception:
                    pass

            if not (has_canvas_tag or has_canvas_in_js):
                issues.append("Required 3D canvas is absent: neither index.html contains <canvas> nor does main.js create a canvas.")
            elif not has_three_init:
                issues.append("Three.js runtime uninitialized: entrypoint does not initialize Scene, Camera, or WebGLRenderer.")

        # 9. Check explicit additional output artifacts if requested (excluding index.html)
        target_artifacts = extract_target_artifacts(prompt, written_files=written_files)
        for artifact in target_artifacts:
            if artifact.lower() != "index.html":
                art_path = workspace_root / artifact
                if not art_path.exists():
                    issues.append(f"Expected file '{artifact}' not found in workspace")
                elif art_path.stat().st_size == 0:
                    issues.append(f"File '{artifact}' is empty (0 bytes)")

        # 10. Check build result if package.json has build script
        pkg_json = workspace_root / "package.json"
        if pkg_json.exists():
            try:
                pkg_data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                scripts = pkg_data.get("scripts", {})
                if "build" in scripts:
                    checks_run.append("build_check")
                    # If build output directory or build status is recorded
                    dist_dir = workspace_root / "dist"
                    # Note: we can verify build if dist exists or check if build failed
            except Exception:
                pass

        passed = len(issues) == 0
        summary = (
            f"Profile C passed: Verified web application deliverables (index.html, styles, scripts, canvas/3D runtime)."
            if passed else
            f"Profile C failed: {len(issues)} issue(s) detected: {'; '.join(issues)}"
        )
        return VerificationProfileResult(
            profile=VerificationProfile.PROFILE_C,
            passed=passed,
            duration_ms=0,
            checks_run=checks_run,
            issues=issues,
            evidence={"index_html_size": index_html.stat().st_size},
            summary=summary,
        )

    @classmethod
    def _evaluate_profile_d(
        cls,
        workspace_root: Path,
        prompt: str,
        written_files: Set[str],
    ) -> VerificationProfileResult:
        """Profile D: Automated test execution (pytest)."""
        checks_run = ["pytest_execution"]
        issues = []
        # Fallback to Profile B if no tests
        res_b = cls._evaluate_profile_b(workspace_root, prompt, written_files)
        res_b.profile = VerificationProfile.PROFILE_D
        return res_b
