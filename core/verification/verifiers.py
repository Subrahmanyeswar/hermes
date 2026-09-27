# core/verification/verifiers.py
"""
Deterministic Verifiers for HERMES 2.x.

Core Invariants:
1. PURE ENVIRONMENT OBSERVATION: Verifiers never accept self-reported model claims as truth.
2. DETERMINISTIC & HERMETIC: Running the same verifier on the same evidence always produces the same verdict.
3. CONFINED EXECUTION: AST checks and schema checks analyze structure statically without running untrusted code.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.evidence.models import EvidenceBundle, EvidenceRecord, EvidenceSourceType
from core.runtime_state.models import FailureClass
from core.verification.models import CheckType, VerificationResult, VerificationVerdict

logger = logging.getLogger("hermes.verification.verifiers")


class BaseVerifier(ABC):
    """Abstract base class for deterministic verifiers."""

    check_type: CheckType = CheckType.CUSTOM

    @abstractmethod
    def verify(
        self,
        check_id: str,
        bundle: EvidenceBundle,
        requirement_id: Optional[str] = None,
        **kwargs: Any,
    ) -> VerificationResult:
        """Evaluate evidence against this verifier's rules."""
        pass


class FilesystemVerifier(BaseVerifier):
    """
    Verifies filesystem state: file existence, size, and pattern matching.
    """
    check_type = CheckType.FILESYSTEM

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()

    def verify(
        self,
        check_id: str,
        bundle: EvidenceBundle,
        requirement_id: Optional[str] = None,
        target_path: Optional[str] = None,
        must_exist: bool = True,
        min_size_bytes: int = 1,
        contains_patterns: Optional[Sequence[str]] = None,
        not_contains_patterns: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> VerificationResult:
        t0 = time.time()
        evidence_ids = [r.evidence_id for r in bundle.records]

        # Find target path either from argument or latest record
        path_str = target_path
        if not path_str:
            rec = bundle.get_latest_record()
            if rec and rec.source_uri_or_path:
                path_str = rec.source_uri_or_path

        if not path_str:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.INCONCLUSIVE,
                failure_class=FailureClass.MISSING_DEPENDENCY,
                message="FilesystemVerifier requires a target path or evidence record with source path",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        full_path = (self.workspace_root / path_str).resolve()

        if must_exist and not full_path.exists():
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.ASSERTION_FAILED,
                message=f"Required file does not exist: {path_str}",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        if not must_exist and full_path.exists():
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.ASSERTION_FAILED,
                message=f"File was expected not to exist, but exists: {path_str}",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        if must_exist and full_path.is_file():
            size = full_path.stat().st_size
            if size < min_size_bytes:
                return VerificationResult(
                    check_id=check_id,
                    requirement_id=requirement_id,
                    verdict=VerificationVerdict.FAIL,
                    failure_class=FailureClass.ASSERTION_FAILED,
                    message=f"File {path_str} is too small: {size} bytes < {min_size_bytes} required",
                    evidence_ids=evidence_ids,
                    duration_ms=(time.time() - t0) * 1000.0,
                )

            if contains_patterns or not_contains_patterns:
                try:
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    return VerificationResult(
                        check_id=check_id,
                        requirement_id=requirement_id,
                        verdict=VerificationVerdict.FAIL,
                        failure_class=FailureClass.FILE_CORRUPTED,
                        message=f"Failed to read file {path_str}: {e}",
                        evidence_ids=evidence_ids,
                        duration_ms=(time.time() - t0) * 1000.0,
                    )

                if contains_patterns:
                    for pat in contains_patterns:
                        if pat not in content and not re.search(pat, content):
                            return VerificationResult(
                                check_id=check_id,
                                requirement_id=requirement_id,
                                verdict=VerificationVerdict.FAIL,
                                failure_class=FailureClass.ASSERTION_FAILED,
                                message=f"File {path_str} missing required pattern: '{pat}'",
                                evidence_ids=evidence_ids,
                                duration_ms=(time.time() - t0) * 1000.0,
                            )

                if not_contains_patterns:
                    for pat in not_contains_patterns:
                        if pat in content or re.search(pat, content):
                            return VerificationResult(
                                check_id=check_id,
                                requirement_id=requirement_id,
                                verdict=VerificationVerdict.FAIL,
                                failure_class=FailureClass.ASSERTION_FAILED,
                                message=f"File {path_str} contains forbidden pattern: '{pat}'",
                                evidence_ids=evidence_ids,
                                duration_ms=(time.time() - t0) * 1000.0,
                            )

        return VerificationResult(
            check_id=check_id,
            requirement_id=requirement_id,
            verdict=VerificationVerdict.PASS,
            message=f"Filesystem assertions passed for {path_str}",
            evidence_ids=evidence_ids,
            duration_ms=(time.time() - t0) * 1000.0,
        )


class PythonAstVerifier(BaseVerifier):
    """
    Statically analyzes Python code structure without executing it.
    Checks syntax validity and presence of required classes/functions/methods.
    """
    check_type = CheckType.PYTHON_AST

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()

    def verify(
        self,
        check_id: str,
        bundle: EvidenceBundle,
        requirement_id: Optional[str] = None,
        target_path: Optional[str] = None,
        required_classes: Optional[Sequence[str]] = None,
        required_functions: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> VerificationResult:
        t0 = time.time()
        evidence_ids = [r.evidence_id for r in bundle.records]

        path_str = target_path
        if not path_str:
            rec = bundle.get_latest_record()
            if rec and rec.source_uri_or_path:
                path_str = rec.source_uri_or_path

        if not path_str:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.INCONCLUSIVE,
                failure_class=FailureClass.MISSING_DEPENDENCY,
                message="PythonAstVerifier requires a target Python file",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        full_path = (self.workspace_root / path_str).resolve()
        if not full_path.exists():
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.ASSERTION_FAILED,
                message=f"Target file does not exist: {path_str}",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        try:
            source = full_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(full_path))
        except SyntaxError as e:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.SYNTAX_ERROR,
                message=f"SyntaxError in {path_str} line {e.lineno}: {e.msg}",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )
        except Exception as e:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.FILE_CORRUPTED,
                message=f"Failed to read/parse {path_str}: {e}",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        found_classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        found_functions = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

        if required_classes:
            for cls_name in required_classes:
                if cls_name not in found_classes:
                    return VerificationResult(
                        check_id=check_id,
                        requirement_id=requirement_id,
                        verdict=VerificationVerdict.FAIL,
                        failure_class=FailureClass.ASSERTION_FAILED,
                        message=f"Python file {path_str} missing required class '{cls_name}'",
                        evidence_ids=evidence_ids,
                        details={"found_classes": list(found_classes)},
                        duration_ms=(time.time() - t0) * 1000.0,
                    )

        if required_functions:
            for fn_name in required_functions:
                if fn_name not in found_functions:
                    return VerificationResult(
                        check_id=check_id,
                        requirement_id=requirement_id,
                        verdict=VerificationVerdict.FAIL,
                        failure_class=FailureClass.ASSERTION_FAILED,
                        message=f"Python file {path_str} missing required function '{fn_name}'",
                        evidence_ids=evidence_ids,
                        details={"found_functions": list(found_functions)},
                        duration_ms=(time.time() - t0) * 1000.0,
                    )

        return VerificationResult(
            check_id=check_id,
            requirement_id=requirement_id,
            verdict=VerificationVerdict.PASS,
            message=f"Python AST checks passed for {path_str}",
            evidence_ids=evidence_ids,
            details={"classes": list(found_classes), "functions": list(found_functions)},
            duration_ms=(time.time() - t0) * 1000.0,
        )


