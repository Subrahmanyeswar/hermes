# tests/test_rewind_engine.py
import pytest
from core.persistence.models import CheckpointReason, RewindMode
from core.recovery.rewind import RewindEngine
from core.runtime_state.models import HermesRuntimeState, AcceptanceCheck, AcceptanceCheckStatus
from core.sessions.manager import SessionManager


def test_rewind_preserves_user_edits_by_default(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_a = workspace / "file_a.py"
    file_a.write_text("v1_original", encoding="utf-8")

    hermes_dir = tmp_path / ".hermes"
    mgr = SessionManager(base_dir=hermes_dir, workspace_root=workspace)
    session = mgr.create_session("m_user_protect")
    state = HermesRuntimeState.create_empty("m_user_protect", session.session_id)

    # 1. Checkpoint C1
    chk1 = mgr.create_checkpoint(session.session_id, state, reason=CheckpointReason.MANUAL)

    # 2. User edits file_a outside HERMES
    file_a.write_text("v2_user_modified", encoding="utf-8")

    # 3. Rewind to C1
    rewind = RewindEngine(
        workspace_root=workspace,
        checkpoint_engine=mgr.checkpoint_engine,
        blob_store=mgr.blob_store,
    )
    plan = rewind.preview_rewind(session.session_id, chk1.checkpoint_id)
    assert plan.user_conflicts_count == 1
    assert plan.actions[0].user_conflict is True

    # Execute rewind: must preserve user edits!
    rewind.execute_rewind(session.session_id, chk1.checkpoint_id, mode=RewindMode.CODE_AND_CONVERSATION)
    assert file_a.read_text(encoding="utf-8") == "v2_user_modified"


def test_required_core_workflow_alternate_repair_after_rewind(tmp_path):
    """
    Requirement #212:
    C1 -> modify file A -> failure -> C2 -> modify file A again -> failure -> rewind C1 -> verify file A == C1 -> alternate repair -> pass!
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_a = workspace / "calc.py"
    file_a.write_text("def add(a, b): return 0", encoding="utf-8")  # Buggy baseline

    hermes_dir = tmp_path / ".hermes"
    mgr = SessionManager(base_dir=hermes_dir, workspace_root=workspace)
    session = mgr.create_session("m_workflow")
    state = HermesRuntimeState.create_empty("m_workflow", session.session_id)
    state.acceptance_ledger.checks["chk_calc"] = AcceptanceCheck(
        check_id="chk_calc",
        requirement_id="req_1",
        description="Verify addition",
        status=AcceptanceCheckStatus.NOT_RUN,
    )

    # 1. Checkpoint C1 (Baseline)
    chk1 = mgr.create_checkpoint(session.session_id, state, reason=CheckpointReason.MANUAL)

    # 2. Agent attempts bad repair 1
    file_a.write_text("def add(a, b): return a - b", encoding="utf-8")
    state.acceptance_ledger.checks["chk_calc"].status = AcceptanceCheckStatus.FAIL

    # 3. Checkpoint C2 (Failed attempt 1)
    chk2 = mgr.create_checkpoint(session.session_id, state, reason=CheckpointReason.PRE_REPAIR)

    # 4. Agent attempts bad repair 2
    file_a.write_text("def add(a, b): return None", encoding="utf-8")

    # 5. REWIND to C1 (known-good baseline)
    rewind = RewindEngine(
        workspace_root=workspace,
        checkpoint_engine=mgr.checkpoint_engine,
        blob_store=mgr.blob_store,
    )
    # Both bad repairs were agent changes
    restored_state = rewind.execute_rewind(
        session.session_id,
        chk1.checkpoint_id,
        mode=RewindMode.CODE_AND_CONVERSATION,
        known_agent_created_files={"calc.py"},
    )

    # Verify file_a restored to C1 baseline
    assert file_a.read_text(encoding="utf-8") == "def add(a, b): return 0"

    # 6. Apply Alternate Repair (Correct fix)
    file_a.write_text("def add(a, b): return a + b", encoding="utf-8")
    restored_state.acceptance_ledger.checks["chk_calc"].status = AcceptanceCheckStatus.PASS
    chk3 = mgr.create_checkpoint(session.session_id, restored_state, reason=CheckpointReason.POST_VERIFICATION)

    # Checkpoint history must reflect C1, C2, and C3 (complete historical record preserved)
    checkpoints = mgr.checkpoint_engine.list_checkpoints(session.session_id)
    assert len(checkpoints) == 3
    assert checkpoints[0].checkpoint_id == chk1.checkpoint_id
    assert checkpoints[1].checkpoint_id == chk2.checkpoint_id
    assert checkpoints[2].checkpoint_id == chk3.checkpoint_id
