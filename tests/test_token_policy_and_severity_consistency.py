# tests/test_token_policy_and_severity_consistency.py
"""
HERMES Phase 4.1  Token-Policy and Acceptance-Severity Consistency Audit Suite.

Tests cover:
Task 1:
- Missing value resolves to default generation ceiling (8192)
- Small values (1, 350, 500, 1536, 4096) are respected exactly
- Exactly 8192 resolves to 8192
- Values above 8192 without override are clamped to 8192
- Values above 8192 with explicit override are honored
- Invalid values (<= 0, non-integers) raise ValueError
- Client generate payload respects the token policy

Task 2:
- Failed exploratory command followed by successful recovery -> warning, non-blocking
- Failed mandatory build -> failed, error, is_blocking=True
- Failed mandatory test -> failed, error, is_blocking=True
- Failed required file write -> failed, error, is_blocking=True
- Non-fatal missing-path probe -> warning, non-blocking
- Mandatory requirement remains unverified -> failed, error, is_blocking=True
- Backend and GUI Outcome panel severity agreement
"""

import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from models.nvidia_client import (
    NvidiaClient,
    resolve_effective_max_tokens,
    validate_token_ceiling_config,
    validate_timeout_config,
    NvidiaTimeoutError,
)
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionState,
    TaskState,
    MissionStatus,
    TaskStatus,
    AcceptanceCheck,
    AcceptanceCheckStatus,
    AcceptanceLedger,
)
from core.server.checks_service import extract_mission_checks, clear_checks_cache
from ui.state.selectors import select_verification_view_model


# ==============================================================================
# Task 1 & 2: Token Budget Strict Input Contract & Boundary Tests
# ==============================================================================


def test_resolve_max_tokens_missing_value():
    """1. None resolves to the documented default (8192)."""
    assert resolve_effective_max_tokens(max_tokens=None, num_predict=None) == 8192
    assert resolve_effective_max_tokens() == 8192


def test_resolve_max_tokens_small_values():
    """2. Valid small positive integers remain unchanged."""
    assert resolve_effective_max_tokens(max_tokens=1) == 1
    assert resolve_effective_max_tokens(max_tokens=350) == 350
    assert resolve_effective_max_tokens(max_tokens=500) == 500
    assert resolve_effective_max_tokens(num_predict=1536) == 1536
    assert resolve_effective_max_tokens(num_predict=2560) == 2560
    assert resolve_effective_max_tokens(num_predict=4096) == 4096


def test_resolve_max_tokens_exact_ceiling():
    """3. Exactly 8192 is handled correctly."""
    assert resolve_effective_max_tokens(max_tokens=8192) == 8192
    assert resolve_effective_max_tokens(num_predict=8192) == 8192


def test_resolve_max_tokens_above_ceiling_clamped():
    """4. Above-limit request is clamped when required."""
    assert resolve_effective_max_tokens(max_tokens=10000) == 8192
    assert resolve_effective_max_tokens(max_tokens=16384) == 8192
    assert resolve_effective_max_tokens(num_predict=32768) == 8192


def test_resolve_max_tokens_explicit_override_policy():
    """5. Explicit override follows documented policy and respects provider hard limit."""
    # Under provider hard limit (16384) -> honored
    assert resolve_effective_max_tokens(max_tokens=12000, allow_override=True) == 12000
    assert resolve_effective_max_tokens(max_tokens=16384, override_max_tokens=True) == 16384
    # Above provider hard limit -> clamped to provider hard limit (16384)
    assert resolve_effective_max_tokens(max_tokens=25000, allow_override=True) == 16384
    assert resolve_effective_max_tokens(num_predict=32768, allow_override=True) == 16384


def test_resolve_max_tokens_rejects_booleans():
    """6 & 7. Python bool values True and False are strictly rejected with TypeError."""
    with pytest.raises(TypeError, match="bool"):
        resolve_effective_max_tokens(max_tokens=True)

    with pytest.raises(TypeError, match="bool"):
        resolve_effective_max_tokens(max_tokens=False)

    with pytest.raises(TypeError, match="bool"):
        resolve_effective_max_tokens(num_predict=True)


