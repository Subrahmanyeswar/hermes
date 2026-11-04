# core/test_diagnostics.py
"""
Test Failure Diagnostics & Repair Brief Generator for HERMES 2.x.
Parses output from test runners (Jest, Pytest, Mocha) and produces
deterministic failure classifications, execution evidence, and actionable repair briefs.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ==============================================================================
# 1. TYPED TEST FAILURE CATEGORIES
# ==============================================================================

class TestDiscoveryResult:
    TESTS_DISCOVERED_AND_PASSED = "TESTS_DISCOVERED_AND_PASSED"
    TESTS_DISCOVERED_AND_FAILED = "TESTS_DISCOVERED_AND_FAILED"
    TESTS_NOT_DISCOVERED = "TESTS_NOT_DISCOVERED"
    TEST_RUNNER_UNAVAILABLE = "TEST_RUNNER_UNAVAILABLE"
    TEST_EXECUTION_TIMEOUT = "TEST_EXECUTION_TIMEOUT"


class TestFailureCategory:
    TEST_HARNESS_FAILURE = "TEST_HARNESS_FAILURE"
    TEST_DISCOVERY_FAILURE = "TEST_DISCOVERY_FAILURE"
    TEST_IMPORT_FAILURE = "TEST_IMPORT_FAILURE"
    JAVASCRIPT_SYNTAX_ERROR = "JAVASCRIPT_SYNTAX_ERROR"
    TEST_ASSERTION_FAILURE = "TEST_ASSERTION_FAILURE"
    APPLICATION_RUNTIME_FAILURE = "APPLICATION_RUNTIME_FAILURE"
    SERVER_STARTUP_ERROR = "SERVER_STARTUP_ERROR"
    APPLICATION_VALIDATION_FAILURE = "APPLICATION_VALIDATION_FAILURE"
    DATABASE_TEST_FAILURE = "DATABASE_TEST_FAILURE"
    DATABASE_ERROR = "DATABASE_ERROR"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    TEST_TIMEOUT = "TEST_TIMEOUT"
    UNKNOWN_TEST_FAILURE = "UNKNOWN_TEST_FAILURE"


# ==============================================================================
# 2. TEST EXECUTION RECORD & REPAIR BRIEF
# ==============================================================================

@dataclass
class TestFailureDetail:
    __test__ = False
    suite_name: str = ""
    test_name: str = ""
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    failure_category: str = TestFailureCategory.UNKNOWN_TEST_FAILURE
    error_message: str = ""
    expected: Optional[str] = None
    received: Optional[str] = None
    stack_trace: Optional[str] = None
    diagnosis: str = ""
    suggested_action: str = ""


@dataclass
class TestExecutionEvidence:
    __test__ = False
    command: str
    working_dir: str
    exit_code: int
    duration_seconds: float
    start_timestamp: float
    end_timestamp: float
    runner_name: str = "unknown"
    runner_version: Optional[str] = None
    passed_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    discovery_result: str = TestDiscoveryResult.TESTS_NOT_DISCOVERED
    primary_failure_category: str = TestFailureCategory.UNKNOWN_TEST_FAILURE
    failures: List[TestFailureDetail] = field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""
    repair_brief: str = ""

    @property
    def is_valid_pass(self) -> bool:
        """True ONLY if tests were actually discovered and all passed without zero-test escape."""
        return (
            self.exit_code == 0
            and self.discovery_result == TestDiscoveryResult.TESTS_DISCOVERED_AND_PASSED
            and self.total_count > 0
            and self.failed_count == 0
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["is_valid_pass"] = self.is_valid_pass
        return d


# ==============================================================================
# 3. TEST OUTPUT PARSER
# ==============================================================================

class TestOutputParser:
    """Parses test runner output into structured TestExecutionEvidence and RepairBriefs."""

    @classmethod
    def parse(
        cls,
        command: str,
        working_dir: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_seconds: float = 0.0,
        start_timestamp: float = 0.0,
        end_timestamp: float = 0.0,
    ) -> TestExecutionEvidence:
        combined = (stdout or "") + "\n" + (stderr or "")
        evidence = TestExecutionEvidence(
            command=command,
            working_dir=working_dir,
            exit_code=exit_code,
            duration_seconds=duration_seconds,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            raw_stdout=stdout or "",
            raw_stderr=stderr or "",
        )

        # Detect runner
        cmd_lower = command.lower()
        if "jest" in cmd_lower or "npm test" in cmd_lower or "npx jest" in cmd_lower:
            evidence.runner_name = "jest"
            cls._parse_jest_output(combined, evidence)
        elif "pytest" in cmd_lower:
            evidence.runner_name = "pytest"
            cls._parse_pytest_output(combined, evidence)
        elif "mocha" in cmd_lower:
            evidence.runner_name = "mocha"
            cls._parse_mocha_output(combined, evidence)
        else:
            if "jest" in combined.lower():
                evidence.runner_name = "jest"
                cls._parse_jest_output(combined, evidence)
            elif "pytest" in combined.lower() or "collected" in combined.lower():
                evidence.runner_name = "pytest"
                cls._parse_pytest_output(combined, evidence)
            else:
                cls._parse_generic_output(combined, evidence)

        # Resolve discovery result
        if evidence.total_count > 0:
            if evidence.failed_count == 0 and evidence.exit_code == 0:
                evidence.discovery_result = TestDiscoveryResult.TESTS_DISCOVERED_AND_PASSED
            else:
                evidence.discovery_result = TestDiscoveryResult.TESTS_DISCOVERED_AND_FAILED
        elif "no tests found" in combined.lower() or "no test files found" in combined.lower() or (evidence.total_count == 0 and evidence.exit_code == 0):
            evidence.discovery_result = TestDiscoveryResult.TESTS_NOT_DISCOVERED
        else:
            evidence.discovery_result = TestDiscoveryResult.TESTS_DISCOVERED_AND_FAILED

        # Determine primary category
        if evidence.failures:
            evidence.primary_failure_category = evidence.failures[0].failure_category
        elif "no tests found" in combined.lower() or "no test files found" in combined.lower() or (evidence.total_count == 0 and evidence.exit_code == 0):
            evidence.primary_failure_category = TestFailureCategory.TEST_DISCOVERY_FAILURE
        elif exit_code != 0:
            evidence.primary_failure_category = cls._classify_raw_text(combined)

        # Generate repair brief
        evidence.repair_brief = cls._generate_repair_brief(evidence)
        return evidence

    @classmethod
    def _classify_raw_text(cls, text: str) -> str:
        t_low = text.lower()
        if "app.address is not a function" in t_low or "server.address is not a function" in t_low:
            return TestFailureCategory.TEST_IMPORT_FAILURE
        if "cannot find module" in t_low or "module_not_found" in t_low or "err_module_not_found" in t_low:
            # Distinguish local relative test import failures from genuine third-party package dependency failures
            mod_m = re.search(r'''cannot find module\s*['"]([^'"]+)['"]''', t_low)
            if mod_m:
                mod_name = mod_m.group(1).strip()
                if mod_name.startswith((".", "/")):
                    return TestFailureCategory.TEST_IMPORT_FAILURE
            return TestFailureCategory.DEPENDENCY_FAILURE
        if "test suite failed to run" in t_low:
            if "syntaxerror" in t_low or "unexpected token" in t_low or "unexpected identifier" in t_low:
                return TestFailureCategory.JAVASCRIPT_SYNTAX_ERROR
            if "app.address" in t_low or "require(" in t_low:
                return TestFailureCategory.TEST_IMPORT_FAILURE
        if "eaddrinuse" in t_low or "address already in use" in t_low:
            return TestFailureCategory.SERVER_STARTUP_ERROR
        if "sqlite_constraint" in t_low or "check constraint failed" in t_low or "sqlite_busy" in t_low or "no such table" in t_low:
            return TestFailureCategory.DATABASE_TEST_FAILURE
        if "syntaxerror" in t_low or "unexpected token" in t_low or "unexpected identifier" in t_low:
            return TestFailureCategory.JAVASCRIPT_SYNTAX_ERROR
        if "timeout" in t_low and ("exceeded" in t_low or "timed out" in t_low or "callback was not invoked" in t_low):
            return TestFailureCategory.TEST_TIMEOUT
        if "no tests found" in t_low or "no test files found" in t_low or ("0 passed" in t_low and "0 failed" in t_low):
            return TestFailureCategory.TEST_DISCOVERY_FAILURE
        if "expected" in t_low and "received" in t_low:
            return TestFailureCategory.TEST_ASSERTION_FAILURE
        if "assertionerror" in t_low or "expect(" in t_low or "toequal" in t_low:
            return TestFailureCategory.TEST_ASSERTION_FAILURE
        if "missing script: test" in t_low or "npm err! missing script" in t_low:
            return TestFailureCategory.TEST_HARNESS_FAILURE
        if "econnrefused" in t_low or "failed to connect" in t_low:
            return TestFailureCategory.APPLICATION_RUNTIME_FAILURE
        return TestFailureCategory.UNKNOWN_TEST_FAILURE

    @classmethod
    def _parse_jest_output(cls, text: str, evidence: TestExecutionEvidence) -> None:
        # Detect counts
        # Tests: 2 failed, 4 passed, 6 total
        tests_m = re.search(r'Tests:\s+(?:([0-9]+)\s+failed,?\s*)?(?:([0-9]+)\s+passed,?\s*)?([0-9]+)\s+total', text)
        if tests_m:
            failed_str = tests_m.group(1) or "0"
            passed_str = tests_m.group(2) or "0"
            total_str = tests_m.group(3) or "0"
            evidence.failed_count = int(failed_str)
            evidence.passed_count = int(passed_str)
            evidence.total_count = int(total_str)

        # Check for Supertest / Express app import mismatch
        if "app.address is not a function" in text or "server.address is not a function" in text:
            detail = TestFailureDetail(
                suite_name="Supertest Express Initialization",
                test_name="Server import shape for request(app)",
                failure_category=TestFailureCategory.TEST_IMPORT_FAILURE,
                error_message="TypeError: app.address is not a function. Supertest requires an Express app instance.",
                diagnosis=(
                    "Supertest was passed an object instead of the Express application instance. "
                    "Typically occurs when 'server.js' exports '{ app, db }' (named object) but the test does "
                    "'const app = require(\"../server\")'. The test must destructure: 'const { app } = require(\"../server\")'."
                ),
                suggested_action="In test files, change 'const app = require(\"../server\")' to 'const { app } = require(\"../server\")'.",
            )
            # Find file/line
            stack_m = re.search(r'at\s+.*?\((.*?):([0-9]+):[0-9]+\)', text)
            if stack_m:
                detail.file_path = stack_m.group(1)
                detail.line_number = int(stack_m.group(2))
                detail.stack_trace = stack_m.group(0)
            evidence.failures.append(detail)
            return

        # Check for Test suite failed to run
        if "test suite failed to run" in text.lower():
            suite_err_m = re.search(r'Test suite failed to run\s*\n\s*(.*?)(?=\n\s*at|\n\s*●|\Z)', text, re.DOTALL | re.IGNORECASE)
            err_line = suite_err_m.group(1).strip() if suite_err_m else "Test suite failed to run"
            stack_m = re.search(r'at\s+.*?\((.*?):([0-9]+):[0-9]+\)', text)
            file_p = stack_m.group(1) if stack_m else None
            line_n = int(stack_m.group(2)) if stack_m else None
            cat = cls._classify_raw_text(text)
            detail = TestFailureDetail(
                suite_name="Test Suite Execution",
                test_name="Suite Import and Initialization",
                failure_category=cat,
                error_message=err_line,
                diagnosis=f"Test runner halted during module load: {err_line[:120]}",
                suggested_action="Verify module relative path and exported structure match test require/import statement.",
                file_path=file_p,
                line_number=line_n,
                stack_trace=stack_m.group(0) if stack_m else None,
            )
            evidence.failures.append(detail)
            return

        # Check for SQLite constraint failure
        if "SQLITE_CONSTRAINT" in text or "CHECK constraint failed" in text:
            m_db = re.search(r'SQLITE_CONSTRAINT:\s*([^,\n]+)', text)
            err_msg = m_db.group(0) if m_db else "SQLite constraint failure during test execution"
            detail = TestFailureDetail(
                suite_name="Database Integrity",
                test_name="SQLite Constraint Check",
                failure_category=TestFailureCategory.DATABASE_TEST_FAILURE,
                error_message=err_msg,
                diagnosis=(
                    "Database operation in test or application route violated a SQLite constraint (e.g. CHECK constraint on 'direction IN (\"export\", \"import\", \"contact\")' "
                    "or foreign key/NOT NULL constraint). Ensure form values and test payloads send normalized values matching the schema."
                ),
                suggested_action="Normalize test request payload and server route handlers to send lowercase/valid enum values.",
            )
            evidence.failures.append(detail)

        # Parse individual test failure blocks: ● Test Suite › Test Name
        blocks = re.split(r'\n\s*●\s+', text)
        if len(blocks) > 1:
            for b in blocks[1:]:
                lines = b.strip().split("\n")
                if not lines:
                    continue
                header = lines[0].strip()
                suite_name = header
                test_name = ""
                if "›" in header:
                    parts = header.split("›")
                    suite_name = parts[0].strip()
                    test_name = parts[1].strip() if len(parts) > 1 else ""

                b_text = "\n".join(lines[1:])
                cat = cls._classify_raw_text(b_text)
                exp_val = None
                rec_val = None

                exp_line_m = re.search(r'Expected:\s*([^\n]+)', b_text)
                exp_val = exp_line_m.group(1).strip() if exp_line_m else None
                if not exp_val:
                    exp_m = re.search(r'Expected:\s*(.*?)(?=\n\s*Received:|\n\s*at|\Z)', b_text, re.DOTALL)
                    if exp_m:
                        exp_val = exp_m.group(1).strip()

                rec_line_m = re.search(r'Received:\s*([^\n]+)', b_text)
                rec_val = rec_line_m.group(1).strip() if rec_line_m else None
                if not rec_val:
                    rec_m = re.search(r'Received:\s*(.*?)(?=\n\s*at|\Z)', b_text, re.DOTALL)
                    if rec_m:
                        rec_val = rec_m.group(1).strip()

                stack_m = re.search(r'at\s+(?:.*?\()?(.*?):([0-9]+):[0-9]+\)?', b_text)
                file_p = None
                line_n = None
                if stack_m:
                    file_p = stack_m.group(1).strip()
                    line_n = int(stack_m.group(2))

                diag = ""
                sugg = ""
                if exp_val and rec_val:
                    cat = TestFailureCategory.TEST_ASSERTION_FAILURE
                    diag = f"Assertion mismatch in '{test_name or suite_name}': expected {exp_val[:80]}, but received {rec_val[:80]}."
                    loc_str = f" at {file_p}:{line_n}" if file_p else ""
                    sugg = f"Inspect both the backend route handler response and test assertion{loc_str} to resolve contract alignment."
                elif cat in (TestFailureCategory.TEST_IMPORT_FAILURE, TestFailureCategory.JAVASCRIPT_SYNTAX_ERROR):
                    diag = f"Import or syntax failure in test suite: {lines[1] if len(lines) > 1 else header}"
                    sugg = "Verify exported module shape matches test require/import statement and syntax is valid."

                detail = TestFailureDetail(
                    suite_name=suite_name,
                    test_name=test_name,
                    file_path=file_p,
                    line_number=line_n,
                    failure_category=cat,
                    error_message=lines[1].strip() if len(lines) > 1 else header,
                    expected=exp_val,
                    received=rec_val,
                    stack_trace=b_text[:500],
                    diagnosis=diag,
                    suggested_action=sugg,
                )
                evidence.failures.append(detail)

    @classmethod
    def _parse_pytest_output(cls, text: str, evidence: TestExecutionEvidence) -> None:
        # Check for FAILED tests/test_*.py::test_name
        fail_matches = re.findall(r'FAILED\s+([^\s:]+)::([^\s\-]+)\s*-\s*(.*)', text)
        for f_path, t_name, reason in fail_matches:
            cat = cls._classify_raw_text(reason)
            evidence.failures.append(
                TestFailureDetail(
                    suite_name=f_path,
                    test_name=t_name,
                    file_path=f_path,
                    failure_category=cat,
                    error_message=reason.strip(),
                    diagnosis=f"Pytest test '{t_name}' in {f_path} failed: {reason.strip()}",
                    suggested_action="Review failing assertion or exception in test output.",
                )
            )

    @classmethod
    def _parse_mocha_output(cls, text: str, evidence: TestExecutionEvidence) -> None:
        cls._parse_generic_output(text, evidence)

    @classmethod
    def _parse_generic_output(cls, text: str, evidence: TestExecutionEvidence) -> None:
        cat = cls._classify_raw_text(text)
        evidence.failures.append(
            TestFailureDetail(
                suite_name="Generic Test Suite",
                test_name=evidence.command,
                failure_category=cat,
                error_message=text[-300:].strip() if text else "Test command exited with non-zero code",
                diagnosis=f"Test runner produced exit code {evidence.exit_code}. Category: {cat}",
                suggested_action="Inspect full stdout/stderr to identify failing assertion or syntax error.",
            )
        )

    @classmethod
    def _generate_repair_brief(cls, evidence: TestExecutionEvidence) -> str:
        if evidence.exit_code == 0:
            return "All test suites passed successfully (exit code 0)."

        lines = [
            f"[TEST EXECUTION FAILURE DIAGNOSIS]",
            f"Command: {evidence.command} (exit code {evidence.exit_code})",
            f"Primary Category: {evidence.primary_failure_category}",
            f"Total Failures: {len(evidence.failures)}",
            "",
        ]

        for i, f in enumerate(evidence.failures[:5], 1):
            lines.append(f"Failure #{i}:")
            if f.file_path:
                lines.append(f"  Location: {f.file_path}:{f.line_number or ''}")
            if f.test_name:
                lines.append(f"  Test: {f.suite_name} › {f.test_name}")
            lines.append(f"  Category: {f.failure_category}")
            lines.append(f"  Error: {f.error_message}")
            if f.expected and f.received:
                lines.append(f"  Expected: {f.expected}")
                lines.append(f"  Received: {f.received}")
            if f.diagnosis:
                lines.append(f"  Diagnosis: {f.diagnosis}")
            if f.suggested_action:
                lines.append(f"  Action: {f.suggested_action}")
            lines.append("")

        lines.append(
            "CRITICAL: Do NOT re-run this exact test command without first modifying the relevant application or test files! "
            "Re-running unchanged failing tests is blocked by the Duplicate Validation Guard."
        )
        return "\n".join(lines)
