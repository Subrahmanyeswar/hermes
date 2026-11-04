# core/agent_loop/completion.py
"""
Authoritative Completion Policy & Goal Completion Guard for HERMES 2.x Agent Loop.

Core Invariants:
1. CLAIMS ARE NOT EVIDENCE: A model self-declaration ('Done', 'Tests passed') NEVER completes a mission.
2. SUBAGENT SUCCESS != GOAL COMPLETE: A subagent completing a subtask does not complete the mission.
3. ACCEPTANCE LEDGER AUTHORITY: Completion requires 100% of requirements VERIFIED or WAIVED.
4. FRESH EVIDENCE MANDATE: All critical acceptance checks must be supported by FRESH, non-stale evidence.
5. QUARANTINE LEGACY HEURISTICS: Prompt 1 keyword checks are completely quarantined from the authoritative completion path.
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.evidence.models import EvidenceFreshness
from core.evidence.store import EvidenceStore
from core.runtime_state.models import (
    AcceptanceCheckStatus,
    AcceptanceLedger,
    HermesRuntimeState,
    RepairStatus,
    RequirementPriority,
    RequirementStatus,
)
from core.workspace import WorkspaceManager

logger = logging.getLogger("hermes.agent_loop.completion")


class GoalCompleteGuard:
    """
    Authoritative guard preventing premature, fake, or unverified mission completion.
    """

    @classmethod
    def evaluate(
        cls,
        state: Optional[HermesRuntimeState] = None,
        ledger: Optional[AcceptanceLedger] = None,
        evidence_store: Optional[EvidenceStore] = None,
        strict_requirements: bool = True,
    ) -> Tuple[bool, str, List[str]]:
        """
        Validate whether the goal satisfies authoritative completion invariants.
        Returns:
            (can_complete: bool, reason: str, issues: List[str])
        """
        issues: List[str] = []

        # 1. State Requirements Check (enforced when strict_requirements is active)
        if state:
            if strict_requirements and state.requirements:
                for req_id, req in state.requirements.items():
                    if req.status not in (RequirementStatus.VERIFIED, RequirementStatus.WAIVED):
                        issues.append(
                            f"Requirement {req_id} ('{req.description[:40]}') is in non-terminal state {req.status.value}"
                        )

            # 2. Check for stalled repairs (always enforced)
            for rep_id, rep in state.repairs.items():
                if rep.status == RepairStatus.STALLED:
                    issues.append(f"Repair {rep_id} is STALLED for check {rep.check_id}")

        # 3. Acceptance Ledger Checks
        check_map = {}
        if ledger and ledger.checks:
            check_map = ledger.checks
        elif state and state.acceptance_ledger and state.acceptance_ledger.checks:
            check_map = state.acceptance_ledger.checks

        for chk_id, chk in check_map.items():
            if chk.status == AcceptanceCheckStatus.FAIL:
                issues.append(f"Acceptance check {chk_id} has FAILED")
            elif strict_requirements and chk.status != AcceptanceCheckStatus.PASS:
                is_critical = getattr(chk, "critical", getattr(chk, "is_critical", True))
                if is_critical:
                    issues.append(f"Critical acceptance check {chk_id} has not PASSED (status: {chk.status.value})")

        # 4. Fresh Evidence Verification
        if evidence_store and strict_requirements:
            for chk_id, chk in check_map.items():
                if chk.status == AcceptanceCheckStatus.PASS:
                    bundle = evidence_store.get_bundle(chk.requirement_id, check_id=chk_id)
                    if not bundle.records:
                        issues.append(f"Passed check {chk_id} has no supporting evidence records in EvidenceStore")
                    elif not bundle.is_all_fresh:
                        issues.append(f"Passed check {chk_id} is backed by STALE or INVALIDATED evidence")

        if issues:
            return (
                False,
                f"Goal completion rejected by GoalCompleteGuard ({len(issues)} unsatisfied invariant(s)).",
                issues,
            )

        return (True, "GoalCompleteGuard invariants satisfied.", [])




def verify_deliverables_and_test_execution(
    ws_root: Path,
    mission_prompt: str,
    acceptance_criteria: Optional[List[str]] = None,
) -> Tuple[bool, str, List[str]]:
    """
    Discovers language, framework, test suite, and README documentation.
    Executes automated tests when present and validates documentation quality.
    """
    p_lower = (mission_prompt or "").lower()
    crit_text = " ".join(acceptance_criteria or []).lower()
    combined = f"{p_lower} {crit_text}"
    issues: List[str] = []

    # 1. README Verification
    requires_readme = any(k in combined for k in ("readme", "documentation", "docs", "setup guide", "instructions"))
    is_fullstack_or_app = any(k in combined for k in ("app", "application", "platform", "full-stack", "fullstack", "dashboard", "web app"))
    if requires_readme or is_fullstack_or_app:
        readme_candidates = [ws_root / "README.md", ws_root / "readme.md", ws_root / "README.txt"]
        found_readme = None
        for r in readme_candidates:
            if r.exists():
                found_readme = r
                break
        if not found_readme:
            return (
                False,
                "Deliverable check failed: Missing required README.md deliverable.",
                ["Missing required deliverable: README.md"]
            )
        try:
            readme_text = found_readme.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            readme_text = ""
        if len(readme_text.strip()) < 100:
            return (
                False,
                "Deliverable check failed: README.md is empty or incomplete (< 100 bytes).",
                ["Incomplete README.md (< 100 bytes)"]
            )
        has_heading = "#" in readme_text
        has_instructions = any(kw in readme_text.lower() for kw in ("run", "start", "install", "node", "python", "npm", "test", "usage"))
        if not has_heading or not has_instructions:
            return (
                False,
                "Deliverable check failed: README.md lacks required headings or execution/setup instructions.",
                ["README.md lacks setup/run instructions"]
            )

    # 2. Automated Test Verification & Execution
    requires_tests = any(k in combined for k in ("test", "tests", "automated test", "test suite", "unit test", "api test", "jest", "pytest"))
    if requires_tests:
        test_patterns = ["test_*.py", "*_test.py", "*.test.js", "*.spec.js", "test.js", "tests.js", "test_*.js"]
        found_tests = []
        for pat in test_patterns:
            found_tests.extend(list(ws_root.glob(pat)))
            found_tests.extend(list(ws_root.glob(f"tests/{pat}")))
            found_tests.extend(list(ws_root.glob(f"test/{pat}")))
        valid_tests = [f for f in found_tests if f.is_file() and f.stat().st_size > 30]
        if not valid_tests:
            return (
                False,
                "Deliverable check failed: Prompt requested automated tests, but no valid test files exist in workspace.",
                ["Missing required deliverable: complete automated test suite"]
            )

        test_cmd = None
        pkg_json = ws_root / "package.json"
        if pkg_json.exists():
            try:
                pkg_data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                scripts = pkg_data.get("scripts", {})
                if "test" in scripts and "no test specified" not in scripts["test"]:
                    if (ws_root / "node_modules").exists():
                        test_cmd = ["npm", "test"]
            except Exception:
                pass

        if not test_cmd:
            py_tests = [f for f in valid_tests if f.suffix == ".py"]
            if py_tests:
                import sys
                test_cmd = [sys.executable, "-m", "pytest", str(py_tests[0]), "-q"]

        if test_cmd:
            try:
                import subprocess
                import os
                test_env = os.environ.copy()
                isolated_db_path = ws_root / ".test_isolated.db"
                test_env["BHARATBRIDGE_DB_PATH"] = str(isolated_db_path)
                test_env["NODE_ENV"] = "test"
                try:
                    run_res = subprocess.run(
                        test_cmd,
                        cwd=str(ws_root),
                        env=test_env,
                        capture_output=True,
                        text=True,
                        timeout=30.0,
                    )
                finally:
                    if isolated_db_path.exists():
                        try:
                            isolated_db_path.unlink()
                        except Exception:
                            pass
                if run_res.returncode != 0:
                    err_sample = (run_res.stderr or run_res.stdout or "")[-300:]
                    return (
                        False,
                        f"Deliverable check failed: Automated test execution failed (exit code {run_res.returncode}): {err_sample.strip()}",
                        [f"Test execution failed with exit code {run_res.returncode}"]
                    )
            except FileNotFoundError:
                return (
                    False,
                    f"Deliverable check failed: Test runner executable '{test_cmd[0]}' not found.",
                    [f"Test runner unavailable: {test_cmd[0]}"]
                )
            except subprocess.TimeoutExpired:
                return (
                    False,
                    "Deliverable check failed: Automated test execution timed out (> 30s).",
                    ["Test execution timed out"]
                )
            except Exception as ex:
                return (
                    False,
                    f"Deliverable check failed: Test execution encountered exception: {ex}",
                    [str(ex)]
                )

    return True, "Deliverables and tests verified.", []


class CompletionPolicy:
    """
    Evaluates completion candidates against physical workspace evidence,
    deterministic AST/syntax checks, and authoritative GoalCompleteGuard criteria.
    Legacy keyword-based quality heuristics are strictly quarantined.
    """

    def __init__(self) -> None:
        pass

    def evaluate_completion(
        self,
        mission_prompt: str,
        workspace: Optional[WorkspaceManager] = None,
        acceptance_criteria: Optional[List[str]] = None,
        written_files: Optional[List[str]] = None,
        runtime_state: Optional[HermesRuntimeState] = None,
        acceptance_ledger: Optional[AcceptanceLedger] = None,
        evidence_store: Optional[EvidenceStore] = None,
        strict_requirements: Optional[bool] = None,
        candidate_response: Optional[str] = None,
    ) -> Tuple[bool, str, List[str]]:
        """
        Evaluate whether the mission satisfies completion requirements.

        Returns:
            (accepted: bool, reason: str, issues: List[str])
        """
        issues: List[str] = []
        acceptance_criteria = acceptance_criteria or []
        written_files = written_files or []
        is_strict = strict_requirements if strict_requirements is not None else bool(acceptance_criteria)

        ws_root = None
        if workspace:
            if isinstance(workspace, (Path, str)):
                ws_root = Path(workspace).resolve()
            elif hasattr(workspace, "workspace_root") and workspace.workspace_root:
                ws_root = Path(workspace.workspace_root).resolve()
            elif getattr(workspace, "is_locked", False) and getattr(workspace, "root_str", None):
                ws_root = Path(workspace.root_str).resolve()
            elif hasattr(workspace, "root_str") and workspace.root_str:
                ws_root = Path(workspace.root_str).resolve()
            elif hasattr(workspace, "_mission_workspace") and workspace._mission_workspace:
                ws_root = Path(workspace._mission_workspace).resolve()

        # ── 0. Risk-Based Fast Verification Profile Path (Profile A/B/C) ──
        try:
            from core.verification_profiles import classify_verification_profile, VerificationProfileEvaluator, VerificationProfile
            prof = classify_verification_profile(mission_prompt, workspace_path=str(ws_root) if ws_root else None, written_files=written_files)
            if prof in (VerificationProfile.PROFILE_A, VerificationProfile.PROFILE_B, VerificationProfile.PROFILE_C) and ws_root and ws_root.exists():
                prof_res = VerificationProfileEvaluator.evaluate(prof, ws_root, mission_prompt, written_files=written_files)
                if prof_res.passed:
                    # Mandatory syntax gate: verify all JavaScript files pass syntax checks before accepting
                    for js_file in ws_root.glob("*.js"):
                        from core.js_syntax_validator import validate_javascript_file
                        j_ok, j_err, _ = validate_javascript_file(js_file)
                        if not j_ok:
                            return (
                                False,
                                f"Fast verification rejected: JavaScript syntax error in {js_file.name}: {j_err}",
                                [f"JavaScript syntax error in {js_file.name}: {j_err}"]
                            )

                    from core.cross_file_contract import CrossFileContractValidator
                    cross_rep = CrossFileContractValidator.validate_workspace(ws_root)
                    if not cross_rep.valid:
                        err_msgs = (
                            cross_rep.endpoint_mismatches
                            + cross_rep.html_asset_mismatches
                            + cross_rep.dom_id_mismatches
                            + cross_rep.database_mismatches
                            + cross_rep.startup_mismatches
                            + cross_rep.response_shape_mismatches
                            + cross_rep.module_graph_mismatches
                            + cross_rep.api_client_mismatches
                            + cross_rep.form_enum_mismatches
                            + cross_rep.test_export_mismatches
                        ) or [cross_rep.summary]
                        return (
                            False,
                            f"Fast verification rejected: Cross-file contract validation failed ({len(err_msgs)} error(s)): {cross_rep.summary}",
                            err_msgs,
                        )
                    # Deliverables and Automated Test Execution
                    d_ok, d_reason, d_issues = verify_deliverables_and_test_execution(
                        ws_root=ws_root,
                        mission_prompt=mission_prompt,
                        acceptance_criteria=acceptance_criteria,
                    )
                    if not d_ok:
                        return (
                            False,
                            f"Fast verification rejected: {d_reason}",
                            d_issues,
                        )

                    # For interactive applications, ensure Browser Acceptance & Freshness pass
                    is_interactive_app = any(k in mission_prompt.lower() for k in (
                        "task", "timer", "habit", "pomodoro", "dashboard", "crud", "interactive", "command center", "full web app"
                    ))
                    if is_interactive_app:
                        from core.browser.acceptance import BrowserAcceptanceVerifier
                        if BrowserAcceptanceVerifier.is_interactive_web_project(ws_root):
                            b_res = BrowserAcceptanceVerifier.verify_workspace_sync(
                                ws_root,
                                acceptance_ledger=acceptance_ledger,
                            )
                            if not b_res.passed:
                                return (
                                    False,
                                    f"Fast verification rejected: Browser acceptance failed: {b_res.summary}",
                                    b_res.issues,
                                )
                            fresh_ok, fresh_msg = BrowserAcceptanceVerifier.check_evidence_freshness(ws_root)
                            if not fresh_ok:
                                return (
                                    False,
                                    f"Fast verification rejected: {fresh_msg}",
                                    [fresh_msg],
                                )
                    if runtime_state or acceptance_ledger or evidence_store:
                        guard_ok, guard_reason, guard_issues = GoalCompleteGuard.evaluate(
                            state=runtime_state,
                            ledger=acceptance_ledger,
                            evidence_store=evidence_store,
                            strict_requirements=is_strict,
                        )
                        if not guard_ok:
                            return (
                                False,
                                f"Goal completion rejected: {guard_reason}",
                                guard_issues,
                            )

                    return (True, f"All requirements satisfied via verified verification {prof.value}: {prof_res.summary}", [])
                elif prof_res.issues:
                    for iss in prof_res.issues:
                        if iss not in issues:
                            issues.append(iss)
        except Exception:
            pass

        # ── 1. Authoritative Ledger & Guard Check ─────────────────────────────
        if runtime_state or acceptance_ledger or evidence_store:
            guard_ok, guard_reason, guard_issues = GoalCompleteGuard.evaluate(
                state=runtime_state,
                ledger=acceptance_ledger,
                evidence_store=evidence_store,
                strict_requirements=is_strict,
            )
            if not guard_ok:
                return (False, guard_reason, guard_issues)

        # ── 1b. Explicit Acceptance Criteria Evaluation on Candidate Response ─────
        # If explicit acceptance criteria require information to be reported in the response,
        # ensure the candidate response satisfies those criteria when tested.
        if acceptance_criteria and candidate_response is not None:
            for crit in acceptance_criteria:
                crit_clean = crit.strip()
                if crit_clean.startswith("must_contain:") or crit_clean.startswith("must_report:"):
                    required_substring = crit_clean.split(":", 1)[1].strip()
                    if required_substring.lower() not in candidate_response.lower():
                        issues.append(f"Response missing required outcome detail: '{required_substring}'")
            if issues:
                return (
                    False,
                    f"Completion rejected: candidate response failed acceptance criteria ({len(issues)} issue(s)).",
                    issues,
                )

        # ── 2. Artifact Existence & Non-Empty Check ───────────────────────────
        creation_keywords = ("build", "create", "write", "implement", "generate", "develop", "setup", "make")
        implies_creation = any(kw in mission_prompt.lower() for kw in creation_keywords)

        ws_root = None
        if workspace:
            if isinstance(workspace, (Path, str)):
                ws_root = Path(workspace).resolve()
            elif hasattr(workspace, "workspace_root") and workspace.workspace_root:
                ws_root = Path(workspace.workspace_root).resolve()
            elif getattr(workspace, "is_locked", False) and getattr(workspace, "root_str", None):
                ws_root = Path(workspace.root_str).resolve()
            elif hasattr(workspace, "root_str") and workspace.root_str:
                ws_root = Path(workspace.root_str).resolve()
            elif hasattr(workspace, "_mission_workspace") and workspace._mission_workspace:
                ws_root = Path(workspace._mission_workspace).resolve()

        IGNORE_PARTS = frozenset({
            ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
            ".hermes", ".artifacts", "dist", "build", "coverage", ".pytest_cache"
        })

        if implies_creation:
            if ws_root and ws_root.exists():
                existing_files = [
                    f for f in ws_root.rglob("*")
                    if f.is_file() and not any(part in IGNORE_PARTS or part.startswith(".") for part in f.relative_to(ws_root).parts)
                ]
                if not existing_files and not written_files:
                    return (
                        False,
                        "Completion rejected: prompt requested creation but no artifacts were found in the workspace.",
                        ["No output files created in workspace root"]
                    )
                empty_files = [
                    str(f.name) for f in existing_files
                    if f.stat().st_size == 0 and f.suffix.lower() in (".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".txt")
                ]
                if empty_files:
                    issues.append(f"Empty files detected: {', '.join(empty_files[:3])}")
            elif not written_files:
                return (
                    False,
                    "Completion rejected: workspace root does not contain created files.",
                    ["No output files detected"]
                )

        # ── 3. Local Deterministic Fast Path (Syntax & Parsing) ───────────────
        if ws_root and ws_root.exists():
            for p in ws_root.rglob("*"):
                if not p.is_file():
                    continue
                try:
                    rel_parts = p.relative_to(ws_root).parts
                except ValueError:
                    continue
                if any(part in IGNORE_PARTS or part.startswith(".") for part in rel_parts):
                    continue
                if p.suffix == ".py":
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        ast.parse(content, filename=str(p))
                    except SyntaxError as syn_err:
                        issues.append(f"Python syntax error in {p.name} (line {syn_err.lineno}): {syn_err.msg}")
                elif p.suffix in (".js", ".mjs", ".cjs"):
                    from core.js_syntax_validator import validate_javascript_file
                    js_ok, js_err, _ = validate_javascript_file(p)
                    if not js_ok:
                        issues.append(f"JavaScript syntax error in {p.name}: {js_err}")
                elif p.suffix == ".json":
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        json.loads(content)
                    except Exception as json_err:
                        issues.append(f"Malformed JSON in {p.name}: {json_err}")

        if issues:
            return (
                False,
                f"Completion rejected: deterministic syntax validation failed ({len(issues)} issue(s)).",
                issues
            )

        # ── 4. Technology-Aware Behavioral Verification & Quality Gate ────────
        # 4a. Deterministic Cross-File Contract Alignment Verification (Contracts first)
        if ws_root and ws_root.exists():
            from core.cross_file_contract import CrossFileContractValidator
            cross_report = CrossFileContractValidator.validate_workspace(ws_root)
            if not cross_report.valid:
                err_msgs = (
                    cross_report.endpoint_mismatches
                    + cross_report.html_asset_mismatches
                    + cross_report.dom_id_mismatches
                    + cross_report.database_mismatches
                    + cross_report.startup_mismatches
                    + cross_report.response_shape_mismatches
                    + cross_report.module_graph_mismatches
                    + cross_report.api_client_mismatches
                    + cross_report.form_enum_mismatches
                    + cross_report.test_export_mismatches
                ) or [cross_report.summary]
                return (
                    False,
                    f"Completion rejected: Cross-file contract validation failed ({len(err_msgs)} error(s)): {cross_report.summary}",
                    err_msgs,
                )

            from core.alignment_verifier import verify_project_alignment
            bp = getattr(runtime_state, "blueprint", None) if runtime_state else None
            im = getattr(runtime_state, "interface_manifest", None) if runtime_state else None
            qr = getattr(runtime_state, "quality_rubric", None) if runtime_state else None

            # Run alignment verifier if contracts are present or if HTML/JS implementation files exist
            has_impl_files = any(ws_root.glob("*.html")) or any(ws_root.glob("*.js"))
            if bp is not None or im is not None or has_impl_files:
                align_report = verify_project_alignment(
                    workspace_root=ws_root,
                    blueprint=bp,
                    interface_manifest=im,
                    quality_rubric=qr,
                )
                if align_report.hard_error_count > 0:
                    err_msgs = [f"[{d.kind.value}] {d.file_path}: {d.message}" for d in align_report.defects if d.severity.value == "ERROR"]
                    return (
                        False,
                        f"Completion rejected: Contract alignment verification failed ({align_report.hard_error_count} hard error(s)).",
                        err_msgs,
                    )

        # 4b. Technology-Aware Behavioral Verification
        if (implies_creation or written_files) and ws_root and ws_root.exists():
            from core.agent_loop.behavioral_verifier import TechnologyAwareBehavioralVerifier
            b_result = TechnologyAwareBehavioralVerifier.verify_workspace(
                ws_root=ws_root,
                mission_prompt=mission_prompt,
                acceptance_criteria=acceptance_criteria,
            )
            if not b_result.passed:
                return (
                    False,
                    f"Completion rejected by BehavioralVerifier ({len(b_result.issues)} issue(s)): {'; '.join(b_result.issues[:2])}",
                    b_result.issues,
                )

        # 4c. Deliverables and Automated Test Execution Verification
        if ws_root and ws_root.exists():
            d_ok, d_reason, d_issues = verify_deliverables_and_test_execution(
                ws_root=ws_root,
                mission_prompt=mission_prompt,
                acceptance_criteria=acceptance_criteria,
            )
            if not d_ok:
                return False, d_reason, d_issues

        # 4d. Browser Acceptance Gate
        if ws_root and ws_root.exists():
            from core.browser.acceptance import BrowserAcceptanceVerifier
            if BrowserAcceptanceVerifier.is_interactive_web_project(ws_root):
                b_res = BrowserAcceptanceVerifier.verify_workspace_sync(
                    ws_root,
                    acceptance_ledger=acceptance_ledger,
                )
                if not b_res.passed:
                    return (
                        False,
                        f"Completion rejected: Browser acceptance failed: {b_res.summary}",
                        b_res.issues,
                    )
                fresh_ok, fresh_msg = BrowserAcceptanceVerifier.check_evidence_freshness(ws_root)
                if not fresh_ok:
                    return (
                        False,
                        f"Completion rejected: {fresh_msg}",
                        [fresh_msg],
                    )

        # ── 5. Acceptance ─────────────────────────────────────────────────────
        return True, "All completion evidence and behavioral checks verified.", []