def test_resolve_max_tokens_rejects_floats():
    """8 & 9. Floating-point values (fractional 1.5 and integral-valued 350.0) are strictly rejected."""
    with pytest.raises(TypeError, match="float"):
        resolve_effective_max_tokens(max_tokens=1.5)

    with pytest.raises(TypeError, match="float"):
        resolve_effective_max_tokens(max_tokens=350.0)

    with pytest.raises(TypeError, match="float"):
        resolve_effective_max_tokens(num_predict=8192.0)


def test_resolve_max_tokens_rejects_strings():
    """10 & 11. Strings (decimal '350' and non-numeric 'invalid') are strictly rejected."""
    with pytest.raises(TypeError, match="str"):
        resolve_effective_max_tokens(max_tokens="350")

    with pytest.raises(TypeError, match="str"):
        resolve_effective_max_tokens(max_tokens="invalid")

    with pytest.raises(TypeError, match="str"):
        resolve_effective_max_tokens(num_predict="1000")


def test_resolve_max_tokens_rejects_zero_and_negatives():
    """12. Zero and negative integers are rejected with ValueError."""
    with pytest.raises(ValueError, match="greater than 0"):
        resolve_effective_max_tokens(max_tokens=0)

    with pytest.raises(ValueError, match="greater than 0"):
        resolve_effective_max_tokens(max_tokens=-5)

    with pytest.raises(ValueError, match="greater than 0"):
        resolve_effective_max_tokens(num_predict=-100)


def test_invalid_environment_ceiling_diagnosed_clearly(monkeypatch):
    """13. Invalid environment ceiling produces clear actionable configuration error."""
    # Invalid non-integer string for ceiling
    monkeypatch.setenv("TIER1_MAX_TOKENS_CEILING", "not_an_int")
    with pytest.raises(ValueError, match="Configuration error: TIER1_MAX_TOKENS_CEILING"):
        resolve_effective_max_tokens(max_tokens=None)

    # Invalid non-positive integer for ceiling
    monkeypatch.setenv("TIER1_MAX_TOKENS_CEILING", "-500")
    with pytest.raises(ValueError, match="Configuration error: TIER1_MAX_TOKENS_CEILING"):
        resolve_effective_max_tokens(max_tokens=None)

    # Invalid non-integer string for provider hard limit
    monkeypatch.delenv("TIER1_MAX_TOKENS_CEILING", raising=False)
    monkeypatch.setenv("TIER1_PROVIDER_HARD_LIMIT", "invalid_limit")
    with pytest.raises(ValueError, match="Configuration error: TIER1_PROVIDER_HARD_LIMIT"):
        resolve_effective_max_tokens(max_tokens=None)

    # Invalid non-positive integer for provider hard limit
    monkeypatch.setenv("TIER1_PROVIDER_HARD_LIMIT", "-10")
    with pytest.raises(ValueError, match="Configuration error: TIER1_PROVIDER_HARD_LIMIT"):
        resolve_effective_max_tokens(max_tokens=None)

    # Invalid non-integer string for application override limit
    monkeypatch.delenv("TIER1_PROVIDER_HARD_LIMIT", raising=False)
    monkeypatch.setenv("TIER1_MAX_OVERRIDE_LIMIT", "bad_override_val")
    with pytest.raises(ValueError, match="Configuration error: TIER1_MAX_OVERRIDE_LIMIT"):
        resolve_effective_max_tokens(max_tokens=None)

    # Valid custom environment ceiling
    monkeypatch.delenv("TIER1_MAX_OVERRIDE_LIMIT", raising=False)
    monkeypatch.setenv("TIER1_MAX_TOKENS_CEILING", "4096")
    assert resolve_effective_max_tokens(max_tokens=None) == 4096
    assert resolve_effective_max_tokens(max_tokens=6000) == 4096  # Clamped to custom ceiling


