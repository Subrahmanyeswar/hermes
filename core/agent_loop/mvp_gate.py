# core/agent_loop/mvp_gate.py
"""
Website MVP Gate and Progress Lifecycle for HERMES (Section 6 & 7).
Enforces strict 4-phase execution for website-building missions:
  Phase 1: Scaffold (package.json, index.html, main.js, style.css)
  Phase 2: Build & Repair (npm run build; blocks enhancement on failure)
  Phase 3: HTTP Browser Verification (HTTP server, canvas, 0 console errors; rejects file://)
  Phase 4: Enhancement (shaders, particles, telemetry; only after Phase 3 passes)
"""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger

from core.browser.evidence import (
    BrowserEvidenceLifecycle,
    BrowserEvidenceValidator,
    AuthoritativeBrowserEvidence,
)


class MvpPhase(str, Enum):
    PHASE_1_SCAFFOLD = "PHASE_1_SCAFFOLD"
    PHASE_2_BUILD_AND_REPAIR = "PHASE_2_BUILD_AND_REPAIR"
    PHASE_3_HTTP_BROWSER_VERIFICATION = "PHASE_3_HTTP_BROWSER_VERIFICATION"
    PHASE_4_ENHANCEMENT = "PHASE_4_ENHANCEMENT"


# Keywords indicating optional Phase 4 enhancement attempts
ENHANCEMENT_KEYWORDS = frozenset({
    "shader", "particles", "particle", "smoke", "fire", "flame", "telemetry",
    "orbit_controls", "camera_preset", "preset", "cinematic", "audio", "sound",
    "bloom", "postprocessing", "composer", "lensflare", "nebula"
})


