"""
core/failure_classifier.py
Hermes 2.x - Failure Classification and Model Failover Decider.

Classifies errors into distinct categories and ensures that ONLY genuine
transient provider errors trigger model failover. Local code, contract,
environment, and test failures are directed to deterministic repair owners.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, Optional, Union


class FailureCategory(str, Enum):
    # Provider-level failures
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_CONNECTION_FAILURE = "PROVIDER_CONNECTION_FAILURE"
    PROVIDER_TRANSIENT_SERVER_ERROR = "PROVIDER_TRANSIENT_SERVER_ERROR"
    PROVIDER_AUTH_ERROR = "PROVIDER_AUTH_ERROR"
    PROVIDER_INVALID_REQUEST = "PROVIDER_INVALID_REQUEST"

    # Local code & verification failures
    SYNTAX_ERROR_JS = "SYNTAX_ERROR_JS"
    SYNTAX_ERROR_PYTHON = "SYNTAX_ERROR_PYTHON"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    FILESYSTEM_ERROR = "FILESYSTEM_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    TEST_FAILURE_API = "TEST_FAILURE_API"
    BROWSER_RUNTIME_ERROR = "BROWSER_RUNTIME_ERROR"
    STUCK_LOOP_ERROR = "STUCK_LOOP_ERROR"

    # Granular Test Execution Failure Categories
    TEST_HARNESS_FAILURE = "TEST_HARNESS_FAILURE"
    TEST_DISCOVERY_FAILURE = "TEST_DISCOVERY_FAILURE"
    TEST_IMPORT_FAILURE = "TEST_IMPORT_FAILURE"
    TEST_ASSERTION_FAILURE = "TEST_ASSERTION_FAILURE"
    APPLICATION_RUNTIME_FAILURE = "APPLICATION_RUNTIME_FAILURE"
    APPLICATION_VALIDATION_FAILURE = "APPLICATION_VALIDATION_FAILURE"
    DATABASE_TEST_FAILURE = "DATABASE_TEST_FAILURE"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    TEST_TIMEOUT = "TEST_TIMEOUT"
    UNKNOWN_TEST_FAILURE = "UNKNOWN_TEST_FAILURE"


# Set of failure categories that are genuinely transient provider errors
TRANSIENT_PROVIDER_FAILURES = {
    FailureCategory.PROVIDER_RATE_LIMIT,
    FailureCategory.PROVIDER_TIMEOUT,
    FailureCategory.PROVIDER_CONNECTION_FAILURE,
    FailureCategory.PROVIDER_TRANSIENT_SERVER_ERROR,
}


class FailureClassifier:
    """Classifies raw errors, exceptions, or tool outputs into typed failure categories."""

    @classmethod
    def classify(
        cls,
        error: Union[Exception, str, Dict[str, Any]],
        error_message: Optional[str] = None,
        context: Optional[Any] = None,
    ) -> FailureCategory:
        """Deterministically map an error or error payload to a FailureCategory."""
        if isinstance(error, dict):
            # Check structured fields
            err_code = str(error.get("error_code") or error.get("code") or "")
            err_type = str(error.get("type") or "")
            err_msg = str(error.get("message") or error.get("error") or error.get("stderr") or "")
            combined = f"{err_code} {err_type} {err_msg}".lower()
        elif isinstance(error, Exception):
            err_name = type(error).__name__
            err_msg = str(error)
            combined = f"{err_name}: {err_msg}".lower()
        else:
            combined = str(error).lower()

        if error_message:
            combined = f"{combined} {str(error_message).lower()}"
        if context:
            combined = f"{combined} {str(context).lower()}"

        # 1. Stuck loop
        if any(k in combined for k in ("stuck_loop", "oscillation_detected", "repeated_identical_failure", "tool_rejected_no_progress", "agent_no_progress")):
            return FailureCategory.STUCK_LOOP_ERROR

        # 2. Syntax errors
        if "syntaxerror" in combined or "indentationerror" in combined or "invalid syntax" in combined:
            if any(k in combined for k in ("python", ".py", "traceback")):
                return FailureCategory.SYNTAX_ERROR_PYTHON
            if any(k in combined for k in ("javascript", "node", ".js", "unexpected token", "missing ) after argument")):
                return FailureCategory.SYNTAX_ERROR_JS
            return FailureCategory.SYNTAX_ERROR_PYTHON

        if any(k in combined for k in ("unexpected identifier", "unexpected token", "missing semicolon", "referenceerror", "node --check")):
            return FailureCategory.SYNTAX_ERROR_JS

        # 3. Contract mismatch
        if any(k in combined for k in ("contract", "discrepancy", "missing_dom_id", "missing dom element", "unregistered_js_id", "interface mismatch", "response shape mismatch", "envelope")):
            return FailureCategory.CONTRACT_MISMATCH

        # 4. Filesystem / Path errors
        if any(k in combined for k in ("filenotfounderror", "path traversal", "canonicalpathresolver", "outside workspace", "no such file or directory")):
            return FailureCategory.FILESYSTEM_ERROR

        # 5. Environment errors
        if any(k in combined for k in ("node executable not found", "command not found", "executable not found", "permission denied", "environment_error", "eacces", "eperm")):
            return FailureCategory.ENVIRONMENT_ERROR

        # 6. Granular Test failures
        if any(k in combined for k in ("app.address is not a function", "server.address is not a function")):
            return FailureCategory.TEST_IMPORT_FAILURE
        if "sqlite_constraint" in combined or "check constraint failed" in combined:
            return FailureCategory.DATABASE_TEST_FAILURE
        if "cannot find module" in combined or "module_not_found" in combined:
            return FailureCategory.DEPENDENCY_FAILURE
        if any(k in combined for k in ("assertionerror", "pytest", "test failed", "test_failure", "failing tests", "expected:", "received:")):
            if "expected" in combined and "received" in combined:
                return FailureCategory.TEST_ASSERTION_FAILURE
            return FailureCategory.TEST_FAILURE_API

        # 7. Browser runtime
        if any(k in combined for k in ("cdp", "browser", "chrome", "page crash", "target closed", "navigation failed", "typeerror", "referenceerror", "is not a function", "unhandled javascript")):
            return FailureCategory.BROWSER_RUNTIME_ERROR

        # 8. Provider Rate Limit
        if any(k in combined for k in ("429", "rate limit", "resource_exhausted", "quota exceeded", "too many requests")):
            return FailureCategory.PROVIDER_RATE_LIMIT

        # 9. Provider Timeout
        if any(k in combined for k in ("timed out", "timeout", "deadline exceeded", "readtimeout", "connecttimeout")):
            return FailureCategory.PROVIDER_TIMEOUT

        # 10. Provider Connection Failure
        if any(k in combined for k in ("connection refused", "connection error", "connection reset", "dns resolution failed", "gaierror", "failed to establish a new connection")):
            return FailureCategory.PROVIDER_CONNECTION_FAILURE

        # 11. Provider Server Error (500, 502, 503, 504)
        if any(k in combined for k in ("500 internal server error", "502 bad gateway", "503 service unavailable", "504 gateway timeout", "server_error", "internal server error")):
            return FailureCategory.PROVIDER_TRANSIENT_SERVER_ERROR

        # 12. Provider Auth Error
        if any(k in combined for k in ("401", "403", "unauthorized", "invalid api key", "authentication failed", "invalid_api_key", "permission_denied")) and not ("tool_rejected" in combined or "forbidden" in combined and "modifications" in combined):
            return FailureCategory.PROVIDER_AUTH_ERROR

        # 13. Provider Invalid Request
        if any(k in combined for k in ("400", "bad request", "invalid argument", "maximum context length", "context_length_exceeded", "prompt too long")):
            return FailureCategory.PROVIDER_INVALID_REQUEST

        # Fallback to filesystem if path-like, else invalid request or environment
        if "path" in combined or "directory" in combined:
            return FailureCategory.FILESYSTEM_ERROR

        return FailureCategory.PROVIDER_INVALID_REQUEST

    @classmethod
    def should_trigger_provider_failover(cls, error: Union[Exception, str, Dict[str, Any], FailureCategory]) -> bool:
        """
        Returns True ONLY for genuine transient provider errors (rate limits, timeouts,
        connection failures, and 5xx transient server responses).
        Returns False for auth errors, bad requests, and all local code/verification errors.
        """
        category: FailureCategory
        if isinstance(error, FailureCategory):
            category = error
        else:
            category = cls.classify(error)

        return category in TRANSIENT_PROVIDER_FAILURES