def test_provider_hard_limit_invariants_under_inconsistent_configuration(monkeypatch):
    """Verify provider hard limit is strictly enforced across missing, ordinary, and override requests."""
    # Inconsistent configuration: policy ceiling configured above provider hard limit
    monkeypatch.setenv("TIER1_MAX_TOKENS_CEILING", "25000")
    monkeypatch.setenv("TIER1_PROVIDER_HARD_LIMIT", "16384")

    # A. Missing budget must not exceed provider hard limit
    assert resolve_effective_max_tokens(max_tokens=None) == 16384

    # B. Ordinary request above provider hard limit must be clamped
    assert resolve_effective_max_tokens(max_tokens=20000) == 16384

    # C. Explicit override above provider hard limit must be clamped
    assert resolve_effective_max_tokens(max_tokens=30000, allow_override=True) == 16384

    # D. Positive budgets below hard limit are preserved
    assert resolve_effective_max_tokens(max_tokens=500) == 500
    assert resolve_effective_max_tokens(max_tokens=8192) == 8192
    assert resolve_effective_max_tokens(max_tokens=12000) == 12000


def test_current_defaults_verification():
    """Verify current documented defaults: policy ceiling 8192, provider hard limit 16384."""
    # Missing value -> default policy ceiling 8192
    assert resolve_effective_max_tokens() == 8192
    # Ordinary request above ceiling -> clamped to 8192
    assert resolve_effective_max_tokens(max_tokens=10000) == 8192
    # Explicit override within provider hard limit -> honored (12000)
    assert resolve_effective_max_tokens(max_tokens=12000, allow_override=True) == 12000
    # Explicit override above provider hard limit -> clamped to 16384
    assert resolve_effective_max_tokens(max_tokens=20000, allow_override=True) == 16384


@pytest.mark.asyncio
async def test_existing_callers_remain_compatible():
    """14. Existing health-check, classification, and routing callers remain compatible."""
    client = NvidiaClient(api_key="test-api-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "chatcmpl-test",
        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    # Liveness ping caller (core/adaptive_routing.py: max_tokens=1)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        await client.generate(prompt="ping", max_tokens=1, stream=False)
        assert mock_post.call_args[1]["json"]["max_tokens"] == 1

    # Intent classification caller (core/intent_classifier.py: max_tokens=350)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        await client.generate(prompt="classify", max_tokens=350, stream=False)
        assert mock_post.call_args[1]["json"]["max_tokens"] == 350

    # Control handler caller (core/commands/handlers/control_handlers.py: max_tokens=500)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        await client.generate(prompt="control", max_tokens=500, stream=False)
        assert mock_post.call_args[1]["json"]["max_tokens"] == 500

    # L1 reasoning budget caller (num_predict=1536)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        await client.generate(prompt="code L1", num_predict=1536, stream=False)
        assert mock_post.call_args[1]["json"]["max_tokens"] == 1536

    # Standard unbounded caller (missing budget -> default ceiling 8192)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        await client.generate(prompt="standard", stream=False)
        assert mock_post.call_args[1]["json"]["max_tokens"] == 8192

    # Verify invalid types are rejected by client.generate
    with pytest.raises(TypeError):
        await client.generate(prompt="bad", max_tokens=True, stream=False)

    with pytest.raises(TypeError):
        await client.generate(prompt="bad", max_tokens=350.0, stream=False)

    with pytest.raises(TypeError):
        await client.generate(prompt="bad", max_tokens="350", stream=False)

    with pytest.raises(ValueError):
        await client.generate(prompt="bad", max_tokens=-10, stream=False)


def test_validate_timeout_config_default_and_overrides(monkeypatch):
    """Verify timeout configuration defaults to 360 and supports valid overrides."""
    monkeypatch.delenv("MODEL_TIMEOUT_SECONDS", raising=False)
    assert validate_timeout_config("MODEL_TIMEOUT_SECONDS", 360) == 360

    # 480-second operator override via environment / .env
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "480")
    assert validate_timeout_config("MODEL_TIMEOUT_SECONDS", 360) == 480

    # Custom positive integer
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "600")
    assert validate_timeout_config("MODEL_TIMEOUT_SECONDS", 360) == 600


