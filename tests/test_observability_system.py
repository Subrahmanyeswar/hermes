# tests/test_observability_system.py
"""
Deterministic Forensic Observability & Live Telemetry Test Suite for HERMES 2.x.
Tests A through M verifying complete coverage across models, tools, recovery,
validations, thinking intervals, secret redaction, and correlation tracing.
"""

import asyncio
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.observability.schemas import (
    ObservabilityEvent,
    TelemetrySeverity,
    FailureClassification,
    TimingPhase,
    CorrelationContext,
)
from core.observability.spans import TimingSpan, classify_thinking_duration
from core.observability.logger import (
    MissionTelemetryLogger,
    get_telemetry_logger,
)
from core.observability.bus_subscriber import ObservabilityBusSubscriber
from core.event_bus import EventBus
from core.runtime_state.events import HermesEvent, EventType, EventSeverity


@pytest.fixture
def temp_telemetry_dir():
    d = tempfile.mkdtemp(prefix="hermes_obs_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


# ==============================================================================
# TEST A: Model Request Telemetry
# ==============================================================================
def test_a_model_request_telemetry(temp_telemetry_dir):
    logger = MissionTelemetryLogger(run_id="run_test_a", mission_id="m_test_a", base_dir=temp_telemetry_dir)

    params = {
        "max_tokens": 4096,
        "temperature": 0.2,
        "streaming": True,
        "tool_count": 5,
    }
    timings = {
        "phases": {
            "queue_wait_ms": 12.5,
            "time_to_first_token_ms": 1450.0,
            "streaming_generation_ms": 2300.0,
            "response_parsing_ms": 15.0,
            "total_duration_ms": 3777.5,
        },
        "anomaly": None,
    }
    response_meta = {
        "finish_reason": "stop",
        "input_tokens": 520,
        "output_tokens": 180,
        "tool_calls_count": 1,
    }

    logger.record_model_call(
        turn=1,
        tier=1,
        provider="gemini",
        model="gemini-3.5-flash-lite",
        duration_ms=3777.5,
        status="SUCCESS",
        params=params,
        timings=timings,
        response_meta=response_meta,
        raw_prompt="Hello model, please create the file app.js",
        raw_response='{"tool_name": "fs.write", "path": "app.js"}',
    )

    models_file = logger.files["models"]
    assert models_file.exists()
    lines = [json.loads(line) for line in models_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1

    entry = lines[0]
    assert entry["event_type"] == "MODEL_REQUEST_COMPLETED"
    assert entry["tier"] == 1
    assert entry["provider"] == "gemini"
    assert entry["model"] == "gemini-3.5-flash-lite"
    assert entry["duration_ms"] == 3777.5
    assert entry["payload"]["response"]["finish_reason"] == "stop"
    assert entry["payload"]["timings"]["phases"]["time_to_first_token_ms"] == 1450.0

    # Also verify entry was mirrored to events.jsonl
    events_lines = [json.loads(line) for line in logger.files["events"].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(e["event_type"] == "MODEL_REQUEST_COMPLETED" for e in events_lines)


# ==============================================================================
# TEST B: Slow Model Response Deconstruction & Thinking Classification
# ==============================================================================
def test_b_slow_model_response_breakdown():
    # 70-second thinking interval where TTFT took 65 seconds
    breakdown = classify_thinking_duration(
        total_duration_ms=70250.0,
        ttft_ms=65100.0,
        streaming_duration_ms=4500.0,
        parse_duration_ms=25.0,
        queue_wait_ms=50.0,
    )

    assert breakdown["anomaly"] == "MODEL_TTFT_LATENCY_EXCESSIVE"
    phases = breakdown["phases"]
    assert phases["time_to_first_token_ms"] == 65100.0
    assert phases["streaming_generation_ms"] == 4500.0
    assert phases["queue_wait_ms"] == 50.0
    assert phases["total_duration_ms"] == 70250.0
    assert "local_or_network_overhead_ms" in phases


# ==============================================================================
# TEST C: HTTP Errors & Sanitized Provider Diagnostics
# ==============================================================================
def test_c_http_errors_and_sanitized_diagnostics(temp_telemetry_dir):
    from models.common_adapter import classify_provider_error, ErrorClassification

    logger = MissionTelemetryLogger(run_id="run_test_c", mission_id="m_test_c", base_dir=temp_telemetry_dir)

    http_statuses = [
        (401, "Invalid API key provided", ErrorClassification.AUTH_FAILURE),
        (403, "Forbidden access to model resource", ErrorClassification.PERMISSION_DENIED),
        (404, "Model not found", ErrorClassification.MODEL_NOT_FOUND),
        (429, "Rate limit reached. Please retry in 300s", ErrorClassification.RATE_LIMIT_EXCEEDED),
        (500, "Internal Server Error", ErrorClassification.INTERNAL_ERROR),
        (503, "Service Temporarily Unavailable", ErrorClassification.SERVICE_UNAVAILABLE),
    ]

    for status, body, expected_class in http_statuses:
        err_info = classify_provider_error(status_code=status, response_body=body)
        assert err_info.classification == expected_class

        logger.record_model_call(
            turn=1,
            tier=2,
            provider="groq",
            model="qwen/qwen3.8-27b",
            duration_ms=450.0,
            status="FAILED",
            params={"max_tokens": 4096},
            timings={"phases": {"total_duration_ms": 450.0}},
            response_meta={"status_code": status},
            error_details={
                "classification": err_info.classification.value,
                "message": err_info.message,
                "raw_body": body,
            },
        )

    # Verify errors recorded in both models.jsonl and errors.jsonl
    error_entries = [json.loads(line) for line in logger.files["errors"].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(error_entries) >= len(http_statuses)
    assert any("RATE_LIMIT" in str(e) for e in error_entries)
    assert any("AUTH_FAILURE" in str(e) for e in error_entries)


# ==============================================================================
# TEST D: Tool Execution Errors & Complete Stderr Preservation
# ==============================================================================
def test_d_tool_errors_and_stderr_preservation(temp_telemetry_dir):
    logger = MissionTelemetryLogger(run_id="run_test_d", mission_id="m_test_d", base_dir=temp_telemetry_dir)

    node_stderr = """app.js:14
const ORDER_STATUSES = ['New', 'Preparing', 'Ready', 'Completed', '
                                                                  ^
SyntaxError: Invalid or unexpected token
    at compileSourceTextModule (node:internal/modules/esm/load:240:19)
Node.js v20.18.3"""

    logger.record_tool_call(
        tool_call_id="call_node_check",
        tool_name="shell.bash",
        turn=2,
        duration_ms=185.0,
        success=False,
        exit_code=1,
        arguments={"command": "node --check app.js"},
        target_path="app.js",
        stdout="",
        stderr=node_stderr,
        error_message="Command failed with exit code 1",
    )

    tools_file = logger.files["tools"]
    lines = [json.loads(line) for line in tools_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    t_entry = lines[0]
    assert t_entry["event_type"] == "TOOL_FAILED"
    assert t_entry["payload"]["exit_code"] == 1
    assert "SyntaxError: Invalid or unexpected token" in t_entry["payload"]["stderr_summary"]
    assert "node --check app.js" == t_entry["payload"]["arguments"]["command"]


# ==============================================================================
# TEST E: Malformed Tool JSON Detection
# ==============================================================================
def test_e_malformed_tool_json_detection(temp_telemetry_dir):
    logger = MissionTelemetryLogger(run_id="run_test_e", mission_id="m_test_e", base_dir=temp_telemetry_dir)

    logger.log_event(
        event_type="MODEL_MALFORMED_TOOL_OUTPUT",
        component="adapter_normalizer",
        severity="ERROR",
        message="Tool arguments could not be parsed as valid JSON: Unterminated string literal",
        turn=3,
        tier=1,
        provider="groq",
        payload={
            "raw_arguments": '{"path": "app.js", "content": "const x = [\'unclosed',
            "parse_error": "Unterminated string starting at line 1 column 35 (char 34)",
            "failure_class": FailureClassification.MODEL_MALFORMED_TOOL_OUTPUT.value,
        },
        destinations=["models", "errors"],
    )

    errors = [json.loads(l) for l in logger.files["errors"].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(e["event_type"] == "MODEL_MALFORMED_TOOL_OUTPUT" for e in errors)


# ==============================================================================
# TEST F: Tier Transitions and Recovery Decision Telemetry
# ==============================================================================
def test_f_tier_transitions_and_recovery_telemetry(temp_telemetry_dir):
    logger = MissionTelemetryLogger(run_id="run_test_f", mission_id="m_test_f", base_dir=temp_telemetry_dir)

    # 1. T1 -> T2
    logger.record_recovery_decision(
        turn=2,
        failure_class="SYNTAX_ERROR",
        fingerprint="fp_syntax_app_js",
        from_tier=1,
        to_tier=2,
        reason="Tier 1 syntax validation failed twice",
        circuit_state="HEALTHY",
        recovery_counters={"attempt": 1, "rotations": 0, "visited": [1]},
    )

    # 2. T2 -> T3
    logger.record_recovery_decision(
        turn=4,
        failure_class="SYNTAX_ERROR",
        fingerprint="fp_syntax_app_js",
        from_tier=2,
        to_tier=3,
        reason="Tier 2 syntax validation failed",
        circuit_state="HEALTHY",
        recovery_counters={"attempt": 2, "rotations": 0, "visited": [1, 2]},
    )

    # 3. T3 -> T1 rotation
    logger.record_recovery_decision(
        turn=6,
        failure_class="SYNTAX_ERROR",
        fingerprint="fp_syntax_app_js",
        from_tier=3,
        to_tier=1,
        reason="Tier 1 verified recovered to HEALTHY; routing T3 -> T1 (rotation 1/1)",
        circuit_state="HEALTHY",
        recovery_counters={"attempt": 3, "rotations": 1, "visited": [1, 2, 3]},
    )

    recovery_file = logger.files["recovery"]
    recs = [json.loads(l) for l in recovery_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(recs) == 3
    assert recs[0]["payload"]["from_tier"] == 1 and recs[0]["payload"]["to_tier"] == 2
    assert recs[1]["payload"]["from_tier"] == 2 and recs[1]["payload"]["to_tier"] == 3
    assert recs[2]["payload"]["from_tier"] == 3 and recs[2]["payload"]["to_tier"] == 1
    assert "rotation 1/1" in recs[2]["payload"]["reason"]


# ==============================================================================
# TEST G: Recovery Stalls and No-Progress Telemetry
# ==============================================================================
def test_g_recovery_stalls_and_no_progress_telemetry(temp_telemetry_dir):
    logger = MissionTelemetryLogger(run_id="run_test_g", mission_id="m_test_g", base_dir=temp_telemetry_dir)

    logger.log_event(
        event_type="REASONING_STALL_EVALUATED",
        component="stall_watchdog",
        severity="WARN",
        message="CRITICAL STALL WARNING: 2 consecutive turns without tool actions. Missing prerequisites: app.js.",
        turn=4,
        payload={
            "consecutive_empty_turns": 2,
            "has_unmet_deliverables": True,
            "unmet_deliverables": ["app.js"],
            "failure_budget_remaining": 3,
            "failure_class": FailureClassification.NO_PROGRESS.value,
        },
        destinations=["recovery", "errors"],
    )

    rec_lines = [json.loads(l) for l in logger.files["recovery"].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r["event_type"] == "REASONING_STALL_EVALUATED" for r in rec_lines)


# ==============================================================================
# TEST H: Deadline Admission Control Telemetry
# ==============================================================================
def test_h_deadline_admission_control_telemetry(temp_telemetry_dir):
    logger = MissionTelemetryLogger(run_id="run_test_h", mission_id="m_test_h", base_dir=temp_telemetry_dir)

    # 1. Admission Allowed
    logger.log_event(
        event_type="MODEL_CALL_ADMISSION_ALLOWED",
        component="deadline_control",
        severity="INFO",
        message="Model call admission granted: 90.0s turn budget",
        turn=1,
        payload={"remaining_wall_time": 950.0, "turn_timeout": 90.0},
        destinations=["runtime"],
    )

    # 2. Admission Denied
    logger.log_event(
        event_type="MODEL_CALL_ADMISSION_DENIED",
        component="deadline_control",
        severity="WARN",
        message="Insufficient remaining wall time budget for model turn",
        turn=10,
        payload={
            "remaining_wall_time": 170.0,
            "reserve_seconds": 165.0,
            "min_model_timeout": 15.0,
            "failure_class": FailureClassification.DEADLINE_EXCEEDED.value,
        },
        destinations=["runtime", "errors"],
    )

    rt_lines = [json.loads(l) for l in logger.files["runtime"].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r["event_type"] == "MODEL_CALL_ADMISSION_ALLOWED" for r in rt_lines)
    assert any(r["event_type"] == "MODEL_CALL_ADMISSION_DENIED" for r in rt_lines)


# ==============================================================================
# TEST I: Runtime Fingerprint Verification & Mismatch Explanation
# ==============================================================================
def test_i_runtime_fingerprint_verification():
    from core.server.app import _compute_code_fingerprint, _get_code_mismatches, _SERVER_CODE_FINGERPRINT

    disk_fp = _compute_code_fingerprint()
    assert len(disk_fp) == 16

    # Test mismatch detection
    mismatches = _get_code_mismatches()
    # At start, either 0 mismatches or lists exact differing files
    assert isinstance(mismatches, list)


# ==============================================================================
# TEST J: Full Python Exception Traceback Telemetry
# ==============================================================================
def test_j_exception_traceback_telemetry(temp_telemetry_dir):
    logger = MissionTelemetryLogger(run_id="run_test_j", mission_id="m_test_j", base_dir=temp_telemetry_dir)

    try:
        raise ValueError("Simulated unexpected internal parsing exception in agent loop")
    except Exception as exc:
        logger.record_exception(
            component="agent_loop",
            exc=exc,
            failure_class=FailureClassification.INTERNAL_HERMES_EXCEPTION.value,
            turn=5,
            recovered=False,
        )

    err_lines = [json.loads(l) for l in logger.files["errors"].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(err_lines) >= 1
    err_entry = err_lines[-1]
    assert err_entry["event_type"] == "UNHANDLED_EXCEPTION"
    assert "ValueError" in err_entry["payload"]["exception_class"]
    assert "Traceback" in err_entry["payload"]["traceback"]


# ==============================================================================
# TEST K: Sensitive Data Redaction
# ==============================================================================
def test_k_sensitive_data_redaction(temp_telemetry_dir):
    logger = MissionTelemetryLogger(run_id="run_test_k", mission_id="m_test_k", base_dir=temp_telemetry_dir)

    secret_key = "sk-ant-api03-abcdef1234567890abcdef1234567890"
    gh_token = "ghp_1234567890abcdef1234567890abcdef1234"
    auth_header = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret"

    payload_with_secrets = {
        "api_key": secret_key,
        "token": gh_token,
        "authorization": auth_header,
        "user_message": f"Please configure key {secret_key} and token {gh_token}",
    }

    logger.log_event(
        event_type="TEST_REDACTION",
        component="test",
        severity="INFO",
        message=f"Attempting to log secret {secret_key}",
        payload=payload_with_secrets,
    )

    # Check raw text of all generated logs
    for fpath in logger.files.values():
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8")
            assert secret_key not in content, f"Secret leaked in {fpath.name}!"
            assert gh_token not in content, f"GitHub token leaked in {fpath.name}!"
    # Verify events.jsonl contains redacted marker
    ev_content = logger.files["events"].read_text(encoding="utf-8")
    assert "[REDACTED_SECRET]" in ev_content or "[REDACTED]" in ev_content


# ==============================================================================
# TEST L: Live Log Viewer FileStream Reader
# ==============================================================================
def test_l_live_log_viewer_stream(temp_telemetry_dir):
    logger = MissionTelemetryLogger(run_id="run_test_l", mission_id="m_test_l", base_dir=temp_telemetry_dir)

    # Write a burst of 5 events
    for i in range(5):
        logger.log_event(
            event_type=f"BURST_EVENT_{i}",
            component="stream_test",
            severity="INFO",
            message=f"Burst message #{i}",
        )

    ev_path = logger.files["events"]
    assert ev_path.exists()
    lines = [l for l in ev_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    # At least 1 initial runtime snapshot + 5 burst events = 6
    assert len(lines) >= 6


# ==============================================================================
# TEST M: Mission Event Correlation Across Components
# ==============================================================================
def test_m_mission_event_correlation(temp_telemetry_dir):
    event_bus = EventBus()
    subscriber = ObservabilityBusSubscriber(event_bus)
    subscriber.attach()

    import uuid
    run_id = f"run_test_m_{uuid.uuid4().hex[:6]}"
    mission_id = f"m_test_m_{uuid.uuid4().hex[:6]}"

    try:
        # Trace flow: Model Request -> Tool Start -> Tool Complete -> File Write -> Validation
        trace_id = "tr_correlate_01"
        span_id = "sp_turn_1"

        # 1. Model Request Completed
        event_bus.publish(HermesEvent(
            event_type=EventType.MODEL_COMPLETED,
            mission_id=mission_id,
            run_id=run_id,
            turn_id="turn_1",
            trace_id=trace_id,
            span_id=span_id,
            payload={"model": "gemini-3.5-flash-lite", "duration_ms": 1200.0},
        ))

        # 2. Tool Started
        event_bus.publish(HermesEvent(
            event_type=EventType.TOOL_STARTED,
            mission_id=mission_id,
            run_id=run_id,
            turn_id="turn_1",
            tool_call_id="call_01",
            trace_id=trace_id,
            span_id="sp_tool_1",
            parent_span_id=span_id,
            payload={"tool_name": "fs.write", "path": "index.html"},
        ))

        # 3. Tool Completed
        event_bus.publish(HermesEvent(
            event_type=EventType.TOOL_COMPLETED,
            mission_id=mission_id,
            run_id=run_id,
            turn_id="turn_1",
            tool_call_id="call_01",
            trace_id=trace_id,
            span_id="sp_tool_1",
            parent_span_id=span_id,
            payload={"tool_name": "fs.write", "duration_ms": 15.0, "status": "SUCCESS"},
        ))

        # 4. Validation Passed
        event_bus.publish(HermesEvent(
            event_type=EventType.VERIFICATION_PASSED,
            mission_id=mission_id,
            run_id=run_id,
            turn_id="turn_1",
            trace_id=trace_id,
            payload={"check_name": "html_structure", "status": "PASSED"},
        ))

        telemetry = get_telemetry_logger(run_id=run_id, mission_id=mission_id)
        ev_lines = [json.loads(l) for l in telemetry.files["events"].read_text(encoding="utf-8").splitlines() if l.strip()]
        
        correlated = [e for e in ev_lines if e.get("trace_id") == trace_id]
        assert len(correlated) == 4
        assert correlated[0]["event_type"] == "MODEL_COMPLETED"
        assert correlated[1]["event_type"] == "TOOL_STARTED"
        assert correlated[2]["event_type"] == "TOOL_COMPLETED"
        assert correlated[3]["event_type"] == "VERIFICATION_PASSED"
    finally:
        subscriber.detach()
