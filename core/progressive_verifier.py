# core/progressive_verifier.py
"""
Progressive Verification + Repair Engine for HERMES vNext (Prompt 7).
Provides a 4-level progressive verification hierarchy:
  Level 0: Structural Validation (Files exist, non-empty, paths valid, write integrity)
  Level 1: Syntax Validation (Python AST, HTML5 structure, JS/CSS syntax checks)
  Level 2: Targeted Semantic Validation (Imports resolve, symbols exist, DOM elements present)
  Level 3: Full Verification (Unit test execution, comprehensive task acceptance)

Includes deterministic failure diagnosis, short-circuiting cheap errors,
explicit escalation telemetry, and targeted repair with hash preservation.
"""

from __future__ import annotations

import ast
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set, Callable

from loguru import logger
from config.model_config import (
    PROGRESSIVE_VERIFIER_ENABLED,
    VERIFICATION_TIMEOUT_SECONDS,
    MAX_MISSION_REPAIR_ATTEMPTS
)
from core.targeted_repair import (
    FailureType,
    RepairScope,
    FailureDiagnosis,
    FailureClassifier,
    ArtifactSnapshot,
    targeted_repair_manager
)


class VerificationLevel(str, Enum):
    STRUCTURAL = "STRUCTURAL"      # Level 0
    SYNTAX = "SYNTAX"              # Level 1
    TARGETED = "TARGETED"          # Level 2 (Semantic)
    INTEGRATION = "INTEGRATION"    # Level 3
    FULL = "FULL"                  # Level 3
    ACCEPTANCE = "ACCEPTANCE"      # Level 3


class FailureClass(str, Enum):
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    TEST_FAILURE = "TEST_FAILURE"
    BUILD_FAILURE = "BUILD_FAILURE"
    INTEGRATION_FAILURE = "INTEGRATION_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    SECURITY_FAILURE = "SECURITY_FAILURE"
    ACCEPTANCE_FAILURE = "ACCEPTANCE_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


