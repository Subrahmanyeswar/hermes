# tests/test_tui_prompt14_integration.py
"""Tests for Prompt 14 Persistence & Recovery integration with TUI 2.x."""

import pytest
from core.persistence.models import CheckpointReason, RewindMode
from core.recovery.engine import RecoveryEngine
from core.runtime_state.models import HermesRuntimeState, MissionStatus
from core.sessions.manager import SessionManager
from ui.rendering.fallback_renderer import FallbackRenderer
from ui.rendering.render_supervisor import RenderSupervisor
from ui.rendering.terminal_capabilities import TerminalCapabilities
from ui.state.selectors import build_root_view_model
from ui.viewmodels.recovery import RecoveryViewModel, RewindPreviewViewModel


def test_tui_displays_prompt14_checkpoints_and_rewind_preview(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('hello')", encoding="utf-8")
    hermes_dir = tmp_path / ".hermes"

    mgr = SessionManager(base_dir=hermes_dir, workspace_root=workspace)
    session = mgr.create_session("m_tui_p14")
    state = HermesRuntimeState.create_empty("m_tui_p14", session.session_id)

    # 1. Create Checkpoint
    chk = mgr.create_checkpoint(session.session_id, state, reason=CheckpointReason.MANUAL)

    # 2. Build TUI View Model with Rewind Preview
    rewind_vm = RewindPreviewViewModel(
        checkpoint_id=chk.checkpoint_id,
        reason="MANUAL",
        files_changed_count=2,
        user_conflicts_count=1,
        conflicts_details=("user_edit.txt",),
        restore_files_count=1,
        preserve_files_count=1,
        can_proceed=True,
        visible=True,
    )

    root_vm = build_root_view_model(
        state=state,
        rewind_preview=rewind_vm,
    )

    assert root_vm.rewind_preview.checkpoint_id == chk.checkpoint_id
    assert root_vm.rewind_preview.user_conflicts_count == 1

    # Render frame with rewind preview modal
    from ui.rendering.renderer import TuiRenderer
    renderer = TuiRenderer()
    caps = TerminalCapabilities.fallback_plain(90, 25)
    frame = renderer.build_frame(root_vm, caps)
    plain = frame.to_plain_text()

    assert "Rewind Preview" in plain
    assert chk.checkpoint_id in plain
    assert "USER CONFLICTS DETECTED" in plain


def test_tui_crash_leaves_persistence_intact(tmp_path):
    """Prove that a catastrophic TUI crash leaves SQLite and CAS session state 100% intact."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "code.py").write_text("x = 10\n", encoding="utf-8")
    hermes_dir = tmp_path / ".hermes"

    mgr = SessionManager(base_dir=hermes_dir, workspace_root=workspace)
    session = mgr.create_session("m_crash_safe")
    state = HermesRuntimeState.create_empty("m_crash_safe", session.session_id)
    state.mission.status = MissionStatus.RUNNING

    # Create persistent checkpoint
    chk = mgr.create_checkpoint(session.session_id, state, reason=CheckpointReason.POST_ACTION)

    # Simulate TUI crash in rendering supervisor
    class CrashingRenderer:
        def build_frame(self, vm, caps, frame_id=0):
            raise SystemError("Fatal display bus crash!")

    supervisor = RenderSupervisor(primary_renderer=CrashingRenderer(), fallback_renderer=FallbackRenderer())
    caps = TerminalCapabilities.fallback_plain(80, 24)
    root_vm = build_root_view_model(state=state)

    # Supervisor isolates crash, falls back
    frame = supervisor.render_frame(root_vm, caps)
    assert supervisor.primary_failures == 1

    # State in SQLite & CAS must be completely unaffected and resumable
    recovery = RecoveryEngine(session_manager=mgr, workspace_root=workspace)
    resumed_state, _ = recovery.resume_session(session.session_id)

    assert resumed_state.mission.mission_id == "m_crash_safe"
    assert resumed_state.session.session_id == session.session_id
    assert recovery.session_manager.checkpoint_engine.verify_checkpoint_integrity(chk.checkpoint_id) is True
