# core/error_handler.py
# Centralised error handling for HERMES.
# Every failure mode in the 12-stage pipeline is defined here.
# Every error produces a structured ErrorResult — never a raw exception propagated to the user.
# Recovery strategies are defined here and used by the orchestrator.
#
# The 6 failure modes this module handles:
#   1. JSON parse failure: T1 response cannot be parsed → re-prompt once with V2 → FAILED
#   2. Tool not found: T1 names an unknown tool → structured error injected → re-prompt once
#   3. Tool execution failure: exit_code != 0 → inject stderr → retry up to 3 times
#   4. Ollama timeout: T1 or T2 exceeds 120s → return [TIMEOUT] tagged result
#   5. Tier 3 API failure: Claude API errors → return T1 result with [UNVERIFIED] tag
#   6. Memory parse error: MEMORY.md corrupted → empty context fallback, session continues

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any
from loguru import logger


class FailureMode(Enum):
    """Every possible failure mode in the HERMES pipeline."""
    JSON_PARSE_FAILURE      = "json_parse_failure"
    TOOL_NOT_FOUND          = "tool_not_found"
    TOOL_EXECUTION_FAILURE  = "tool_execution_failure"
    OLLAMA_TIMEOUT          = "ollama_timeout"
    TIER3_API_FAILURE       = "tier3_api_failure"
    MEMORY_PARSE_ERROR      = "memory_parse_error"
    UNKNOWN                 = "unknown"


class RecoveryAction(Enum):
    """What the orchestrator should do after an error."""
    RETRY_WITH_V2_PROMPT     = "retry_with_v2_prompt"       # Use two-shot prompt on retry
    RETRY_WITH_ERROR_CONTEXT = "retry_with_error_context"   # Inject error into next attempt
    RETURN_WITH_TAG          = "return_with_tag"             # Return result with warning tag
    USE_EMPTY_FALLBACK       = "use_empty_fallback"          # Use empty/safe default
    FAIL_TASK                = "fail_task"                   # Mark task FAILED, stop retrying


@dataclass
class ErrorResult:
    """
    Structured result for any pipeline failure.
    The orchestrator receives this and decides how to respond based on recovery_action.
    The session NEVER crashes — ErrorResult is always returned instead of raising.
    """
    failure_mode: FailureMode
    recovery_action: RecoveryAction
    user_message: str           # What to show the user in the chat panel
    technical_detail: str       # Full detail for logs and debugging
    tag: str = ""               # Optional tag like [TIMEOUT] or [UNVERIFIED] prepended to output
    retry_count: int = 0        # How many retries have been attempted so far
    max_retries: int = 3        # Maximum allowed retries for this failure mode
    context_for_retry: str = "" # Extra context to inject into the retry prompt

    @property
    def can_retry(self) -> bool:
        """True if another attempt is allowed."""
        return (
            self.retry_count < self.max_retries
            and self.recovery_action in (
                RecoveryAction.RETRY_WITH_V2_PROMPT,
                RecoveryAction.RETRY_WITH_ERROR_CONTEXT,
            )
        )

    @property
    def is_final(self) -> bool:
        """True if no more recovery is possible — must return result to user."""
        return (
            not self.can_retry
            or self.recovery_action in (
                RecoveryAction.RETURN_WITH_TAG,
                RecoveryAction.USE_EMPTY_FALLBACK,
                RecoveryAction.FAIL_TASK,
            )
        )

    def tagged_output(self, base_output: str) -> str:
        """Prepend the error tag to base_output if a tag is set."""
        if self.tag:
            return f"[{self.tag}] {base_output}"
        return base_output

    def to_log_dict(self) -> dict:
        return {
            "failure_mode": self.failure_mode.value,
            "recovery_action": self.recovery_action.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "can_retry": self.can_retry,
            "tag": self.tag,
            "technical_detail": self.technical_detail[:200],
        }