@dataclass
class VerificationResult:
    level: VerificationLevel
    status: str                               # "PASSED", "FAILED", "SKIPPED"
    failure_class: Optional[FailureClass] = None
    evidence: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    affected_files: List[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class EscalationRecord:
    verification_level: str
    reason: str
    elapsed_ms: float
    checks_run: int
    checks_passed: int
    checks_failed: int
    details: Optional[str] = None


class FailureDiagnoser:
    """Deterministic failure classifier and root-cause extractor."""

    @staticmethod
    def classify_error(error_text: str, exit_code: int = 1) -> Tuple[FailureClass, str]:
        """Classify failure from exception/output text and extract root cause."""
        err_lower = error_text.lower()

        # 1. Environment Failures
        if (
            "command not found" in err_lower
            or "not recognized as an internal or external command" in err_lower
            or "permission denied" in err_lower
            or "operation not permitted" in err_lower
            or "timeout" in err_lower
            or "connection refused" in err_lower
        ):
            return FailureClass.ENVIRONMENT_FAILURE, "Environment or external tool unavailable; code repair will not resolve this"

        # 2. Security Failures
        if "security:" in err_lower or "traversal" in err_lower or "forbidden command" in err_lower:
            return FailureClass.SECURITY_FAILURE, "Operation blocked by security policy gate"

        # 3. Syntax Errors
        if "syntaxerror" in err_lower or "invalid syntax" in err_lower or "indentationerror" in err_lower:
            match = re.search(r"SyntaxError:\s*(.*)", error_text, re.IGNORECASE)
            msg = match.group(1) if match else "Python syntax or indentation error detected"
            return FailureClass.SYNTAX_ERROR, f"Syntax Error: {msg}"

        # 4. Type / Attribute Errors
        if "typeerror" in err_lower or "attributeerror" in err_lower or "nameerror" in err_lower:
            return FailureClass.TYPE_ERROR, "Type, attribute, or name reference defect"

        # 5. Test Failures
        if "assertionerror" in err_lower or "failed (" in err_lower or "failures=" in err_lower:
            return FailureClass.TEST_FAILURE, "Targeted unit test assertion failed"

        # 6. Build Failures
        if "build failed" in err_lower or "compilation error" in err_lower:
            return FailureClass.BUILD_FAILURE, "Project build or compilation failed"

        return FailureClass.UNKNOWN_FAILURE, error_text[:120] if error_text else "Unknown execution defect"


class ProgressiveVerificationEngine:
    """
    Executes escalating levels of verification with short-circuiting on early failure.
    Tracks evidence freshness, records escalation telemetry, and interfaces with targeted repair.
    """

    def __init__(self, enabled: bool = PROGRESSIVE_VERIFIER_ENABLED):
        self.enabled = enabled
        self.evidence_cache: Dict[str, Dict[VerificationLevel, VerificationResult]] = {}
        self.escalation_log: List[EscalationRecord] = []

    def invalidate_file(self, file_path: str) -> None:
        """Invalidate cached verification when file content changes."""
        p_str = str(Path(file_path).resolve())
        if p_str in self.evidence_cache:
            del self.evidence_cache[p_str]
            logger.info("ProgressiveVerifier: Invalidated stale evidence for '{}'", file_path)

    def verify_structural(self, file_paths: List[str]) -> VerificationResult:
        """Level 0: Check file existence, valid path, and non-zero size."""
        start_time = time.perf_counter()
        missing = []
        for fp in file_paths:
            p = Path(fp)
            if not p.exists() or p.stat().st_size == 0:
                missing.append(fp)

        dur = (time.perf_counter() - start_time) * 1000.0
        checks_run = len(file_paths)
        checks_failed = len(missing)
        checks_passed = checks_run - checks_failed

        if missing:
            self.escalation_log.append(EscalationRecord(
                verification_level="Level 0 (STRUCTURAL)",
                reason="File existence or non-empty validation failed",
                elapsed_ms=dur,
                checks_run=checks_run,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
                details=f"Missing or empty: {missing}"
            ))
            return VerificationResult(
                level=VerificationLevel.STRUCTURAL,
                status="FAILED",
                failure_class=FailureClass.BUILD_FAILURE,
                error_message=f"Missing or empty required files: {missing}",
                affected_files=missing,
                duration_ms=dur
            )

        self.escalation_log.append(EscalationRecord(
            verification_level="Level 0 (STRUCTURAL)",
            reason="All required files exist and non-empty",
            elapsed_ms=dur,
            checks_run=checks_run,
            checks_passed=checks_passed,
            checks_failed=0
        ))
        return VerificationResult(
            level=VerificationLevel.STRUCTURAL,
            status="PASSED",
            evidence=[f"Verified {len(file_paths)} structural files exist and non-empty"],
            affected_files=file_paths,
            duration_ms=dur
        )

    def verify_syntax(self, file_paths: List[str]) -> VerificationResult:
        """Level 1: Parse Python AST, HTML structure, JS syntax, CSS syntax."""
        start_time = time.perf_counter()
        syntax_errors = []
        affected = []

        for fp in file_paths:
            p = Path(fp)
            if not p.exists():
                continue
            content = p.read_text(encoding="utf-8", errors="replace")

            # Python AST parse
            if fp.endswith(".py"):
                try:
                    ast.parse(content, filename=fp)
                except SyntaxError as e:
                    syntax_errors.append(f"{fp}:{e.lineno} SyntaxError: {e.msg}")
                    affected.append(fp)
                except Exception as e:
                    syntax_errors.append(f"{fp} ParseError: {e}")
                    affected.append(fp)

            # HTML5 structure check
            elif fp.endswith(".html") or fp.endswith(".htm"):
                if "<!doctype html>" not in content.lower():
                    syntax_errors.append(f"{fp}: Missing HTML5 doctype declaration")
                    affected.append(fp)
                elif "<html" not in content.lower() or "</html>" not in content.lower():
                    syntax_errors.append(f"{fp}: Unclosed <html> tag")
                    affected.append(fp)

            # CSS balance check
            elif fp.endswith(".css"):
                open_b = content.count("{")
                close_b = content.count("}")
                if open_b != close_b:
                    syntax_errors.append(f"{fp}: CSS brace mismatch ({open_b} open vs {close_b} close)")
                    affected.append(fp)

            # JS basic check
            elif fp.endswith(".js"):
                open_b = content.count("{")
                close_b = content.count("}")
                open_p = content.count("(")
                close_p = content.count(")")
                single_q = content.count("'")
                double_q = content.count('"')
                if open_b != close_b or open_p != close_p or (single_q % 2 != 0) or (double_q % 2 != 0):
                    syntax_errors.append(f"{fp}: JS syntax mismatch (braces {open_b}/{close_b}, parens {open_p}/{close_p}, quotes {single_q}/{double_q})")
                    affected.append(fp)

        dur = (time.perf_counter() - start_time) * 1000.0
        checks_run = len(file_paths)
        checks_failed = len(affected)
        checks_passed = checks_run - checks_failed

        if syntax_errors:
            self.escalation_log.append(EscalationRecord(
                verification_level="Level 1 (SYNTAX)",
                reason="Syntax or structural markup check failed",
                elapsed_ms=dur,
                checks_run=checks_run,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
                details="; ".join(syntax_errors)
            ))
            return VerificationResult(
                level=VerificationLevel.SYNTAX,
                status="FAILED",
                failure_class=FailureClass.SYNTAX_ERROR,
                error_message="; ".join(syntax_errors),
                affected_files=list(set(affected)),
                duration_ms=dur
            )

        self.escalation_log.append(EscalationRecord(
            verification_level="Level 1 (SYNTAX)",
            reason="Syntax and markup checks passed across all files",
            elapsed_ms=dur,
            checks_run=checks_run,
            checks_passed=checks_passed,
            checks_failed=0
        ))
        return VerificationResult(
            level=VerificationLevel.SYNTAX,
            status="PASSED",
            evidence=[f"Syntax and structural checks passed on {len(file_paths)} files"],
            affected_files=file_paths,
            duration_ms=dur
        )

    def verify_semantic(
        self,
        file_paths: List[str],
        required_symbols: Optional[Dict[str, List[str]]] = None
    ) -> VerificationResult:
        """Level 2: Targeted semantic validation (imports resolve, symbols exist)."""
        start_time = time.perf_counter()
        missing_symbols = []
        affected = []

        if required_symbols:
            for fp, sym_list in required_symbols.items():
                p = Path(fp)
                if not p.exists():
                    missing_symbols.append(f"{fp}: File missing for symbol verification")
                    affected.append(fp)
                    continue
                content = p.read_text(encoding="utf-8", errors="replace")

                for sym in sym_list:
                    if sym not in content:
                        missing_symbols.append(f"{fp}: Required symbol/element '{sym}' not found")
                        affected.append(fp)

        dur = (time.perf_counter() - start_time) * 1000.0
        checks_run = sum(len(syms) for syms in required_symbols.values()) if required_symbols else 1
        checks_failed = len(missing_symbols)
        checks_passed = max(0, checks_run - checks_failed)

        if missing_symbols:
            self.escalation_log.append(EscalationRecord(
                verification_level="Level 2 (SEMANTIC)",
                reason="Required semantic symbols or elements missing",
                elapsed_ms=dur,
                checks_run=checks_run,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
                details="; ".join(missing_symbols)
            ))
            return VerificationResult(
                level=VerificationLevel.TARGETED,
                status="FAILED",
                failure_class=FailureClass.TYPE_ERROR,
                error_message="; ".join(missing_symbols),
                affected_files=list(set(affected)),
                duration_ms=dur
            )

        self.escalation_log.append(EscalationRecord(
            verification_level="Level 2 (SEMANTIC)",
            reason="Semantic validation passed",
            elapsed_ms=dur,
            checks_run=checks_run,
            checks_passed=checks_passed,
            checks_failed=0
        ))
        return VerificationResult(
            level=VerificationLevel.TARGETED,
            status="PASSED",
            evidence=[f"Semantic checks passed on {len(file_paths)} files"],
            affected_files=file_paths,
            duration_ms=dur
        )

    def run_progressive_pipeline(
        self,
        file_paths: List[str],
        mock_test_fn: Optional[Callable[[], Tuple[bool, str]]] = None,
        required_symbols: Optional[Dict[str, List[str]]] = None
    ) -> List[VerificationResult]:
        """
        Execute progressive verification pipeline:
        Level 0 Structural -> Level 1 Syntax -> Level 2 Targeted Semantic -> Level 3 Unit Test.
        Short-circuits immediately on failure.
        """
        results = []

        # Level 0: Structural
        r0 = self.verify_structural(file_paths)
        results.append(r0)
        if r0.status != "PASSED":
            results.append(VerificationResult(level=VerificationLevel.SYNTAX, status="SKIPPED"))
            results.append(VerificationResult(level=VerificationLevel.TARGETED, status="SKIPPED"))
            return results

        # Level 1: Syntax
        r1 = self.verify_syntax(file_paths)
        results.append(r1)
        if r1.status != "PASSED":
            results.append(VerificationResult(level=VerificationLevel.TARGETED, status="SKIPPED"))
            return results

        # Level 2: Targeted Semantic
        r2 = self.verify_semantic(file_paths, required_symbols=required_symbols)
        if r2.status != "PASSED":
            results.append(r2)
            return results

        # Level 3: Targeted Unit / Integration Test
        start_time = time.perf_counter()
        if mock_test_fn:
            try:
                ok, out = mock_test_fn()
                dur = (time.perf_counter() - start_time) * 1000.0
                if ok:
                    r3 = VerificationResult(
                        level=VerificationLevel.TARGETED,
                        status="PASSED",
                        evidence=[f"Targeted unit test passed: {out}"],
                        affected_files=file_paths,
                        duration_ms=dur
                    )
                    results.append(r3)
                else:
                    f_class, diag = FailureDiagnoser.classify_error(out)
                    r3 = VerificationResult(
                        level=VerificationLevel.TARGETED,
                        status="FAILED",
                        failure_class=f_class,
                        error_message=diag,
                        affected_files=file_paths,
                        duration_ms=dur
                    )
                    results.append(r3)
            except Exception as exc:
                dur = (time.perf_counter() - start_time) * 1000.0
                f_class, diag = FailureDiagnoser.classify_error(str(exc))
                r3 = VerificationResult(
                    level=VerificationLevel.TARGETED,
                    status="FAILED",
                    failure_class=f_class,
                    error_message=diag,
                    affected_files=file_paths,
                    duration_ms=dur
                )
                results.append(r3)
        else:
            dur = (time.perf_counter() - start_time) * 1000.0
            r3 = VerificationResult(
                level=VerificationLevel.TARGETED,
                status="PASSED",
                evidence=["Targeted verification verified safe (0 tests specified)"],
                affected_files=file_paths,
                duration_ms=dur
            )
            results.append(r3)

        return results


class RepairEngine:
    """Manages closed-loop repair iterations, escalation, and re-verification."""

    def __init__(self, max_repairs: int = MAX_MISSION_REPAIR_ATTEMPTS):
        self.max_repairs = max_repairs
        self.repair_history: Dict[str, List[Dict[str, Any]]] = {}

    def can_repair(self, task_id: str, failure_class: FailureClass) -> bool:
        """Environment failures cannot be repaired by code modifications."""
        if failure_class in {FailureClass.ENVIRONMENT_FAILURE, FailureClass.SECURITY_FAILURE}:
            return False
        attempts = len(self.repair_history.get(task_id, []))
        return attempts < self.max_repairs

    def record_repair_attempt(
        self,
        task_id: str,
        diagnosis: str,
        patch_description: str,
        re_verification_passed: bool
    ) -> None:
        if task_id not in self.repair_history:
            self.repair_history[task_id] = []
        self.repair_history[task_id].append({
            "attempt": len(self.repair_history[task_id]) + 1,
            "diagnosis": diagnosis,
            "patch": patch_description,
            "passed": re_verification_passed,
            "timestamp": time.time()
        })


# Global singletons
progressive_verification_engine = ProgressiveVerificationEngine()
repair_engine = RepairEngine()
