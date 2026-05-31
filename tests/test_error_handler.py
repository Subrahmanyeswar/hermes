import pytest
from core.error_handler import (
    ErrorHandler, ErrorResult, FailureMode, RecoveryAction
)


@pytest.fixture
def handler():
    return ErrorHandler()


# ── JSON parse failure ────────────────────────────────────────────────


def test_json_parse_failure_first_attempt_allows_retry(handler):
    result = handler.json_parse_failure("not json at all", attempt=0)
    assert result.failure_mode == FailureMode.JSON_PARSE_FAILURE
    assert result.recovery_action == RecoveryAction.RETRY_WITH_V2_PROMPT
    assert result.can_retry is True
    assert result.context_for_retry != ""
    assert result.user_message == ""  # Transparent first retry


def test_json_parse_failure_second_attempt_is_final(handler):
    result = handler.json_parse_failure("still not json", attempt=1)
    assert result.recovery_action == RecoveryAction.FAIL_TASK
    assert result.can_retry is False
    assert result.is_final is True
    assert result.user_message != ""  # Now shows user a message


def test_json_parse_failure_context_contains_bad_response(handler):
    bad_response = "I would be happy to help"
    result = handler.json_parse_failure(bad_response, attempt=0)
    assert bad_response[:50] in result.context_for_retry or "not valid JSON" in result.context_for_retry


# ── Tool not found ────────────────────────────────────────────────────


def test_tool_not_found_first_attempt_allows_retry(handler):
    result = handler.tool_not_found("nonexistent_tool", ["write_file", "read_file"], attempt=0)
    assert result.failure_mode == FailureMode.TOOL_NOT_FOUND
    assert result.can_retry is True
    assert "nonexistent_tool" in result.context_for_retry
    assert "write_file" in result.context_for_retry


def test_tool_not_found_second_attempt_is_final(handler):
    result = handler.tool_not_found("bad_tool", ["write_file"], attempt=1)
    assert result.can_retry is False
    assert "bad_tool" in result.user_message


def test_tool_not_found_user_message_empty_on_first_attempt(handler):
    result = handler.tool_not_found("fake_tool", ["write_file"], attempt=0)
    assert result.user_message == ""


# ── Tool execution failure ────────────────────────────────────────────


def test_tool_execution_failure_retry_0_can_retry(handler):
    result = handler.tool_execution_failure("bash_exec", 1, "Permission denied", retry_count=0)
    assert result.can_retry is True
    assert result.recovery_action == RecoveryAction.RETRY_WITH_ERROR_CONTEXT
    assert "Permission denied" in result.context_for_retry
    assert result.retry_count == 0


def test_tool_execution_failure_retry_1_can_retry(handler):
    result = handler.tool_execution_failure("bash_exec", 1, "Still failing", retry_count=1)
    assert result.can_retry is True


def test_tool_execution_failure_retry_2_can_retry(handler):
    result = handler.tool_execution_failure("bash_exec", 1, "Still failing", retry_count=2)
    assert result.can_retry is True


def test_tool_execution_failure_retry_3_is_final(handler):
    result = handler.tool_execution_failure("bash_exec", 1, "Max retries", retry_count=3)
    assert result.can_retry is False
    assert result.is_final is True
    assert result.tag == "FAILED"
    assert "3 attempts" in result.user_message


def test_tool_execution_failure_context_has_stderr(handler):
    stderr = "FileNotFoundError: no such file"
    result = handler.tool_execution_failure("run_python", 1, stderr, retry_count=0)
    assert stderr in result.context_for_retry


# ── Ollama timeout ────────────────────────────────────────────────────


def test_ollama_timeout_is_final(handler):
    result = handler.ollama_timeout("qwen2.5-coder:7b", 120, "stage_4")
    assert result.failure_mode == FailureMode.OLLAMA_TIMEOUT
    assert result.is_final is True
    assert result.tag == "TIMEOUT"
    assert result.max_retries == 0


def test_ollama_timeout_message_mentions_timeout(handler):
    result = handler.ollama_timeout("qwen2.5-coder:7b", 120, "stage_7")
    assert "120" in result.user_message or "long" in result.user_message.lower()


def test_ollama_timeout_tagged_output(handler):
    result = handler.ollama_timeout("model", 120, "stage_4")
    tagged = result.tagged_output("partial result here")
    assert tagged.startswith("[TIMEOUT]")


# ── Tier 3 API failure ────────────────────────────────────────────────


def test_tier3_failure_returns_t1_output(handler):
    t1_output = "I will write the Flask app now"
    result = handler.tier3_api_failure("APIError", "rate limit exceeded", t1_output)
    assert result.failure_mode == FailureMode.TIER3_API_FAILURE
    assert result.tag == "UNVERIFIED"
    assert result.user_message == t1_output  # T1 output preserved


def test_tier3_failure_is_final(handler):
    result = handler.tier3_api_failure("NetworkError", "timeout", "some output")
    assert result.is_final is True
    assert result.max_retries == 0


def test_tier3_failure_tagged_output(handler):
    result = handler.tier3_api_failure("APIError", "error", "T1 result")
    tagged = result.tagged_output("T1 result")
    assert "[UNVERIFIED]" in tagged


# ── Memory parse error ────────────────────────────────────────────────


def test_memory_parse_error_is_transparent(handler):
    result = handler.memory_parse_error("Invalid YAML on line 3", "myproject")
    assert result.failure_mode == FailureMode.MEMORY_PARSE_ERROR
    assert result.user_message == ""  # Completely transparent
    assert result.tag == ""
    assert result.recovery_action == RecoveryAction.USE_EMPTY_FALLBACK


def test_memory_parse_error_is_final(handler):
    result = handler.memory_parse_error("parse error", "default")
    assert result.is_final is True


# ── Unknown error ─────────────────────────────────────────────────────


def test_unknown_error_never_raises(handler):
    try:
        result = handler.unknown_error(ValueError("something went wrong"), "stage_6")
        assert result.failure_mode == FailureMode.UNKNOWN
        assert result.is_final is True
        assert result.tag == "ERROR"
    except Exception as e:
        pytest.fail(f"unknown_error raised an exception: {e}")


def test_unknown_error_message_contains_exception_type(handler):
    result = handler.unknown_error(RuntimeError("disk full"), "stage_10")
    assert "RuntimeError" in result.user_message or "unexpected" in result.user_message.lower()


# ── ErrorResult invariants ────────────────────────────────────────────


def test_error_result_can_retry_false_when_max_reached():
    result = ErrorResult(
        failure_mode=FailureMode.TOOL_EXECUTION_FAILURE,
        recovery_action=RecoveryAction.RETRY_WITH_ERROR_CONTEXT,
        user_message="",
        technical_detail="",
        retry_count=3,
        max_retries=3,
    )
    assert result.can_retry is False


def test_error_result_can_retry_true_when_below_max():
    result = ErrorResult(
        failure_mode=FailureMode.TOOL_EXECUTION_FAILURE,
        recovery_action=RecoveryAction.RETRY_WITH_ERROR_CONTEXT,
        user_message="",
        technical_detail="",
        retry_count=2,
        max_retries=3,
    )
    assert result.can_retry is True


def test_error_result_is_final_for_return_with_tag():
    result = ErrorResult(
        failure_mode=FailureMode.OLLAMA_TIMEOUT,
        recovery_action=RecoveryAction.RETURN_WITH_TAG,
        user_message="timeout",
        technical_detail="",
        retry_count=0,
        max_retries=0,
    )
    assert result.is_final is True
