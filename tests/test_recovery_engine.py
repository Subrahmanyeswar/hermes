# tests/test_recovery_engine.py
import pytest
from core.persistence.models import SessionStatus, CheckpointReason
from core.recovery.engine import RecoveryEngine
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import HermesRuntimeState, TaskStatus
from core.sessions.manager import SessionManager


def test_recovery_engine_resume_with_journal_replay(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    hermes_dir = tmp_path / ".hermes"

    mgr = SessionManager(base_dir=hermes_dir, workspace_root=workspace)
    session = mgr.create_session("mission_resume")
    state = HermesRuntimeState.create_empty("mission_resume", session.session_id)

    # 1. Create checkpoint C1
    chk = mgr.create_checkpoint(session.session_id, state, reason=CheckpointReason.MANUAL)

    # 2. Add journal events AFTER checkpoint
    ev1 = HermesEvent(event_type=EventType.TASK_CREATED, payload={"task_id": "t_after", "title": "Post Checkpoint Task"})
    ev2 = HermesEvent(event_type=EventType.TASK_STARTED, payload={"task_id": "t_after"})
    ev3 = HermesEvent(event_type=EventType.TASK_COMPLETED, payload={"task_id": "t_after"})
    mgr.journal.append(session.session_id, ev1)
    mgr.journal.append(session.session_id, ev2)
    mgr.journal.append(session.session_id, ev3)

    # Simulate process crash / clean pause
    mgr.pause_session(session.session_id)

    # 3. Resume session
    recovery = RecoveryEngine(session_manager=mgr, workspace_root=workspace)
    reconstructed_state, verdict = recovery.resume_session(session.session_id)

    assert verdict.can_proceed is True
    # The task created and completed via journal after checkpoint MUST be present and completed
    assert "t_after" in reconstructed_state.tasks
    assert reconstructed_state.tasks["t_after"].status == TaskStatus.COMPLETED

    # Session status must be restored to RUNNING
    s_active = mgr.get_session(session.session_id)
    assert s_active.status == SessionStatus.RUNNING
