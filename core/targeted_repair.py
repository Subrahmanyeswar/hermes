# core/targeted_repair.py
"""
Targeted Repair & Failure Classification Engine for HERMES vNext (Prompt 7).
Implements the minimum intervention principle:
  Repair the smallest failing unit with the smallest possible intervention.

Hierarchy:
  Scope 0: No repair (Verification passes, repair_calls = 0)
  Scope 1: Local file repair (Single affected file isolated and repaired)
  Scope 2: Dependency subset repair (Direct causal dependency repaired together)
  Scope 3: Task-level repair (Failure cannot safely be isolated to single file)
  Scope 4: Mission-level recovery (Broad failure requiring replanning/regeneration)

Guarantees:
  - Bounded retry cap (default max 3 attempts)
  - Unaffected artifact hash preservation (verified bit-for-bit unchanged)
  - Deterministic failure classification
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

from loguru import logger


class FailureType(str, Enum):
    PARSE_FAILURE = "PARSE_FAILURE"
    TOOL_DISPATCH_FAILURE = "TOOL_DISPATCH_FAILURE"
    FILE_WRITE_FAILURE = "FILE_WRITE_FAILURE"
    PATH_VALIDATION_FAILURE = "PATH_VALIDATION_FAILURE"
    SYNTAX_FAILURE = "SYNTAX_FAILURE"
    STRUCTURAL_FAILURE = "STRUCTURAL_FAILURE"
    SEMANTIC_FAILURE = "SEMANTIC_FAILURE"
    TEST_FAILURE = "TEST_FAILURE"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    TIMEOUT_FAILURE = "TIMEOUT_FAILURE"
    CANCELLATION_FAILURE = "CANCELLATION_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class RepairScope(IntEnum):
    SCOPE_0_NO_REPAIR = 0
    SCOPE_1_LOCAL_FILE = 1
    SCOPE_2_DEPENDENCY_SUBSET = 2
    SCOPE_3_TASK_LEVEL = 3
    SCOPE_4_MISSION_RECOVERY = 4


@dataclass
class FailureDiagnosis:
    failure_type: FailureType
    root_cause: str
    affected_files: List[str] = field(default_factory=list)
    suggested_scope: RepairScope = RepairScope.SCOPE_1_LOCAL_FILE
    error_details: Optional[str] = None
    is_recoverable: bool = True


@dataclass
class ArtifactSnapshot:
    """Captures file states and SHA-256 hashes prior to repair."""
    file_hashes: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def capture(cls, paths: List[str | Path]) -> ArtifactSnapshot:
        hashes = {}
        for p in paths:
            path_obj = Path(p)
            if path_obj.exists() and path_obj.is_file():
                content = path_obj.read_bytes()
                hashes[str(path_obj.resolve())] = hashlib.sha256(content).hexdigest()
        return cls(file_hashes=hashes)

    def verify_unaffected_unchanged(self, unaffected_paths: List[str | Path]) -> Tuple[bool, List[str]]:
        """Verify that unaffected artifacts maintain identical SHA-256 hashes."""
        mismatches = []
        for p in unaffected_paths:
            path_obj = Path(p)
            resolved = str(path_obj.resolve())
            if resolved in self.file_hashes:
                if not path_obj.exists():
                    mismatches.append(f"Deleted unaffected file: {p}")
                    continue
                current_hash = hashlib.sha256(path_obj.read_bytes()).hexdigest()
                if current_hash != self.file_hashes[resolved]:
                    mismatches.append(
                        f"Hash mismatch for unaffected file {p}: expected {self.file_hashes[resolved][:10]} vs {current_hash[:10]}"
                    )
        return len(mismatches) == 0, mismatches


class FailureClassifier:
    """Deterministic classifier mapping error signals to typed FailureDiagnosis."""

    @staticmethod
    def classify(
        error_text: str,
        affected_files: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> FailureDiagnosis:
        err = error_text.lower()
        files = affected_files or []

        # 1. Cancellation
        if "cancel" in err or "aborted" in err or "interrupted" in err:
            return FailureDiagnosis(
                failure_type=FailureType.CANCELLATION_FAILURE,
                root_cause="Operation was cancelled or aborted",
                affected_files=files,
                suggested_scope=RepairScope.SCOPE_0_NO_REPAIR,
                error_details=error_text,
                is_recoverable=False
            )

        # 2. Timeout
        if "timeout" in err or "timed out" in err or "deadline exceeded" in err:
            return FailureDiagnosis(
                failure_type=FailureType.TIMEOUT_FAILURE,
                root_cause="Execution exceeded allocated time budget",
                affected_files=files,
                suggested_scope=RepairScope.SCOPE_3_TASK_LEVEL,
                error_details=error_text,
                is_recoverable=False
            )

        # 3. Path Validation / Security Traversal
        if (
            "path traversal" in err
            or "outside workspace" in err
            or "invalid path" in err
            or "escapes workspace" in err
        ):
            return FailureDiagnosis(
                failure_type=FailureType.PATH_VALIDATION_FAILURE,
                root_cause="Target path validation or workspace boundary violation",
                affected_files=files,
                suggested_scope=RepairScope.SCOPE_1_LOCAL_FILE,
                error_details=error_text,
                is_recoverable=True
            )

        # 4. File Write Failure
        if (
            "permission denied" in err
            or "disk full" in err
            or "read-only file system" in err
            or "failed to write" in err
            or "cannot open file" in err
        ):
            return FailureDiagnosis(
                failure_type=FailureType.FILE_WRITE_FAILURE,
                root_cause="Filesystem write error or I/O failure",
                affected_files=files,
                suggested_scope=RepairScope.SCOPE_1_LOCAL_FILE,
                error_details=error_text,
                is_recoverable=True
            )

        # 5. Parse Failure (Tool / JSON response parsing)
        if (
            "jsondecodeerror" in err
            or "expecting value" in err
            or "invalid json" in err
            or "could not parse" in err
            or "extra data" in err
        ):
            return FailureDiagnosis(
                failure_type=FailureType.PARSE_FAILURE,
                root_cause="Model response or tool payload parsing failure",
                affected_files=files,
                suggested_scope=RepairScope.SCOPE_3_TASK_LEVEL,
                error_details=error_text,
                is_recoverable=True
            )

        # 6. Tool Dispatch Failure
        if (
            "unknown tool" in err
            or "tool not found" in err
            or "invalid arguments" in err
            or "missing required parameter" in err
        ):
            return FailureDiagnosis(
                failure_type=FailureType.TOOL_DISPATCH_FAILURE,
                root_cause="Tool dispatch schema error or unregistered tool invocation",
                affected_files=files,
                suggested_scope=RepairScope.SCOPE_3_TASK_LEVEL,
                error_details=error_text,
                is_recoverable=True
            )

        # 7. Syntax Failure (Python SyntaxError, IndentationError, JS syntax)
        if (
            "syntaxerror" in err
            or "indentationerror" in err
            or "unexpected token" in err
            or "invalid or unexpected token" in err
        ):
            match = re.search(r"(?:SyntaxError|IndentationError):\s*(.*)", error_text, re.IGNORECASE)
            msg = match.group(1) if match else "Syntax or indentation error detected"
            scope = RepairScope.SCOPE_1_LOCAL_FILE if len(files) <= 1 else RepairScope.SCOPE_2_DEPENDENCY_SUBSET
            return FailureDiagnosis(
                failure_type=FailureType.SYNTAX_FAILURE,
                root_cause=f"Syntax defect: {msg}",
                affected_files=files,
                suggested_scope=scope,
                error_details=error_text,
                is_recoverable=True
            )

        # 8. Structural Failure (Missing closing tag, missing required skeleton elements)
        if (
            "missing doctype" in err
            or "doctype" in err
            or "unclosed tag" in err
            or "missing required section" in err
            or "structural validation failed" in err
            or "empty file" in err
        ):
            scope = RepairScope.SCOPE_1_LOCAL_FILE if len(files) <= 1 else RepairScope.SCOPE_2_DEPENDENCY_SUBSET
            return FailureDiagnosis(
                failure_type=FailureType.STRUCTURAL_FAILURE,
                root_cause="Required document structure or markup format missing",
                affected_files=files,
                suggested_scope=scope,
                error_details=error_text,
                is_recoverable=True
            )

        # 9. Dependency Failure (ImportError, ModuleNotFoundError, unresolved reference)
        if (
            "modulenotfounderror" in err
            or "importerror" in err
            or "cannot import name" in err
            or "is not defined" in err
            or "referenceerror" in err
        ):
            return FailureDiagnosis(
                failure_type=FailureType.DEPENDENCY_FAILURE,
                root_cause="Unresolved symbol, module import, or cross-file reference defect",
                affected_files=files,
                suggested_scope=RepairScope.SCOPE_2_DEPENDENCY_SUBSET,
                error_details=error_text,
                is_recoverable=True
            )

        # 10. Semantic Failure (Type error, attribute error, route mismatch)
        if (
            "typeerror" in err
            or "attributeerror" in err
            or "valueerror" in err
            or "keyerror" in err
            or "route not found" in err
            or "unexpected status code" in err
        ):
            scope = RepairScope.SCOPE_1_LOCAL_FILE if len(files) <= 1 else RepairScope.SCOPE_2_DEPENDENCY_SUBSET
            return FailureDiagnosis(
                failure_type=FailureType.SEMANTIC_FAILURE,
                root_cause="Runtime type, attribute, or logic semantic mismatch",
                affected_files=files,
                suggested_scope=scope,
                error_details=error_text,
                is_recoverable=True
            )

        # 11. Test Failure (AssertionError, pytest failure)
        if "assertionerror" in err or "test failed" in err or "failed assertion" in err:
            return FailureDiagnosis(
                failure_type=FailureType.TEST_FAILURE,
                root_cause="Automated assertion or unit test expectation failed",
                affected_files=files,
                suggested_scope=RepairScope.SCOPE_2_DEPENDENCY_SUBSET if len(files) > 1 else RepairScope.SCOPE_1_LOCAL_FILE,
                error_details=error_text,
                is_recoverable=True
            )

        # 12. Unknown
        return FailureDiagnosis(
            failure_type=FailureType.UNKNOWN_FAILURE,
            root_cause="Unclassified execution defect",
            affected_files=files,
            suggested_scope=RepairScope.SCOPE_3_TASK_LEVEL,
            error_details=error_text[:200] if error_text else None,
            is_recoverable=True
        )


class TargetedRepairManager:
    """
    Coordinates targeted repairs with strict scope escalation,
    bounded retry budgets, and artifact hash integrity protection.
    """

    def __init__(self, max_repair_attempts: int = 3):
        self.max_repair_attempts = max_repair_attempts
        self.repair_records: Dict[str, List[Dict[str, Any]]] = {}

    def select_repair_scope(
        self,
        diagnosis: FailureDiagnosis,
        total_files: List[str]
    ) -> Tuple[RepairScope, List[str]]:
        """
        Determines the minimal necessary repair scope and target file list.
        Rule: If exactly 1 file is invalid and others are valid, isolate to Scope 1.
        """
        if not diagnosis.is_recoverable:
            return RepairScope.SCOPE_0_NO_REPAIR, []

        affected = diagnosis.affected_files
        if not affected:
            # Fallback to single task scope if no file specified
            return RepairScope.SCOPE_3_TASK_LEVEL, total_files

        if len(affected) == 1 and len(total_files) > 1:
            # Single file failure in multi-file project -> Scope 1 Local Repair
            return RepairScope.SCOPE_1_LOCAL_FILE, [affected[0]]

        if len(affected) > 1 and len(affected) < len(total_files):
            # Subset of files failed -> Scope 2 Dependency Subset
            return RepairScope.SCOPE_2_DEPENDENCY_SUBSET, affected

        if diagnosis.suggested_scope == RepairScope.SCOPE_3_TASK_LEVEL:
            return RepairScope.SCOPE_3_TASK_LEVEL, total_files

        return diagnosis.suggested_scope, affected

    def can_attempt_repair(self, task_id: str, diagnosis: FailureDiagnosis) -> bool:
        """Check whether repair attempts remain for the given task."""
        if not diagnosis.is_recoverable:
            return False
        attempts = len(self.repair_records.get(task_id, []))
        return attempts < self.max_repair_attempts

    def prepare_repair(
        self,
        task_id: str,
        target_files: List[str],
        all_workspace_files: List[str]
    ) -> ArtifactSnapshot:
        """
        Captures baseline snapshot of all workspace files before repair execution.
        """
        snapshot = ArtifactSnapshot.capture(all_workspace_files)
        logger.debug(
            "TargetedRepair: Captured baseline snapshot for {} files before repairing {}",
            len(all_workspace_files), target_files
        )
        return snapshot

    def record_repair_result(
        self,
        task_id: str,
        diagnosis: FailureDiagnosis,
        scope: RepairScope,
        repaired_files: List[str],
        verification_passed: bool,
        duration_ms: float = 0.0
    ) -> Dict[str, Any]:
        """Record completed repair attempt in history."""
        if task_id not in self.repair_records:
            self.repair_records[task_id] = []

        record = {
            "attempt": len(self.repair_records[task_id]) + 1,
            "failure_type": diagnosis.failure_type.value,
            "root_cause": diagnosis.root_cause,
            "scope": scope.name,
            "repaired_files": repaired_files,
            "passed": verification_passed,
            "duration_ms": duration_ms,
            "timestamp": time.time()
        }
        self.repair_records[task_id].append(record)
        return record


# Global singleton
targeted_repair_manager = TargetedRepairManager()