class ErrorHandler:
    """
    Factory class that produces ErrorResult objects for every known failure mode.
    The orchestrator calls one method per failure type and receives a structured
    ErrorResult telling it exactly what to do next.
    """

    def json_parse_failure(self, raw_response: str, attempt: int = 0) -> ErrorResult:
        """T1 produced a response that cannot be parsed as a valid JSON tool call."""
        logger.warning(
            f"ErrorHandler: JSON parse failure | attempt={attempt} | "
            f"response_length={len(raw_response)} | "
            f"response_preview={raw_response[:80]!r}"
        )

        if attempt == 0:
            return ErrorResult(
                failure_mode=FailureMode.JSON_PARSE_FAILURE,
                recovery_action=RecoveryAction.RETRY_WITH_V2_PROMPT,
                user_message="",  # Don't show anything for first retry — transparent to user
                technical_detail=f"T1 produced invalid JSON on attempt 1. Retrying with two-shot prompt.",
                retry_count=attempt,
                max_retries=1,
                context_for_retry=(
                    "IMPORTANT: Your previous response was not valid JSON. "
                    "You MUST respond with ONLY a JSON object starting with { and ending with }. "
                    "No explanation. No markdown. Just the JSON.\n"
                    f"Your previous response was: {raw_response[:200]!r}"
                ),
            )
        else:
            return ErrorResult(
                failure_mode=FailureMode.JSON_PARSE_FAILURE,
                recovery_action=RecoveryAction.FAIL_TASK,
                user_message=(
                    "I was unable to process this request. The AI model failed to produce a "
                    "valid response format after 2 attempts. Please try rephrasing your request."
                ),
                technical_detail=f"T1 produced invalid JSON on both attempts. Task failed.",
                retry_count=attempt,
                max_retries=1,
                tag="PARSE_FAILED",
            )

    def tool_not_found(self, tool_name: str, available_tools: list[str], attempt: int = 0) -> ErrorResult:
        """T1 named a tool that does not exist in the registry."""
        available_str = ", ".join(sorted(available_tools)[:10])
        logger.warning(
            f"ErrorHandler: tool not found | tool={tool_name!r} | attempt={attempt} | "
            f"available={available_str}"
        )

        if attempt == 0:
            return ErrorResult(
                failure_mode=FailureMode.TOOL_NOT_FOUND,
                recovery_action=RecoveryAction.RETRY_WITH_ERROR_CONTEXT,
                user_message="",  # Transparent first retry
                technical_detail=f"T1 named unknown tool '{tool_name}'. Injecting correction.",
                retry_count=attempt,
                max_retries=1,
                context_for_retry=(
                    f"ERROR: The tool '{tool_name}' does not exist. "
                    f"You must use ONLY tools from this exact list: {available_str}. "
                    f"Pick the most appropriate tool from that list and try again."
                ),
            )
        else:
            return ErrorResult(
                failure_mode=FailureMode.TOOL_NOT_FOUND,
                recovery_action=RecoveryAction.FAIL_TASK,
                user_message=(
                    f"I could not complete this task. The AI tried to use a "
                    f"non-existent tool '{tool_name}'. "
                    f"Available tools: {available_str[:100]}"
                ),
                technical_detail=f"T1 named unknown tool '{tool_name}' on both attempts.",
                retry_count=attempt,
                max_retries=1,
            )

    def tool_execution_failure(
        self, tool_name: str, exit_code: int, stderr: str, retry_count: int = 0
    ) -> ErrorResult:
        """A tool executed but returned a non-zero exit code. Inject the error and retry up to 3 times."""
        logger.warning(
            f"ErrorHandler: tool execution failure | tool={tool_name} | "
            f"exit_code={exit_code} | retry_count={retry_count} | "
            f"stderr={stderr[:120]!r}"
        )

        if retry_count < 3:
            return ErrorResult(
                failure_mode=FailureMode.TOOL_EXECUTION_FAILURE,
                recovery_action=RecoveryAction.RETRY_WITH_ERROR_CONTEXT,
                user_message="",  # Transparent — retrying automatically
                technical_detail=(
                    f"Tool '{tool_name}' failed with exit_code={exit_code}. "
                    f"Retry {retry_count + 1}/3. Error: {stderr[:200]}"
                ),
                retry_count=retry_count,
                max_retries=3,
                context_for_retry=(
                    f"The previous tool call FAILED.\n"
                    f"Tool: {tool_name}\n"
                    f"Exit code: {exit_code}\n"
                    f"Error output:\n{stderr[:400]}\n\n"
                    f"Analyse this error carefully. Fix the issue and try again with corrected parameters. "
                    f"If the command had a syntax error, correct it. "
                    f"If a file was missing, create it first. "
                    f"Do NOT repeat the same command that just failed."
                ),
            )
        else:
            return ErrorResult(
                failure_mode=FailureMode.TOOL_EXECUTION_FAILURE,
                recovery_action=RecoveryAction.FAIL_TASK,
                user_message=(
                    f"The action could not be completed after 3 attempts.\n"
                    f"Tool: {tool_name}\n"
                    f"Final error: {stderr[:300]}"
                ),
                technical_detail=f"Tool '{tool_name}' failed 3 times. exit_code={exit_code}",
                retry_count=retry_count,
                max_retries=3,
                tag="FAILED",
            )

    def ollama_timeout(self, model: str, timeout_seconds: int, stage: str) -> ErrorResult:
        """Ollama generation exceeded the timeout limit. Tag result and return immediately."""
        logger.error(
            f"ErrorHandler: Ollama timeout | model={model} | "
            f"timeout={timeout_seconds}s | stage={stage}"
        )
        return ErrorResult(
            failure_mode=FailureMode.OLLAMA_TIMEOUT,
            recovery_action=RecoveryAction.RETURN_WITH_TAG,
            user_message=(
                f"The AI model ({model}) took too long to respond "
                f"(>{timeout_seconds}s). This task has been paused. "
                f"You can try again with a simpler request."
            ),
            technical_detail=f"Ollama timeout at stage={stage} after {timeout_seconds}s",
            tag="TIMEOUT",
            retry_count=0,
            max_retries=0,  # No retries for timeout — avoid hanging again immediately
        )

    def tier3_api_failure(self, error_type: str, error_detail: str, tier1_output: str) -> ErrorResult:
        """Claude API call failed. Return T1's original result with [UNVERIFIED] tag."""
        logger.error(
            f"ErrorHandler: Tier 3 API failure | "
            f"error_type={error_type} | detail={error_detail[:100]}"
        )
        return ErrorResult(
            failure_mode=FailureMode.TIER3_API_FAILURE,
            recovery_action=RecoveryAction.RETURN_WITH_TAG,
            user_message=tier1_output,  # Return T1 result directly
            technical_detail=f"Tier 3 API failed: {error_type}: {error_detail}",
            tag="UNVERIFIED",
            retry_count=0,
            max_retries=0,  # Never retry API failures — could be rate limit or billing issue
        )

    def memory_parse_error(self, error_detail: str, project: str) -> ErrorResult:
        """MEMORY.md could not be read or parsed. Fall back to empty context and continue."""
        logger.warning(
            f"ErrorHandler: memory parse error | project={project} | "
            f"detail={error_detail[:100]} | using empty context fallback"
        )
        return ErrorResult(
            failure_mode=FailureMode.MEMORY_PARSE_ERROR,
            recovery_action=RecoveryAction.USE_EMPTY_FALLBACK,
            user_message="",  # Completely transparent — user does not need to know
            technical_detail=(
                f"MEMORY.md for project '{project}' could not be parsed: {error_detail}. "
                f"Using empty memory context for this session."
            ),
            tag="",
            retry_count=0,
            max_retries=0,
        )

    def unknown_error(self, exception: Exception, stage: str) -> ErrorResult:
        """Catch-all for unexpected exceptions. Always returns a safe result."""
        import traceback
        tb = traceback.format_exc()
        logger.error(
            f"ErrorHandler: unexpected error at stage={stage} | "
            f"type={type(exception).__name__} | "
            f"detail={str(exception)[:200]}"
        )
        logger.debug(f"ErrorHandler: full traceback:\n{tb}")
        return ErrorResult(
            failure_mode=FailureMode.UNKNOWN,
            recovery_action=RecoveryAction.FAIL_TASK,
            user_message=(
                f"An unexpected error occurred at pipeline stage {stage}. "
                f"Error type: {type(exception).__name__}. "
                f"Please try again. If the problem persists, check the logs."
            ),
            technical_detail=f"{type(exception).__name__}: {str(exception)[:300]}\n{tb[:500]}",
            tag="ERROR",
            retry_count=0,
            max_retries=0,
        )
