# tests/test_session_manager.py
import pytest
from core.persistence.models import SessionStatus, CheckpointReason
from core.runtime_state.models import HermesRuntimeState
from core.sessions.manager import SessionManager


def test_session_manager_create_and_clear(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    hermes_dir = tmp_path / ".hermes"

    mgr = SessionManager(base_dir=hermes_dir, workspace_root=workspace)
    s1 = mgr.create_session("mission_1", branch_name="main")

    assert s1.session_id.startswith("sess_")
    assert s1.status == SessionStatus.CREATED

    # Clear conversation: old session remains in history, fresh session returned
    s2 = mgr.clear_session(s1.session_id, new_mission_id="mission_2")
    assert s2.session_id != s1.session_id

    s1_reloaded = mgr.get_session(s1.session_id)
    assert s1_reloaded.status == SessionStatus.PAUSED

    all_sessions = mgr.list_sessions()
    assert len(all_sessions) == 2


def test_session_manager_fork_and_branch(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "code.py").write_text("a = 1", encoding="utf-8")
    hermes_dir = tmp_path / ".hermes"

    mgr = SessionManager(base_dir=hermes_dir, workspace_root=workspace)
    parent = mgr.create_session("mission_parent")
    state = HermesRuntimeState.create_empty("mission_parent", parent.session_id)

    chk = mgr.create_checkpoint(parent.session_id, state, reason=CheckpointReason.PRE_BRANCH)

    # Fork session from checkpoint
    child = mgr.fork_session(parent.session_id, chk.checkpoint_id, branch_name="strategy_b")
    assert child.parent_session_id == parent.session_id
    assert child.current_checkpoint_id == chk.checkpoint_id
    assert child.branch_name == "strategy_b"

    # Parent remains unchanged
    p_reloaded = mgr.get_session(parent.session_id)
    assert p_reloaded.parent_session_id is None
