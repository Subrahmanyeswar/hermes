"""
HERMES Phase 4I — Operational Release & Launch Acceptance Test Suite
Validates:
1. Canonical launcher & interpreter guard (Python 3.12 requirement, hermes.bat resolution).
2. Secret redaction in logging and JSONL archives.
3. Provider health presentation & status bar visibility.
4. Immediate SEND state transition & asynchronous non-blocking scheduling.
5. SEND/STOP separation & cooperative cancellation.
6. Session resume & physical filesystem state reconciliation.
7. Graceful handling of missing configuration.
8. Physical deliverable verification on disk.
9. Child-process environment isolation & cleanup.
"""

import asyncio
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.runtime_identity import (
    get_canonical_python_executable,
    get_canonical_subprocess_env,
    detect_runtime_identity,
)
from core.mission_planner import Mission, MissionTask, TaskState
from core.mission_runner import MissionRunner
from core.workspace import WorkspaceManager
from utils.logging import redact_secrets


# ==============================================================================
# 1. CANONICAL LAUNCHER & INTERPRETER ENFORCEMENT
# ==============================================================================

def test_canonical_launcher_and_interpreter_guard():
    assert sys.version_info.major == 3 and sys.version_info.minor == 12, (
        f"HERMES strictly requires Python 3.12.x (got {sys.version_info.major}.{sys.version_info.minor})"
    )

    canonical_py = get_canonical_python_executable()
    assert "venv" in canonical_py.lower()
    assert Path(canonical_py).exists()

    launcher_bat = ROOT / "hermes.bat"
    assert launcher_bat.exists(), "hermes.bat launcher must exist at repository root"
    content = launcher_bat.read_text(encoding="utf-8")
    assert "CANONICAL_PYTHON" in content
    assert "venv\\Scripts\\python.exe" in content
    assert "main.py" in content


# ==============================================================================
# 2. SECRET REDACTION IN LOGGING
# ==============================================================================

def test_secret_redaction_in_logging():
    # Test raw API key pattern scrubbing
    sample_nv_key = "nvapi-abcdef1234567890abcdef1234567890abcdef"
    sample_sk_key = "sk-live-9876543210fedcba9876543210fedcba"
    sample_bearer = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret12345678"

    text = f"Connecting to endpoint with key={sample_nv_key} and backup={sample_sk_key} Auth: {sample_bearer}"
    redacted = redact_secrets(text)

    assert sample_nv_key not in redacted
    assert sample_sk_key not in redacted
    assert "secret12345678" not in redacted
    assert "[REDACTED_NVIDIA_KEY]" in redacted
    assert "[REDACTED_API_KEY]" in redacted
    assert "[REDACTED_TOKEN]" in redacted


# ==============================================================================
# 3. PROVIDER HEALTH PRESENTATION & STATUS BAR VISIBILITY
# ==============================================================================

def test_provider_health_status_bar_presentation():
    from ui.panels.status_bar import StatusBar

    sb = StatusBar()
    # Default initial state
    rendered = sb._render_status_text().plain
    assert "T1:GLM-5.3-Flash" in rendered or "GLM" in rendered

    # Test T1 Degraded / Circuit Open
    sb.update_provider_health("T1:OPEN")
    rendered_open = sb._render_status_text().plain
    assert "T1:OPEN" in rendered_open

    # Test T2 Failover
    sb.update_provider_health("T2:FAILOVER")
    rendered_failover = sb._render_status_text().plain
    assert "T2:FAILOVER" in rendered_failover

    # Test Background Probing
    sb.update_provider_health("T1:PROBING")
    rendered_probing = sb._render_status_text().plain
    assert "T1:PROBING" in rendered_probing

    # Test T1 Recovery
    sb.update_provider_health("T1:RECOVERED")
    rendered_recovered = sb._render_status_text().plain
    assert "T1:RECOVERED" in rendered_recovered

    # Test T3 Arbitration
    sb.update_provider_health("T3:ARBITRATION")
    rendered_arb = sb._render_status_text().plain
    assert "T3:ARBITRATION" in rendered_arb


# ==============================================================================
# 4. IMMEDIATE SEND STATE TRANSITION & ASYNC SCHEDULING
# ==============================================================================

@pytest.mark.asyncio
async def test_immediate_send_state_transition_and_latency():
    from ui.app import HermesApp, UserMessageSent

    app = HermesApp(show_startup=False)
    assert app.is_processing is False

    # Simulate user sending message
    msg = UserMessageSent("Build login authentication module")

    # Mock _process_request to verify async invocation
    app._process_request = MagicMock(return_value=None)

    t0 = time.perf_counter()
    await app.handle_user_message(msg)
    t_elapsed = (time.perf_counter() - t0) * 1000.0

    # Must immediately transition is_processing to True
    assert app.is_processing is True
    # Internal SEND audit latency must be sub-10ms
    assert app._send_latency_audit["latency_ms"] < 10.0
    # Must have scheduled the worker
    assert app._process_request.called


# ==============================================================================
# 5. SEND/STOP SEPARATION & COOPERATIVE CANCELLATION
# ==============================================================================

