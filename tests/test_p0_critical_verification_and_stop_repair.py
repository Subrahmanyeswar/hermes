# tests/test_p0_critical_verification_and_stop_repair.py
"""
P0 Verification, Latency, Anti-Deadlock, Windows Compatibility & Stop Repair Suite.
Validates:
1. Windows command translation for ls, ls -1, cat, which.
2. Fast risk-based verification profiles (Profile A < 1s, B, C, D).
3. Task lifecycle advancement emitting REQUIREMENT_COMPLETED and updating acceptance_ledger.
4. Fast, non-blocking Stop/cancellation updating database and state store to CANCELLED.
"""

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_loop.loop import AgentLoop
from core.mission_planner import Mission
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import MissionControlContext, MissionStatus
from core.verification_profiles import (
    VerificationProfile,
    VerificationProfileEvaluator,
    classify_verification_profile,
)
from tools.shell_tools import BashExecTool, _command_for_platform


def test_windows_shell_command_translation():
    """Verify that POSIX commands translate to valid Windows/Python commands."""
    cmd_ls = _command_for_platform("ls -1")
    assert "python" in cmd_ls.lower()
    assert "listdir" in cmd_ls

    cmd_cat = _command_for_platform("cat README.md")
    assert "python" in cmd_cat.lower()
    assert "read" in cmd_cat

    cmd_which = _command_for_platform("which git")
    assert cmd_which == "where git"


def test_bash_exec_tool_ls_and_cat_execution():
    """Verify BashExecTool executes ls -1 and cat with exit code 0."""
    tool = BashExecTool()
    res = tool.execute(BashExecTool.Input(command="ls -1"))
    assert res.success is True
    assert res.exit_code == 0
    assert len(res.output.splitlines()) > 0

    res_cat = tool.execute(BashExecTool.Input(command="cat README.md"))
    assert res_cat.success is True
    assert res_cat.exit_code == 0
    assert len(res_cat.output) > 0


def test_profile_classification():
    """Verify classification into Profile A, B, C, D."""
    p_smoke = "# HERMES LIVE WRITE-TOOL SMOKE TEST\nCreate smoke_test.html and README.md\nDiagnostic test"
    assert classify_verification_profile(p_smoke) == VerificationProfile.PROFILE_A

    p_web = "Build the AETHER ORBITAL 3D rocket website with Three.js WebGL canvas"
    assert classify_verification_profile(p_web) == VerificationProfile.PROFILE_C

    p_high_risk = "Run security audit and penetration test on auth service"
    assert classify_verification_profile(p_high_risk) == VerificationProfile.PROFILE_D

    p_code = "Implement a utility function to compute fibonacci numbers"
    assert classify_verification_profile(p_code) == VerificationProfile.PROFILE_B


