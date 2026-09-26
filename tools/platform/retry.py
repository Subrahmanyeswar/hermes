# tools/platform/retry.py
"""
Deterministic Retry Policy and Idempotency Enforcement for HERMES 2.x Tool Platform.
Guarantees that non-idempotent operations are never blindly duplicated,
and error recovery follows strict safety budgets.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Dict, Optional

from tools.platform.specs import ToolSpec, RiskMetadata
from tools.platform.errors import ToolError, ToolErrorCode


class RetryDecision(str, enum.Enum):
    SAFE_TO_RETRY = "SAFE_TO_RETRY"
    RETRY_WITH_MODIFIED_INPUT = "RETRY_WITH_MODIFIED_INPUT"
    DO_NOT_RETRY = "DO_NOT_RETRY"
    ASK_USER = "ASK_USER"
    ESCALATE = "ESCALATE"


@dataclass
class RetryEvaluation:
    """Diagnostic outcome of retry policy evaluation."""
    decision: RetryDecision
    reason: str
    attempt_allowed: bool
    current_attempt: int
    max_budget: int
    delay_seconds: float = 0.0


class RetryPolicy:
    """
    Evaluates whether a failed tool action can be safely retried.
    """

    DEFAULT_MAX_RETRIES: int = 2

    @classmethod
    def evaluate(
        cls,
        spec: Optional[ToolSpec],
        error: ToolError,
        current_attempt: int = 0,
        max_budget: Optional[int] = None,
    ) -> RetryEvaluation:
        """
        Evaluate retry safety for a failed tool invocation.
        """
        budget = max_budget if max_budget is not None else cls.DEFAULT_MAX_RETRIES

        # 1. Budget check
        if current_attempt >= budget:
            return RetryEvaluation(
                decision=RetryDecision.DO_NOT_RETRY,
                reason=f"Exhausted maximum retry budget ({budget} attempts).",
                attempt_allowed=False,
                current_attempt=current_attempt,
                max_budget=budget,
            )

        # 2. Rejection for non-retryable error categories
        if error.code in (
            ToolErrorCode.PERMISSION_DENIED,
            ToolErrorCode.PATH_OUTSIDE_WORKSPACE,
            ToolErrorCode.EDIT_PATH_OUTSIDE_WORKSPACE,
            ToolErrorCode.COMMAND_REJECTED,
        ):
            return RetryEvaluation(
                decision=RetryDecision.DO_NOT_RETRY,
                reason=f"Security violation ({error.code.value}) cannot be retried without policy modification.",
                attempt_allowed=False,
                current_attempt=current_attempt,
                max_budget=budget,
            )

        # 3. User interaction required
        if error.code == ToolErrorCode.USER_REQUIRED:
            return RetryEvaluation(
                decision=RetryDecision.ASK_USER,
                reason="User interaction or confirmation is required.",
                attempt_allowed=False,
                current_attempt=current_attempt,
                max_budget=budget,
            )

        # 4. Schema / parameter mismatch requires modification
        if error.code in (
            ToolErrorCode.INVALID_ARGUMENT,
            ToolErrorCode.FILE_CONFLICT,
            ToolErrorCode.FILE_NOT_FOUND,
            ToolErrorCode.FILE_EXISTS_OVERWRITE_REQUIRED,
            ToolErrorCode.EDIT_TARGET_NOT_FOUND,
            ToolErrorCode.EDIT_TARGET_NOT_UNIQUE,
            ToolErrorCode.EDIT_EXPECTED_COUNT_MISMATCH,
            ToolErrorCode.EDIT_FILE_CHANGED,
            ToolErrorCode.EDIT_POSTCONDITION_FAILED,
            ToolErrorCode.EDIT_SUSPICIOUS_LARGE_DIFF,
            ToolErrorCode.GREP_INVALID_PATTERN,
        ):
            return RetryEvaluation(
                decision=RetryDecision.RETRY_WITH_MODIFIED_INPUT,
                reason=f"Error {error.code.value} requires corrected or fresh parameter inputs.",
                attempt_allowed=True,
                current_attempt=current_attempt + 1,
                max_budget=budget,
            )


        # 5. Non-idempotent operations must never be blindly retried on failure
        if spec and spec.risk:
            if not spec.risk.idempotent:
                return RetryEvaluation(
                    decision=RetryDecision.RETRY_WITH_MODIFIED_INPUT,
                    reason=f"Tool '{spec.canonical_name}' is non-idempotent. Blind retry prohibited to prevent side-effect duplication.",
                    attempt_allowed=False,
                    current_attempt=current_attempt,
                    max_budget=budget,
                )

        # 6. Transient timeout or process network glitch may be safely retried
        if error.code in (
            ToolErrorCode.COMMAND_TIMEOUT,
            ToolErrorCode.PROVIDER_UNAVAILABLE,
        ):
            return RetryEvaluation(
                decision=RetryDecision.SAFE_TO_RETRY,
                reason=f"Transient issue ({error.code.value}) is eligible for retry.",
                attempt_allowed=True,
                current_attempt=current_attempt + 1,
                max_budget=budget,
                delay_seconds=0.5 * (current_attempt + 1),
            )

        # Default fallback
        return RetryEvaluation(
            decision=RetryDecision.RETRY_WITH_MODIFIED_INPUT,
            reason="Review tool failure observation and adjust parameters before retrying.",
            attempt_allowed=True,
            current_attempt=current_attempt + 1,
            max_budget=budget,
        )
