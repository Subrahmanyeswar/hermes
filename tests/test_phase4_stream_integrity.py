"""
Phase 4 Acceptance Test Suite: Stream Integrity & Response Completeness (Scenarios I, J / Gate E).

Verifies:
- Scenario I: Truncated structured response (partial output discarded, no tool execution, clean accumulator).
- Scenario J: Complete but malformed structured response fails validation.
- End-of-stream validation: [DONE] / finish_reason required before final response acceptance.
"""

import pytest

from core.transport.stream_validator import (
    SseStreamAccumulator,
    OllamaStreamAccumulator,
)
from core.transport.types import ErrorCategory


def test_scenario_i_truncated_stream_discarded_and_rejected():
    """Verify stream ending before [DONE] is rejected, marked STREAM_INCOMPLETE, and partial text discarded."""
    acc = SseStreamAccumulator(
        model="z-ai/glm-5.3-flash",
        provider="nvidia_nim",
    )

    # Valid SSE chunk carrying partial content
    chunk = 'data: {"choices": [{"delta": {"content": "Partial response text..."}}]}'
    is_done, err = acc.process_chunk(chunk, now=100.0)
    assert is_done is False
    assert err is None
    assert acc.content_chunks == ["Partial response text..."]

    # Connection closes abruptly without [DONE]
    resp, final_err = acc.validate_and_finalize(elapsed_ms=1200.0)
    assert resp.success is False
    assert final_err is not None
    assert final_err.category == ErrorCategory.STREAM_INCOMPLETE
    assert "terminal completion marker" in final_err.message

    # Next attempt begins with clean accumulator
    new_acc = SseStreamAccumulator(
        model="z-ai/glm-5.3-flash",
        provider="nvidia_nim",
    )
    assert len(new_acc.content_chunks) == 0
    assert len(new_acc.tool_calls_map) == 0


def test_scenario_j_complete_stream_with_malformed_json_arguments_rejected():
    """Verify complete response with malformed JSON tool arguments fails validation."""
    acc = SseStreamAccumulator(
        model="z-ai/glm-5.3-flash",
        provider="nvidia_nim",
    )

    # Tool call with invalid JSON arguments
    chunk1 = 'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "write_file", "arguments": "malformed_json_arguments"}}]}}]}'
    is_done, err = acc.process_chunk(chunk1, now=100.0)
    assert is_done is False
    assert err is None

    # Stream sends terminal [DONE]
    is_done, _ = acc.process_chunk("data: [DONE]", now=101.0)
    assert is_done is True

    # Finalize must reject due to invalid tool arguments JSON
    resp, final_err = acc.validate_and_finalize(elapsed_ms=1000.0)
    assert resp.success is False
    assert final_err is not None
    assert final_err.category == ErrorCategory.STREAM_INCOMPLETE
    assert "arguments" in final_err.message.lower() or "json" in final_err.message.lower()


def test_scenario_i_ollama_ndjson_stream_incomplete_and_complete():
    """Verify Ollama NDJSON accumulator enforces 'done: true' and validates completeness."""
    acc_incomplete = OllamaStreamAccumulator(model="gpt-oss:120b-cloud", provider="ollama")
    line1 = '{"response": "First partial line", "done": false}'
    acc_incomplete.process_line(line1)

    # Incomplete stream finalize
    resp, err = acc_incomplete.validate_and_finalize(elapsed_ms=500.0)
    assert resp.success is False
    assert err is not None
    assert err.category == ErrorCategory.STREAM_INCOMPLETE

    # Complete stream finalize
    acc_complete = OllamaStreamAccumulator(model="gpt-oss:120b-cloud", provider="ollama")
    acc_complete.process_line(line1)
    line2 = '{"response": " Part 2", "done": true}'
    acc_complete.process_line(line2)

    resp_ok, err_none = acc_complete.validate_and_finalize(elapsed_ms=800.0)
    assert resp_ok.success is True
    assert err_none is None
    assert resp_ok.text == "First partial line Part 2"