class WebsiteMvpGate:
    """
    State machine governing website mission progression.
    Guarantees working MVP prior to optional visual or architectural enhancements.
    """

    def __init__(self, workspace_root: Optional[Path] = None, mission_id: Optional[str] = None) -> None:
        self.workspace_root = workspace_root or Path.cwd()
        self.mission_id: Optional[str] = mission_id
        self.current_phase: MvpPhase = MvpPhase.PHASE_1_SCAFFOLD
        self.build_passed: bool = False
        self.browser_verified: bool = False
        self.last_build_error: Optional[str] = None
        self.last_browser_error: Optional[str] = None
        self.evidence_lifecycle: BrowserEvidenceLifecycle = BrowserEvidenceLifecycle.UNAVAILABLE

    @classmethod
    def is_website_mission(
        cls,
        prompt: str,
        workspace_root: Optional[Path] = None,
        written_files: Optional[Set[str]] = None,
    ) -> bool:
        """Determine if current mission is a website or web application task."""
        p_lower = (prompt or "").lower()

        # Check negative cues first: if prompt explicitly asks for Python, CLI, terminal, backend, or script
        # without explicit website/webpage cues, it is NOT a website mission.
        explicit_non_web = any(k in p_lower for k in (
            "python script", "python program", "python package", "python cli", "python module",
            "pytest", "command-line", "cli utility", "cli tool", "terminal app", "backend service"
        ))
        has_explicit_web_word = any(w in p_lower for w in (
            "website", "web page", "webpage", "web app", "webapp", "landing page", "html", "three.js", "threejs"
        ))
        if explicit_non_web and not has_explicit_web_word:
            return False

        web_cues = (
            "website", "web application", "landing page", "html", "web page", "webpage", "frontend",
            "three.js", "webgl", "dashboard", "css", "canvas", "lvm3 website", "rocket website"
        )
        if any(w in p_lower for w in web_cues):
            return True

        ws = workspace_root or Path.cwd()
        if ws.exists():
            if (ws / "index.html").exists() or (ws / "vite.config.js").exists() or (ws / "vite.config.ts").exists():
                return True
            if (ws / "package.json").exists():
                try:
                    txt = (ws / "package.json").read_text(encoding="utf-8", errors="ignore").lower()
                    if any(k in txt for k in ("three", "vite", "react", "vue", "canvas", "frontend")):
                        return True
                except Exception:
                    pass

        if written_files:
            if any(f.lower().endswith((".html", ".css")) or f.lower() in ("main.js", "app.js", "src/main.js") for f in written_files):
                return True

        return False

    def evaluate(self, workspace_root: Optional[Path] = None) -> Tuple[bool, List[str]]:
        """
        Authoritative evaluation of workspace scaffold completeness (P0 requirement).
        Returns:
            Tuple[bool, List[str]]: (is_complete, list_of_unmet_requirement_descriptions)
        """
        ws = workspace_root or self.workspace_root
        ok, missing = self.check_scaffold_complete(ws)
        unmet = [f"Scaffold missing/incomplete: {m}" for m in missing]
        return ok, unmet

    def check_scaffold_complete(self, workspace_root: Optional[Path] = None) -> Tuple[bool, List[str]]:
        """
        Verify that core Phase 1 scaffold files exist, are valid, and contain non-placeholder code.
        Enforces Section 5 explicit scaffold contract:
          - package.json exists and parses as valid JSON
          - index.html references application entrypoint
          - style.css exists, is nonempty (> 20 bytes), and connected
          - main.js is a real implementation rather than a placeholder skeleton
        """
        ws = workspace_root or self.workspace_root
        missing = []

        # 1. package.json for npm/Vite projects
        pkg_path = ws / "package.json"
        if not pkg_path.exists() or pkg_path.stat().st_size < 20:
            missing.append("package.json")
        else:
            try:
                pkg_data = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
                # Check dependencies or scripts
                scripts = pkg_data.get("scripts", {})
                deps = pkg_data.get("dependencies", {})
                dev_deps = pkg_data.get("devDependencies", {})
                if not isinstance(pkg_data, dict):
                    missing.append("package.json (invalid JSON object)")
            except Exception:
                missing.append("package.json (malformed JSON syntax)")

        # 2. index.html
        html_path = ws / "index.html"
        if not html_path.exists() or html_path.stat().st_size < 50:
            missing.append("index.html")
        else:
            try:
                html_txt = html_path.read_text(encoding="utf-8", errors="ignore")
                has_script = bool(re.search(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html_txt, re.I))
                if not has_script:
                    missing.append("index.html (missing entrypoint <script> tag)")
            except Exception:
                pass

        # 3. Primary JavaScript entrypoint (contract-driven & dynamic)
        expected_js = "app.js"
        # Check project contract if present
        contract_file = ws / ".hermes" / "project_contract.json"
        if contract_file.exists():
            try:
                cdata = json.loads(contract_file.read_text(encoding="utf-8", errors="ignore"))
                if cdata.get("canonical_js"):
                    expected_js = cdata["canonical_js"]
            except Exception:
                pass
        elif html_path.exists():
            # Check script referenced in index.html
            try:
                html_txt_check = html_path.read_text(encoding="utf-8", errors="ignore")
                scripts_found = re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html_txt_check, re.I)
                for s in scripts_found:
                    if not s.startswith(("http://", "https://", "//")):
                        expected_js = s.lstrip("./")
                        break
            except Exception:
                pass
        elif pkg_path.exists():
            try:
                pkg_data_check = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
                if pkg_data_check.get("main") and isinstance(pkg_data_check["main"], str):
                    expected_js = pkg_data_check["main"].lstrip("./")
            except Exception:
                pass

        main_cands = [expected_js, "app.js", "main.js", "src/main.js", "src/app.js", "index.js", "script.js"]
        # Remove duplicates while preserving order
        seen_cands = set()
        ordered_cands = []
        for c in main_cands:
            if c not in seen_cands:
                seen_cands.add(c)
                ordered_cands.append(c)

        found_main: Optional[Path] = None
        for p in ordered_cands:
            cand_p = ws / p
            if cand_p.exists() and cand_p.stat().st_size > 40:
                found_main = cand_p
                break

        if not found_main:
            missing.append(expected_js)
        else:
            # Check completeness and lack of placeholder stubs (Section 4 & 5)
            try:
                from core.code_completeness import validate_implementation_completeness
                code_txt = found_main.read_text(encoding="utf-8", errors="ignore")
                is_complete, comp_err = validate_implementation_completeness(code_txt, found_main.name)
                if not is_complete:
                    missing.append(f"{found_main.name} (incomplete or contains placeholder stubs: {comp_err})")
            except Exception as e:
                logger.debug(f"WebsiteMvpGate: completeness check notice on {found_main}: {e}")

        # 4. Stylesheet (must exist, > 20 bytes, and connected)
        style_cands = ["style.css", "src/style.css", "styles.css", "src/styles.css"]
        has_style = any((ws / p).exists() and (ws / p).stat().st_size > 20 for p in style_cands)
        if not has_style:
            # Check if linked in index.html
            linked_css = False
            if html_path.exists():
                try:
                    html_txt = html_path.read_text(encoding="utf-8", errors="ignore")
                    for m in re.findall(r'<link[^>]+href=["\']([^"\']+\.css)["\']', html_txt, re.I):
                        if (ws / m.lstrip("./")).exists() and (ws / m.lstrip("./")).stat().st_size > 20:
                            linked_css = True
                            break
                except Exception:
                    pass
            if not linked_css:
                missing.append("style.css")

        # 5. Cross-artifact structural integration check
        if len(missing) == 0:
            try:
                from core.integration_validator import CrossArtifactValidator
                rep = CrossArtifactValidator.validate_web_integration(ws)
                if not rep.valid:
                    for iss in rep.issues:
                        missing.append(f"DOM mismatch: {iss}")
            except Exception as e:
                logger.debug(f"WebsiteMvpGate: integration validation notice: {e}")

        return len(missing) == 0, missing

    @classmethod
    def parse_scaffold_target(cls, req_str: str) -> Tuple[Optional[str], str]:
        """
        Extract the target filename and a clear actionable repair instruction
        from an unmet requirement string.
        """
        raw = req_str or ""
        raw_lower = raw.lower()
        detail = raw.split(":", 1)[-1].strip() if ":" in raw else raw
        detail_lower = detail.lower()

        # Specific structured error patterns first
        missing_script_match = re.search(r"Broken script reference in [^:]+:\s*['\"]([^'\"]+\.js)['\"]\s*not found on disk", raw, re.I)
        if missing_script_match:
            missing_script = missing_script_match.group(1).lstrip("./")
            return missing_script, f"Create '{missing_script}' using fs.write with full implementation as referenced in index.html."

        formdata_match = re.search(r"FormData name mismatch:\s*(\w+\.js)\s+accesses formData\.get\(['\"]([^'\"]+)['\"]\)", raw, re.I)
        if formdata_match:
            js_file = formdata_match.group(1)
            field_name = formdata_match.group(2)
            return "index.html", f"Add name='{field_name}' to the corresponding form input/control in index.html so {js_file} can read it."

        dom_mismatch_match = re.search(r"JavaScript DOM mismatch:\s*(\w+\.js)\s+(?:calls getElementById\(['\"]([^'\"]+)['\"]\)|queries ['\"]#([^'\"]+)['\"])", raw, re.I)
        if dom_mismatch_match:
            js_file = dom_mismatch_match.group(1)
            target_id = dom_mismatch_match.group(2) or dom_mismatch_match.group(3)
            return js_file, f"Update '{js_file}' to use the correct DOM ID from index.html, or add #{target_id} to index.html."

        placeholder_match = re.search(r"Incomplete placeholder function in\s+(\w+\.js)", raw, re.I)
        if placeholder_match:
            js_file = placeholder_match.group(1)
            return js_file, f"Implement dynamic calculations in '{js_file}' instead of returning static placeholder values."

        pkg_mismatch = re.search(r"Package entrypoint mismatch", raw, re.I)
        if pkg_mismatch:
            return "package.json", "Align package.json 'main' with the actual JavaScript file on disk."

        for cand in ("index.html", "main.js", "app.js", "style.css", "package.json", "vite.config.js"):
            if cand in raw_lower:
                if "script" in detail_lower and cand == "index.html" and "not found on disk" not in detail_lower:
                    return cand, "Add an entrypoint script tag (e.g. <script src=\"app.js\"></script>) before </body> and ensure all HTML tags are closed."
                elif "placeholder" in detail_lower or "incomplete" in detail_lower:
                    return cand, f"Implement full working functionality in '{cand}' without placeholder stubs."
                elif detail_lower.startswith(cand) or "missing" in detail_lower or detail_lower == cand:
                    return cand, f"Create '{cand}' with complete implementation using fs.write."
                return cand, f"Repair and complete '{cand}' to satisfy requirements."

        if "build" in raw_lower:
            return "npm run build", "Run 'npm run build' via shell.bash to verify the build passes."
        if "browser" in raw_lower:
            return "browser_open_preview", "Open and verify the application in the browser using browser_open_preview."

        return None, raw

    def get_unmet_requirements(self, workspace_root: Optional[Path] = None) -> List[str]:
        """Expose current unmet requirements for progress governance and pre-dispatch policy."""
        ws = workspace_root or self.workspace_root
        phase = self.evaluate_phase(ws)
        if phase == MvpPhase.PHASE_1_SCAFFOLD:
            _, missing = self.check_scaffold_complete(ws)
            return [f"Scaffold missing/incomplete: {m}" for m in missing]
        elif phase == MvpPhase.PHASE_2_BUILD_AND_REPAIR:
            err = f" (Error: {self.last_build_error})" if self.last_build_error else ""
            return [f"Build not verified{err}. Project build must pass (npm run build)."]
        elif phase == MvpPhase.PHASE_3_HTTP_BROWSER_VERIFICATION:
            err = f" ({self.last_browser_error})" if self.last_browser_error else ""
            return [f"Authoritative browser qualification not passed{err}. Must verify HTTP 200, styles, canvas, and 0 console errors via CDP evidence."]
        return []

    def evaluate_phase(
        self,
        workspace_root: Optional[Path] = None,
        build_succeeded: Optional[bool] = None,
        browser_verified: Optional[bool] = None,
    ) -> MvpPhase:
        """Compute the effective lifecycle phase based on real workspace evidence."""
        ws = workspace_root or self.workspace_root

        if build_succeeded is not None:
            self.build_passed = build_succeeded
        if browser_verified is not None:
            self.browser_verified = browser_verified

        # Phase 1: Check scaffold
        scaffold_ok, missing = self.check_scaffold_complete(ws)
        if not scaffold_ok:
            self.current_phase = MvpPhase.PHASE_1_SCAFFOLD
            return self.current_phase

        # Phase 2: Check build
        # If package.json exists, check whether a 'build' script is defined.
        # Pure static/vanilla web apps without a build script do not require npm run build.
        pkg_path = ws / "package.json"
        has_build_script = False
        if pkg_path.exists():
            try:
                pkg_data = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(pkg_data, dict):
                    scripts = pkg_data.get("scripts", {})
                    has_build_script = bool(isinstance(scripts, dict) and scripts.get("build"))
            except Exception:
                pass

        if not has_build_script:
            self.build_passed = True

        if not self.build_passed:
            self.current_phase = MvpPhase.PHASE_2_BUILD_AND_REPAIR
            return self.current_phase

        # Phase 3: Check HTTP browser verification with authoritative evidence
        # Detect if project is purely static HTML/CSS (no JavaScript entrypoint required)
        is_pure_static = False
        html_file = ws / "index.html"
        if html_file.exists():
            try:
                html_txt_check = html_file.read_text(encoding="utf-8", errors="ignore")
                has_script = bool(re.search(r"""<script[^>]+src=["']([^"']+\.js)["']""", html_txt_check, re.I))
                if not has_script:
                    is_pure_static = True
            except Exception:
                pass

        if is_pure_static and self.build_passed:
            # Pure static HTML/CSS with valid structure passes without interactive CDP
            self.browser_verified = True
            self.evidence_lifecycle = BrowserEvidenceLifecycle.PASSED
        else:
            # Interactive web applications strictly require authoritative browser verification evidence
            status, ev, reason = BrowserEvidenceValidator.load_and_validate(ws, mission_id=self.mission_id)
            self.evidence_lifecycle = status
            if status == BrowserEvidenceLifecycle.PASSED:
                self.browser_verified = True
                self.last_browser_error = None
            else:
                self.browser_verified = False
                self.last_browser_error = f"Browser verification {status.value}: {reason}"
                self.current_phase = MvpPhase.PHASE_3_HTTP_BROWSER_VERIFICATION
                return self.current_phase

        # Phase 4: All MVP gates passed -> enhancements allowed
        self.current_phase = MvpPhase.PHASE_4_ENHANCEMENT
        return self.current_phase

    def authorize_action(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        workspace_root: Optional[Path] = None,
    ) -> Tuple[bool, str]:
        """
        Evaluate whether the requested tool action is permitted under the current MVP phase.
        Enforces:
        - Fake root Three.js prohibition.
        - Phase 1 blocks enhancement assets until scaffold is complete.
        - Phase 2 blocks enhancements while build is broken.
        - Phase 3 blocks enhancements while browser verification has not passed.
        """
        ws = workspace_root or self.workspace_root
        phase = self.evaluate_phase(ws)

        # 1. Prohibit fake root Three.js file unconditionally
        target_path = str(arguments.get("path") or arguments.get("file_path") or "").replace("\\", "/").strip("./").lower()
        if target_path in ("three.js", "three"):
            return False, (
                "FAKE_DEPENDENCY_PROHIBITED: Cannot write root-level 'Three.js' file as a substitute for the library. "
                "Install 'three' as an npm package in package.json and import it via 'import * as THREE from \"three\"' in main.js."
            )

        # 2. Check for optional enhancement files
        is_enhancement_file = any(kw in target_path for kw in ENHANCEMENT_KEYWORDS)
        content_sample = str(arguments.get("content") or "").lower()
        is_enhancement_content = any(kw in content_sample for kw in ("shader", "particlesystem", "particlecontainer"))

        if phase == MvpPhase.PHASE_1_SCAFFOLD:
            if is_enhancement_file and target_path not in ("main.js", "src/main.js", "index.html", "style.css", "package.json"):
                scaffold_ok, missing = self.check_scaffold_complete(ws)
                return False, (
                    f"MVP GATE (Phase 1 - Scaffold): Core deliverables are missing: {', '.join(missing)}. "
                    f"You must create {missing[0]} before adding optional enhancement '{target_path}'."
                )

        elif phase == MvpPhase.PHASE_2_BUILD_AND_REPAIR:
            if is_enhancement_file and not self.build_passed:
                err_detail = f" (Last error: {self.last_build_error})" if self.last_build_error else ""
                return False, (
                    f"MVP GATE (Phase 2 - Build & Repair): Project build has not succeeded{err_detail}. "
                    f"You must fix the build error in main.js or package.json before adding optional enhancements."
                )

        elif phase == MvpPhase.PHASE_3_HTTP_BROWSER_VERIFICATION:
            if is_enhancement_file and not self.browser_verified:
                return False, (
                    "MVP GATE (Phase 3 - HTTP Browser Verification): The application must be verified over HTTP in the browser "
                    "(checking HTTP 200, valid styles, DOM canvas, and 0 console errors) before adding optional enhancements."
                )

        return True, "Authorized by MVP Gate"