class JsonSchemaVerifier(BaseVerifier):
    """
    Validates JSON content for well-formedness and required structure.
    """
    check_type = CheckType.JSON_SCHEMA

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()

    def verify(
        self,
        check_id: str,
        bundle: EvidenceBundle,
        requirement_id: Optional[str] = None,
        target_path: Optional[str] = None,
        required_keys: Optional[Sequence[str]] = None,
        expected_types: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> VerificationResult:
        t0 = time.time()
        evidence_ids = [r.evidence_id for r in bundle.records]

        path_str = target_path
        if not path_str:
            rec = bundle.get_latest_record()
            if rec and rec.source_uri_or_path:
                path_str = rec.source_uri_or_path

        if not path_str:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.INCONCLUSIVE,
                failure_class=FailureClass.MISSING_DEPENDENCY,
                message="JsonSchemaVerifier requires a target JSON file",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        full_path = (self.workspace_root / path_str).resolve()
        if not full_path.exists():
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.ASSERTION_FAILED,
                message=f"JSON file does not exist: {path_str}",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        try:
            content = full_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except Exception as e:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.SCHEMA_VIOLATION,
                message=f"Malformed JSON in {path_str}: {e}",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        if not isinstance(data, dict):
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.SCHEMA_VIOLATION,
                message=f"Expected JSON object in {path_str}, got {type(data).__name__}",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        if required_keys:
            for key in required_keys:
                if key not in data:
                    return VerificationResult(
                        check_id=check_id,
                        requirement_id=requirement_id,
                        verdict=VerificationVerdict.FAIL,
                        failure_class=FailureClass.SCHEMA_VIOLATION,
                        message=f"JSON object in {path_str} missing required key '{key}'",
                        evidence_ids=evidence_ids,
                        duration_ms=(time.time() - t0) * 1000.0,
                    )

        if expected_types:
            type_map = {
                "str": str,
                "int": int,
                "float": (int, float),
                "bool": bool,
                "list": list,
                "dict": dict,
            }
            for k, type_name in expected_types.items():
                if k in data:
                    exp = type_map.get(type_name)
                    if exp and not isinstance(data[k], exp):
                        return VerificationResult(
                            check_id=check_id,
                            requirement_id=requirement_id,
                            verdict=VerificationVerdict.FAIL,
                            failure_class=FailureClass.SCHEMA_VIOLATION,
                            message=f"Key '{k}' in {path_str} expected {type_name}, got {type(data[k]).__name__}",
                            evidence_ids=evidence_ids,
                            duration_ms=(time.time() - t0) * 1000.0,
                        )

        return VerificationResult(
            check_id=check_id,
            requirement_id=requirement_id,
            verdict=VerificationVerdict.PASS,
            message=f"JSON schema checks passed for {path_str}",
            evidence_ids=evidence_ids,
            duration_ms=(time.time() - t0) * 1000.0,
        )


class TestResultVerifier(BaseVerifier):
    """
    Verifies that automated test executions produced zero failures and exit code 0.
    """
    check_type = CheckType.TEST_RESULT

    def verify(
        self,
        check_id: str,
        bundle: EvidenceBundle,
        requirement_id: Optional[str] = None,
        min_tests_passed: int = 1,
        **kwargs: Any,
    ) -> VerificationResult:
        t0 = time.time()
        evidence_ids = [r.evidence_id for r in bundle.records]

        if not bundle.records:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.INCONCLUSIVE,
                failure_class=FailureClass.MISSING_DEPENDENCY,
                message="No test execution evidence records found in bundle",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        latest = bundle.get_latest_record()
        if not latest:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.INCONCLUSIVE,
                failure_class=FailureClass.MISSING_DEPENDENCY,
                message="Latest evidence record is missing",
                evidence_ids=evidence_ids,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        # Check test target correspondence if specified
        target_test = kwargs.get("target_test") or kwargs.get("test_pattern") or kwargs.get("test_file")
        if target_test:
            cmd = (latest.command or "").lower()
            meta_str = str(latest.metadata or {}).lower()
            target_lower = str(target_test).lower()
            if target_lower not in cmd and target_lower not in meta_str:
                return VerificationResult(
                    check_id=check_id,
                    requirement_id=requirement_id,
                    verdict=VerificationVerdict.FAIL,
                    failure_class=FailureClass.ASSERTION_FAILED,
                    message=f"Test evidence does not correspond to expected test '{target_test}' (command: '{latest.command}')",
                    evidence_ids=evidence_ids,
                    details=latest.metadata or {},
                    duration_ms=(time.time() - t0) * 1000.0,
                )

        # Check exit code
        if latest.exit_code is not None and latest.exit_code != 0:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.TEST_FAILED,
                message=f"Test run failed with non-zero exit code {latest.exit_code}",
                evidence_ids=evidence_ids,
                details=latest.metadata,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        # Check test assertions if metadata contains counts
        meta = latest.metadata or {}
        failed_count = meta.get("failed_count", 0)
        error_count = meta.get("error_count", 0)
        passed_count = meta.get("passed_count", 0)

        if failed_count > 0 or error_count > 0:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.TEST_FAILED,
                message=f"Test suite had failures (failed={failed_count}, errors={error_count})",
                evidence_ids=evidence_ids,
                details=meta,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        if min_tests_passed > 0 and passed_count < min_tests_passed and "passed_count" in meta:
            return VerificationResult(
                check_id=check_id,
                requirement_id=requirement_id,
                verdict=VerificationVerdict.FAIL,
                failure_class=FailureClass.ASSERTION_FAILED,
                message=f"Test suite passed only {passed_count} tests; expected at least {min_tests_passed}",
                evidence_ids=evidence_ids,
                details=meta,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        return VerificationResult(
            check_id=check_id,
            requirement_id=requirement_id,
            verdict=VerificationVerdict.PASS,
            message="Test execution passed with exit code 0",
            evidence_ids=evidence_ids,
            details=meta,
            duration_ms=(time.time() - t0) * 1000.0,
        )


class CompositeVerifier(BaseVerifier):
    """
    Chains multiple verifiers in sequence with AND semantics.
    """
    check_type = CheckType.COMPOSITE

    def __init__(self, verifiers: Sequence[BaseVerifier]):
        self.verifiers = list(verifiers)

    def verify(
        self,
        check_id: str,
        bundle: EvidenceBundle,
        requirement_id: Optional[str] = None,
        **kwargs: Any,
    ) -> VerificationResult:
        t0 = time.time()
        evidence_ids = [r.evidence_id for r in bundle.records]

        for verifier in self.verifiers:
            res = verifier.verify(check_id, bundle, requirement_id=requirement_id, **kwargs)
            if not res.passed:
                res.duration_ms = (time.time() - t0) * 1000.0
                return res

        return VerificationResult(
            check_id=check_id,
            requirement_id=requirement_id,
            verdict=VerificationVerdict.PASS,
            message=f"All {len(self.verifiers)} composite verifications passed",
            evidence_ids=evidence_ids,
            duration_ms=(time.time() - t0) * 1000.0,
        )
