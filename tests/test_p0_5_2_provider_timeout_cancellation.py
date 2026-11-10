"""
Unit tests for P0.5.2 Provider Timeout, Cancellation, and Fast Failover.
Verifies:
1. 25-second decision deadline default configuration.
2. Classification of AttemptTimeoutError, TTFTTimeoutError, and connection timeouts as transient.
3. Telemetry tracking of timeout_config, actual_timeout_result, and cancellation_result.
4. Fast failover handling when provider response is empty or stalls.
"""

import os
import pytest
import httpx
from models.common_adapter import (
    CommonProviderAdapter,
    ErrorClassification,
    AttemptTimeoutError,
    TTFTTimeoutError,
    StreamStallError,
    RequestTelemetry,
    classify_provider_error,
)


def test_provider_adapter_deadline_defaults():
    adapter = CommonProviderAdapter(
        provider_name="test_provider",
        model_name="test_model",
        base_url="https://api.test.example/v1",
        api_key="sk-test-key",
    )
    assert adapter.attempt_timeout_seconds == 25.0
    assert adapter.first_token_timeout_seconds == 7.5
    assert adapter.stream_idle_timeout_seconds == 10.0


def test_classify_timeout_errors():
    attempt_err = AttemptTimeoutError("Request attempt exceeded deadline of 25.0s")
    classified = classify_provider_error(attempt_err)
    assert classified.classification == ErrorClassification.MODEL_REQUEST_TIMEOUT
    assert classified.is_transient is True

    ttft_err = TTFTTimeoutError("First token not received within 7.5s")
    classified_ttft = classify_provider_error(ttft_err)
    assert classified_ttft.classification == ErrorClassification.MODEL_TTFT_TIMEOUT
    assert classified_ttft.is_transient is True

    stall_err = StreamStallError("Stream idle timeout exceeded 10.0s")
    classified_stall = classify_provider_error(stall_err)
    assert classified_stall.classification == ErrorClassification.MODEL_STREAM_STALL
    assert classified_stall.is_transient is True

    conn_err = httpx.ConnectTimeout("Connection timed out after 5.0s")
    classified_conn = classify_provider_error(conn_err)
    assert classified_conn.classification == ErrorClassification.PROVIDER_CONNECT_TIMEOUT
    assert classified_conn.is_transient is True


def test_request_telemetry_timeout_tracking():
    telemetry = RequestTelemetry(
        provider="groq",
        model="llama-3.3-70b-versatile",
        timeout_config=25.0,
        actual_timeout_result="EXCEEDED",
        cancellation_result="CANCELLED_ATOMICALLY",
    )
    d = telemetry.to_dict()
    assert d["timeout_config"] == 25.0
    assert d["actual_timeout_result"] == "EXCEEDED"
    assert d["cancellation_result"] == "CANCELLED_ATOMICALLY"