def test_validate_timeout_config_rejects_invalid_values(monkeypatch):
    """Verify timeout configuration rejects non-integers, zero, and negative values with clear errors."""
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "invalid_text")
    with pytest.raises(ValueError, match="Configuration error: MODEL_TIMEOUT_SECONDS"):
        validate_timeout_config("MODEL_TIMEOUT_SECONDS", 360)

    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValueError, match="must be a positive integer greater than 0"):
        validate_timeout_config("MODEL_TIMEOUT_SECONDS", 360)

    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "-60")
    with pytest.raises(ValueError, match="must be a positive integer greater than 0"):
        validate_timeout_config("MODEL_TIMEOUT_SECONDS", 360)


def test_nvidia_client_timeout_initialization_and_validation(monkeypatch):
    """Verify NvidiaClient propagates environment timeout and strictly validates explicit timeout_seconds."""
    monkeypatch.delenv("MODEL_TIMEOUT_SECONDS", raising=False)
    client_default = NvidiaClient(api_key="test-key")
    assert client_default.timeout_seconds == 360

    # Environment override 480s propagates to default initialization
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "480")
    client_env = NvidiaClient(api_key="test-key")
    assert client_env.timeout_seconds == 480

    # Explicit integer timeout
    client_explicit = NvidiaClient(api_key="test-key", timeout_seconds=500)
    assert client_explicit.timeout_seconds == 500

    # Rejection of boolean
    with pytest.raises(TypeError, match="bool"):
        NvidiaClient(api_key="test-key", timeout_seconds=True)

    # Rejection of float
    with pytest.raises(TypeError, match="float"):
        NvidiaClient(api_key="test-key", timeout_seconds=480.0)

    # Rejection of string
    with pytest.raises(TypeError, match="str"):
        NvidiaClient(api_key="test-key", timeout_seconds="480")

    # Rejection of zero
    with pytest.raises(ValueError, match="greater than 0"):
        NvidiaClient(api_key="test-key", timeout_seconds=0)

    # Rejection of negative
    with pytest.raises(ValueError, match="greater than 0"):
        NvidiaClient(api_key="test-key", timeout_seconds=-30)


@pytest.mark.asyncio
async def test_streaming_total_deadline_enforcement():
    """Verify NvidiaClient raises TOTAL_GENERATION_TIMEOUT when streaming exceeds deadline."""
    client = NvidiaClient(api_key="test-key", timeout_seconds=1)

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
            import asyncio
            await asyncio.sleep(1.1)
            yield 'data: {"choices": [{"delta": {"content": " world"}}]}'
            yield "data: [DONE]"

    mock_client = MagicMock()
    mock_client.stream.return_value = FakeStreamResponse()

    with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_client
        with pytest.raises(NvidiaTimeoutError) as exc_info:
            await client.generate(prompt="test timeout", stream=True)

        assert exc_info.value.timeout_type == "TOTAL_GENERATION_TIMEOUT"
        assert "exceeded total allowed duration" in str(exc_info.value)



# ==============================================================================
# Task 2: Acceptance-Check Severity Mapping Tests
# ==============================================================================