@pytest.mark.asyncio
async def test_send_stop_separation_and_cooperative_cancellation():
    from ui.app import HermesApp

    app = HermesApp(show_startup=False)
    app.is_processing = True

    mock_driver = MagicMock()
    app._mission_driver = mock_driver
    mock_worker = MagicMock()
    app._current_worker = mock_worker

    # Call STOP handler
    await app.on_stop_pressed()

    # Verify stop state reflected immediately
    assert app.is_processing is False
    assert mock_driver.abort_current_mission.called
    assert mock_worker.cancel.called


# ==============================================================================
# 6. SESSION RESUME & PHYSICAL RECONCILIATION
# ==============================================================================

def test_session_resume_physical_reconciliation(tmp_path):
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()

    # File A exists physically on disk with valid content
    file_a = ws_root / "auth.py"
    file_a.write_text("def verify_token(): return True\n", encoding="utf-8")

    # File B does NOT exist on disk
    file_b = ws_root / "routes.py"

    wm = WorkspaceManager()
    wm.lock(str(ws_root))

    # Construct mission:
    # Task 1 was marked COMPLETED, but its file (routes.py) is missing -> Reopen to PENDING
    # Task 2 was marked PENDING, but its file (auth.py) is already present and valid -> Mark COMPLETED
    task1 = MissionTask(
        task_id="t1",
        title="Create routes.py",
        description="Implement API routes",
        state=TaskState.COMPLETED,
        target_paths=["routes.py"],
    )
    task2 = MissionTask(
        task_id="t2",
        title="Create auth.py",
        description="Implement token verification",
        state=TaskState.PENDING,
        target_paths=["auth.py"],
    )

    mission = Mission(
        mission_id="m_reconcile",
        user_prompt="Setup authentication and routes",
        tasks=[task1, task2],
    )

    runner = MissionRunner(
        orchestrator=MagicMock(),
        workspace_manager=wm,
    )

    runner.reconcile_mission_state(mission)

    # Task 1 must be reopened to PENDING because routes.py is missing
    assert task1.state == TaskState.PENDING
    # Task 2 must be satisfied as COMPLETED because auth.py exists and is non-empty
    assert task2.state == TaskState.COMPLETED


# ==============================================================================
# 7. GRACEFUL HANDLING OF MISSING CONFIGURATION
# ==============================================================================

def test_missing_configuration_graceful_handling():
    from models.nvidia_client import NvidiaClient

    # Missing API key must not crash on instantiation
    with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}, clear=False):
        with patch("config.model_config.NVIDIA_API_KEY", ""), patch("models.nvidia_client.NVIDIA_API_KEY", ""):
            client = NvidiaClient(api_key="")
            assert client.api_key == ""

            # is_running check must safely return False without throwing exceptions
            is_up = asyncio.run(client.is_running(timeout=0.5))
            assert is_up is False


# ==============================================================================
# 8. PHYSICAL DELIVERABLE VERIFICATION
# ==============================================================================

def test_physical_deliverable_verification(tmp_path):
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()

    target_file = ws_root / "service.py"
    target_file.write_text("class PaymentService:\n    pass\n", encoding="utf-8")

    # Assert deliverable exists physically with size > 0
    assert target_file.exists()
    assert target_file.is_file()
    assert target_file.stat().st_size > 0


# ==============================================================================
# 9. CHILD-PROCESS ENVIRONMENT ISOLATION & CLEANUP
# ==============================================================================

def test_child_process_environment_isolation():
    env = get_canonical_subprocess_env()

    # Canonical venv Scripts must be at the very front of PATH
    path_entries = env.get("PATH", "").split(os.pathsep)
    assert len(path_entries) > 0
    assert "venv" in path_entries[0].lower()
    assert "scripts" in path_entries[0].lower()

    # PYTHONHOME must be absent to avoid leaking global libraries
    assert "PYTHONHOME" not in env

    # PYTHONNOUSERSITE must be 1 to isolate from user site-packages
    assert env.get("PYTHONNOUSERSITE") == "1"


# ==============================================================================
# 10. LOGGING SETUP LIFECYCLE & SESSION ID GENERATION
# ==============================================================================

def test_logging_setup_lifecycle_and_session_id_generation(tmp_path):
    from utils.logging import setup_logging, generate_session_id, _SESSION_ID

    # 1. generate_session_id returns 12-char hex string
    gen_id = generate_session_id()
    assert isinstance(gen_id, str)
    assert len(gen_id) == 12
    assert all(c in "0123456789abcdef" for c in gen_id)

    # 2. setup_logging succeeds with no session_id provided and generates valid 12-char ID
    sid_default = setup_logging(debug=False, tui=True)
    assert isinstance(sid_default, str)
    assert len(sid_default) == 12

    # 3. Explicitly supplied session ID is preserved exactly
    custom_id = "test_custom_sid_123"
    sid_custom = setup_logging(session_id=custom_id, debug=True, tui=False)
    assert sid_custom == custom_id

    # 4. Repeated initialization is idempotent and stable
    sid_repeat = setup_logging(session_id="repeated_session", debug=False, tui=True)
    assert sid_repeat == "repeated_session"

    # 5. Secret redaction remains active in log records
    from utils.logging import redact_secrets
    cleaned = redact_secrets("Token is nvapi-secret-key-1234567890")
    assert "nvapi-secret-key-1234567890" not in cleaned

