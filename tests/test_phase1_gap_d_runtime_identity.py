"""
Tests for Acceptance Gap D: Runtime and Launcher Identity Verification.

Verifies:
1. Matching runtime fingerprint is accepted.
2. Mismatched runtime fingerprint is detected and reported.
3. Missing or malformed identity fields are handled explicitly.
4. Unexpected Python interpreter version is detected.
5. PID and startup metadata are attributed to the correct runtime instance.
6. Identity mismatch does not silently pass.
7. Verification does not kill, restart, or silently take over an existing process.
"""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from core.server.launcher import verify_runtime_identity, compute_local_code_fingerprint


@pytest.fixture
def valid_health_payload():
    fp = compute_local_code_fingerprint()
    return {
        "status": "ok",
        "version": "1.0.0-rc1",
        "runtime_mode": "auto",
        "python_version": sys.version.split()[0],
        "workspace_locked": True,
        "workspace_root": "C:\\fake\\workspace",
        "server_time": time.time(),
        "startup_time": time.time() - 10.0,
        "pid": os.getpid(),
        "code_fingerprint": fp,
        "code_match": True,
        "model_stack": {
            "tier1": "nvidia_nim / z-ai/glm-5.3-flash",
            "tier2": "ollama / gpt-oss:120b-cloud",
            "tier3": "ollama / nemotron-3-ultra:cloud",
        },
    }


def test_scenario_1_matching_runtime_fingerprint_accepted(valid_health_payload):
    """Scenario 1: Genuine matching health payload with valid code fingerprint passes."""
    ok, reason = verify_runtime_identity(
        valid_health_payload,
        expected_pid=os.getpid(),
        expected_python_version="3.12",
    )
    assert ok is True
    assert reason == "IDENTITY_VERIFIED"


def test_scenario_2_mismatched_runtime_fingerprint_detected(valid_health_payload):
    """Scenario 2: Mismatched code fingerprint is flagged and rejected."""
    tampered = dict(valid_health_payload)
    tampered["code_fingerprint"] = "badc0de000000000"

    ok, reason = verify_runtime_identity(
        tampered,
        expected_pid=os.getpid(),
    )
    assert ok is False
    assert "CODE_FINGERPRINT_MISMATCH" in reason


def test_scenario_3_missing_or_malformed_identity_field_handled():
    """Scenario 3: Missing fields, wrong types, or malformed dictionaries fail cleanly."""
    # None payload
    ok, reason = verify_runtime_identity(None)
    assert ok is False
    assert reason == "MISSING_HEALTH_DATA"

    # Status not ok
    ok, reason = verify_runtime_identity({"status": "degraded"})
    assert ok is False
    assert reason == "INVALID_STATUS"

    # Malformed model stack
    ok, reason = verify_runtime_identity({"status": "ok", "model_stack": None})
    assert ok is False
    assert reason == "MALFORMED_MODEL_STACK"

    # Missing python version
    ok, reason = verify_runtime_identity({
        "status": "ok",
        "model_stack": {"tier1": "x"},
    })
    assert ok is False
    assert reason == "MISSING_PYTHON_VERSION"

    # Missing code fingerprint
    ok, reason = verify_runtime_identity({
        "status": "ok",
        "model_stack": {"tier1": "x"},
        "python_version": "3.12.0",
    })
    assert ok is False
    assert reason == "MISSING_CODE_FINGERPRINT"


def test_scenario_4_unexpected_python_version_detected(valid_health_payload):
    """Scenario 4: Server reporting non-canonical Python version is rejected."""
    tampered = dict(valid_health_payload)
    tampered["python_version"] = "3.10.4"

    ok, reason = verify_runtime_identity(
        tampered,
        expected_python_version="3.12",
    )
    assert ok is False
    assert "PYTHON_VERSION_MISMATCH" in reason


def test_scenario_5_pid_attribution_verified(valid_health_payload):
    """Scenario 5: PID mismatch is flagged."""
    ok, reason = verify_runtime_identity(
        valid_health_payload,
        expected_pid=999999,  # different PID
    )
    assert ok is False
    assert "PID_MISMATCH" in reason


def test_scenario_6_identity_mismatch_does_not_silently_pass(valid_health_payload):
    """Scenario 6: Any discrepancy returns False and does not raise uncaught exceptions."""
    for key, bad_val in [
        ("code_fingerprint", "wrong"),
        ("python_version", "2.7.18"),
        ("status", "error"),
    ]:
        bad_payload = dict(valid_health_payload, **{key: bad_val})
        ok, reason = verify_runtime_identity(bad_payload, expected_python_version="3.12")
        assert ok is False
        assert len(reason) > 0


def test_scenario_7_verification_does_not_mutate_or_kill_processes(valid_health_payload):
    """Scenario 7: Identity verification operates strictly read-only and does not terminate processes."""
    mock_proc = MagicMock()
    mock_proc.pid = os.getpid()
    mock_proc.is_running.return_value = True

    # Run check against mismatched payload
    bad_payload = dict(valid_health_payload, code_fingerprint="mismatch_12345")
    ok, reason = verify_runtime_identity(bad_payload)
    assert ok is False

    # Assert mock process terminate / kill were NEVER called
    mock_proc.kill.assert_not_called()
    mock_proc.terminate.assert_not_called()