def test_failed_exploratory_command_followed_by_successful_recovery():
    """Verify exploratory command failure followed by successful recovery is a non-blocking warning."""
    clear_checks_cache()
    m_state = MissionState(mission_id="m_exp_1", workspace_root="/ws", prompt="test", status=MissionStatus.COMPLETED)
    state = HermesRuntimeState(mission=m_state)

    events = [
        HermesEvent(
            event_type=EventType.TOOL_FAILED,
            mission_id="m_exp_1",
            sequence=1,
            payload={
                "tool_name": "execute_command",
                "command": "file index.html",
                "exit_code": 1,
                "error": "file: command not found",
            },
        ),
        HermesEvent(
            event_type=EventType.TOOL_COMPLETED,
            mission_id="m_exp_1",
            sequence=2,
            payload={
                "tool_name": "read_file",
                "target_path": "index.html",
                "exit_code": 0,
            },
        ),
    ]

    resp = extract_mission_checks("m_exp_1", state, events)
    assert resp.total_count == 1
    chk = resp.checks[0]
    assert chk.status == "warning"
    assert chk.severity == "warning"
    assert chk.is_blocking is False
    assert resp.mandatory_failed_count == 0


def test_failed_mandatory_build():
    """Verify failed mandatory build remains strictly blocking with error severity."""
    clear_checks_cache()
    m_state = MissionState(mission_id="m_bld_1", workspace_root="/ws", prompt="test", status=MissionStatus.RUNNING)
    state = HermesRuntimeState(mission=m_state)

    events = [
        HermesEvent(
            event_type=EventType.TOOL_FAILED,
            mission_id="m_bld_1",
            sequence=1,
            payload={
                "tool_name": "execute_command",
                "command": "npm run build",
                "exit_code": 1,
                "error": "Error: compilation failed with 2 errors in src/main.ts",
            },
        )
    ]

    resp = extract_mission_checks("m_bld_1", state, events)
    assert resp.total_count == 1
    chk = resp.checks[0]
    assert chk.status == "failed"
    assert chk.severity == "error"
    assert chk.is_blocking is True
    assert resp.mandatory_failed_count == 1
    assert "Failed Mandatory Build" in chk.title


def test_failed_mandatory_test():
    """Verify failed mandatory test remains strictly blocking with error severity."""
    clear_checks_cache()
    m_state = MissionState(mission_id="m_tst_1", workspace_root="/ws", prompt="test", status=MissionStatus.RUNNING)
    state = HermesRuntimeState(mission=m_state)

    events = [
        HermesEvent(
            event_type=EventType.TOOL_FAILED,
            mission_id="m_tst_1",
            sequence=1,
            payload={
                "tool_name": "execute_command",
                "command": "pytest tests/ -v",
                "exit_code": 1,
                "error": "FAILED tests/test_core.py::test_auth - AssertionError: 401 != 200",
            },
        )
    ]

    resp = extract_mission_checks("m_tst_1", state, events)
    assert resp.total_count == 1
    chk = resp.checks[0]
    assert chk.status == "failed"
    assert chk.severity == "error"
    assert chk.is_blocking is True
    assert resp.mandatory_failed_count == 1
    assert "Failed Mandatory Test" in chk.title


def test_failed_required_file_write():
    """Verify unrecovered file write failure remains strictly blocking."""
    clear_checks_cache()
    m_state = MissionState(mission_id="m_wrt_1", workspace_root="/ws", prompt="test", status=MissionStatus.RUNNING)
    state = HermesRuntimeState(mission=m_state)

    events = [
        HermesEvent(
            event_type=EventType.TOOL_FAILED,
            mission_id="m_wrt_1",
            sequence=1,
            payload={
                "tool_name": "write_file",
                "target_path": "app/server.py",
                "exit_code": 1,
                "error": "PermissionError: [Errno 13] Permission denied: 'app/server.py'",
            },
        )
    ]

    resp = extract_mission_checks("m_wrt_1", state, events)
    assert resp.total_count == 1
    chk = resp.checks[0]
    assert chk.status == "failed"
    assert chk.severity == "error"
    assert chk.is_blocking is True
    assert resp.mandatory_failed_count == 1
    assert "Failed Required File Write" in chk.title