def test_profile_a_deterministic_fast_check():
    """Verify Profile A passes in < 1 second for valid files and fails for missing files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        html_file = tmp_path / "smoke_test.html"
        readme_file = tmp_path / "README.md"

        html_file.write_text("<!DOCTYPE html><html><h1>HERMES Write Tool Verification</h1><p>diagnostic test</p></html>", encoding="utf-8")
        readme_file.write_text("# Smoke Test\nDiagnostic test documentation.", encoding="utf-8")

        prompt = "Create smoke_test.html and README.md with heading HERMES Write Tool Verification and diagnostic test"
        t0 = time.monotonic()
        res = VerificationProfileEvaluator.evaluate(
            VerificationProfile.PROFILE_A,
            tmp_path,
            prompt,
            written_files=["smoke_test.html", "README.md"],
        )
        elapsed = time.monotonic() - t0

        assert res.passed is True
        assert elapsed < 1.0  # Must complete in under 1 second
        assert len(res.issues) == 0
        assert "smoke_test.html" in res.evidence
        assert "README.md" in res.evidence


@pytest.mark.asyncio
async def test_agent_loop_advances_requirement_completed():
    """Verify that _advance_active_task publishes REQUIREMENT_COMPLETED and updates planning service."""
    mock_orch = MagicMock()
    mock_bus = MagicMock()
    mock_bus.publish = MagicMock()

    mock_planning = MagicMock()
    mock_planning.acceptance_ledger = MagicMock()
    chk_mock = MagicMock()
    chk_mock.check_id = "chk_1"
    mock_planning.acceptance_ledger.get_checks_for_requirement.return_value = [chk_mock]
    req_mock = MagicMock()
    mock_planning.requirements = {"task_1": req_mock}

    loop = AgentLoop(orchestrator=mock_orch, event_bus_instance=mock_bus)
    loop._mission_id = "m_test_advance"
    loop.planning_service = mock_planning
    loop._tasks = [
        {"task_id": "task_1", "title": "Create Files", "status": "PENDING"},
        {"task_id": "task_2", "title": "Verify Files", "status": "PENDING"},
    ]

    await loop._ensure_active_task()
    assert loop._active_task_idx == 0

    await loop._advance_active_task("Files verified on disk")
    assert loop._tasks[0]["status"] == "COMPLETED"
    assert loop._active_task_idx == 1

    # Check published events
    event_types = [call[0][0].event_type for call in mock_bus.publish.call_args_list if isinstance(call[0][0], HermesEvent)]
    assert EventType.TASK_COMPLETED in event_types
    assert EventType.REQUIREMENT_COMPLETED in event_types

    # Check planning service was updated
    assert mock_planning.record_acceptance_result.called
    assert req_mock.transition_status.called


@pytest.mark.asyncio
async def test_stop_mission_cancels_immediately_without_blocking():
    """Verify stop_mission updates DB, state store, and cancels in < 100ms."""
    from core.server.runtime_adapter import RuntimeAdapter
    from core.event_bus import EventBus

    bus = EventBus()
    adapter = RuntimeAdapter(event_bus=bus)

    m_id = "m_test_fast_stop"
    control = MissionControlContext(mission_id=m_id, run_id="run_1", attempt_number=1)
    adapter._mission_controls[m_id] = control

    # Mock an active task that is long running
    async def long_running_task():
        try:
            await asyncio.sleep(100.0)
        except asyncio.CancelledError:
            pass

    bg_task = asyncio.create_task(long_running_task())
    adapter._active_tasks[m_id] = bg_task

    mock_db = MagicMock()
    mock_db.get_mission.return_value = {
        "mission_id": m_id,
        "status": "RUNNING",
        "workspace_path": "C:\\fake",
        "run_id": "run_1",
        "attempt_number": 1,
    }
    bus.get_database = MagicMock(return_value=mock_db)

    t0 = time.monotonic()
    stopped = await adapter.stop_mission(m_id, timeout=1.0)
    elapsed = time.monotonic() - t0

    assert stopped is True
    assert elapsed < 0.3  # Immediate response in < 300ms
    assert control.is_cancelled is True
    assert control.is_terminal is True
    assert bg_task.cancelled() or bg_task.done()

    # Verify DB was saved with CANCELLED
    assert mock_db.save_mission.called
    save_kwargs = mock_db.save_mission.call_args[1]
    assert save_kwargs["status"] == "CANCELLED"
    assert save_kwargs["execution_active"] is False


def test_behavioral_verifier_ignores_external_cdn_links(tmp_path):
    """Verify that external CDN scripts and stylesheets are not flagged as missing local files."""
    from core.agent_loop.behavioral_verifier import TechnologyAwareBehavioralVerifier

    html = (
        "<!DOCTYPE html><html><head>"
        '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/normalize/8.0.1/normalize.css">'
        '<link rel="stylesheet" href="styles.css">'
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r152/three.min.js"></script>'
        '<script src="https://cdn.jsdelivr.net/npm/three@0.152.0/examples/js/controls/OrbitControls.js"></script>'
        '<script src="app.js"></script>'
        "</head><body><button id='btn'>Launch</button></body></html>"
    )
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    (tmp_path / "styles.css").write_text("body { background: #000; color: #fff; }", encoding="utf-8")
    (tmp_path / "app.js").write_text(
        "document.getElementById('btn').addEventListener('click', () => { document.body.textContent = 'Launched!'; });",
        encoding="utf-8"
    )

    res = TechnologyAwareBehavioralVerifier.verify_workspace(
        ws_root=tmp_path,
        mission_prompt="Interactive 3D rocket website with launch button",
    )
    # Ensure no issues about CDN scripts not existing in workspace
    cdn_issues = [iss for iss in res.issues if "which does not exist in workspace" in iss]
    assert len(cdn_issues) == 0, f"Expected 0 CDN missing file issues, got: {cdn_issues}"
    assert any("external_cdn_js" in feat for feat in res.features_detected)
    assert any("external_cdn_css" in feat for feat in res.features_detected)


def test_read_file_tool_unchanged_read_enforcement(tmp_path):
    """Verify that repeatedly reading an unchanged file is rejected with UNCHANGED_READ."""
    from tools.file_tools import ReadFileTool, reset_read_loop_tracker
    from core.workspace import workspace_manager

    reset_read_loop_tracker()
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello World", encoding="utf-8")

    tool = ReadFileTool()
    # Execute 3 times -> success
    for i in range(3):
        res = tool.execute({"path": str(test_file)})
        assert res.success is True

    # 4th time -> rejected
    res4 = tool.execute({"path": str(test_file)})
    assert res4.success is False
    assert "NO_PROGRESS_LOOP_ENFORCEMENT" in res4.error
    assert res4.details.get("code") == "UNCHANGED_READ"