def test_non_fatal_missing_path_probe():
    """Verify exploratory read on missing path is classified as a non-blocking warning."""
    clear_checks_cache()
    m_state = MissionState(mission_id="m_prb_1", workspace_root="/ws", prompt="test", status=MissionStatus.COMPLETED)
    state = HermesRuntimeState(mission=m_state)

    events = [
        HermesEvent(
            event_type=EventType.TOOL_FAILED,
            mission_id="m_prb_1",
            sequence=1,
            payload={
                "tool_name": "read_file",
                "target_path": "package.json",
                "exit_code": 1,
                "error": "FileNotFoundError: File 'package.json' not found in workspace",
            },
        )
    ]

    resp = extract_mission_checks("m_prb_1", state, events)
    assert resp.total_count == 1
    chk = resp.checks[0]
    assert chk.status == "warning"
    assert chk.severity == "warning"
    assert chk.is_blocking is False
    assert resp.mandatory_failed_count == 0


def test_mandatory_requirement_remains_unverified():
    """Verify mission with unverified mandatory requirement reports blocking failure."""
    clear_checks_cache()
    m_state = MissionState(mission_id="m_unv_1", workspace_root="/ws", prompt="test", status=MissionStatus.COMPLETED)
    ledger = AcceptanceLedger(
        goal_id="g1",
        checks={
            "chk_auth": AcceptanceCheck(
                check_id="chk_auth",
                requirement_id="req_auth",
                description="User Authentication Gate",
                status=AcceptanceCheckStatus.FAIL,
                critical=True,
                error_message="Authentication token verification failed",
            )
        },
    )
    state = HermesRuntimeState(mission=m_state, acceptance_ledger=ledger)

    resp = extract_mission_checks("m_unv_1", state, [])
    assert resp.total_count == 1
    chk = resp.checks[0]
    assert chk.status == "failed"
    assert chk.severity == "error"
    assert chk.is_blocking is True
    assert resp.mandatory_failed_count == 1


def test_ui_and_backend_severity_agreement():
    """Verify that backend checks and GUI verification viewmodel agree on critical failures."""
    clear_checks_cache()
    m_state = MissionState(mission_id="m_agr_1", workspace_root="/ws", prompt="test", status=MissionStatus.FAILED)
    ledger = AcceptanceLedger(
        goal_id="g1",
        checks={
            "chk_1": AcceptanceCheck(
                check_id="chk_1",
                requirement_id="req_1",
                description="Critical Core Feature",
                status=AcceptanceCheckStatus.FAIL,
                critical=True,
                error_message="Feature failed unit tests",
            ),
            "chk_2": AcceptanceCheck(
                check_id="chk_2",
                requirement_id="req_2",
                description="Optional Theme Customization",
                status=AcceptanceCheckStatus.FAIL,
                critical=False,
                error_message="Optional color mismatch",
            ),
        },
    )
    state = HermesRuntimeState(mission=m_state, acceptance_ledger=ledger)

    # 1. Backend checks
    backend_resp = extract_mission_checks("m_agr_1", state, [])
    assert backend_resp.mandatory_failed_count == 1
    assert backend_resp.failed_count == 1
    assert backend_resp.warning_count == 1

    # 2. UI ViewModel
    ui_vm = select_verification_view_model(state)
    assert ui_vm.critical_failed == 1
    assert len(ui_vm.checks) == 2

    # Check 1 agrees on critical failure
    chk1_backend = next(c for c in backend_resp.checks if "chk_1" in c.check_id)
    chk1_ui = next(c for c in ui_vm.checks if c.check_id == "chk_1")
    assert chk1_backend.is_blocking is True
    assert chk1_ui.critical is True
    assert chk1_backend.status == "failed"
    assert chk1_ui.status == AcceptanceCheckStatus.FAIL.value

    # Check 2 agrees on non-critical warning
    chk2_backend = next(c for c in backend_resp.checks if "chk_2" in c.check_id)
    chk2_ui = next(c for c in ui_vm.checks if c.check_id == "chk_2")
    assert chk2_backend.is_blocking is False
    assert chk2_ui.critical is False
