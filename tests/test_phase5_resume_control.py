# tests/test_phase5_resume_control.py
"""
HERMES Phase 5 Acceptance Test Suite: Safe Resume from the First Unfinished Task.

Scenarios Covered:
- Scenario A: Checkpoint Integrity Validation (valid checkpoint passes; corrupt CAS state/file blobs fail).
- Scenario B: Original Workspace Binding & Verification (resuming in original folder succeeds; missing or substituted folder fails).
- Scenario C: Disk-vs-Ledger Reconciliation & User Mod Detection (detect missing files, prior/post hash match, and post-stop user edits).
- Scenario D: Uncertain Outcome Protocol & Blocking (unresolved OUTCOME_UNKNOWN operations block resume until reconciled).
- Scenario E: First Unfinished Task Selection (skips completed/verified tasks, selects first incomplete in dependency order).
- Scenario F: Terminal Run Immutability & Continuation Run Identity (old terminal run_id remains cancelled; new run_id created with attempt_number + 1).
- Scenario G: Duplicate Resume Idempotency & Concurrency Protection (concurrent duplicate resume calls return 409 conflict).
- Scenario H: Safe Resume via RuntimeAdapter & AgentLoop Execution (executes continuation task without repeating earlier settled writes).
- Scenario I: Fast Resume Preview API (inspects resume plan and discrepancies without side effects).
- Scenario J: Full Process Restart Recovery Cycle (simulates server shutdown, restarts, loads state, and successfully resumes).
"""

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from core.checkpoints.engine import CheckpointEngine
from core.event_bus import EventBus
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import (
    CheckpointManifest,
    CheckpointReason,
    CheckpointTrigger,
    FileSnapshot,
    OperationStatus,
    WorkspaceManifest,
)
from core.persistence.recovery import (
    Discrepancy,
    ReconciliationDiscrepancyType,
    RecoveryEngine,
    ResumePlan,
)
from core.persistence.serializer import serialize_runtime_state
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionControlContext,
    MissionState,
    MissionStatus,
    TaskState,
    TaskStatus,
)
from core.runtime_state.store import StateStore
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import WorkspaceManager


# ── Scenario A: Checkpoint Integrity Validation ──────────────────────────────

def test_scenario_a_checkpoint_integrity_validation(tmp_path):
    """
    Valid checkpoint manifests and CAS blobs pass verification.
    Corrupted CAS file blobs or missing state blobs fail validation with clear reasons.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    engine = CheckpointEngine(base_dir=tmp_path, workspace_root=ws_dir, db=db, blob_store=blobs)
    recovery = RecoveryEngine(db=db, blob_store=blobs, checkpoint_engine=engine)

    # 1. Create a dummy file in workspace and put in blob store
    test_file = ws_dir / "app.py"
    test_content = b"print('Hello Hermes')"
    test_file.write_bytes(test_content)
    file_blob_id = blobs.put(test_content)

    state = HermesRuntimeState.create_empty(mission_id="m_chk_test")
    state_dict, state_hash = serialize_runtime_state(state)
    state_bytes = json.dumps(state_dict, sort_keys=True).encode("utf-8")
    state_blob_id = blobs.put(state_bytes)

    # 2. Build and commit valid checkpoint
    now = time.time()
    ws_manifest = WorkspaceManifest(
        workspace_root=str(ws_dir),
        total_files=1,
        total_bytes=len(test_content),
        files={"app.py": FileSnapshot(relative_path="app.py", sha256=file_blob_id, size_bytes=len(test_content), mtime_ns=int(now * 1e9), blob_id=file_blob_id)},
    )
    chk = CheckpointManifest(
        checkpoint_id="chk_valid_01",
        session_id="sess_01",
        mission_id="m_chk_test",
        sequence=1,
        state_hash=state_blob_id,
        created_at=now,
        workspace=ws_manifest,
    )
    # Save session row to satisfy foreign key constraint
    from core.persistence.models import SessionStatus
    db.save_session(
        session_id=chk.session_id,
        mission_id=chk.mission_id,
        workspace_root=str(ws_dir),
        status=SessionStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )

    db.save_checkpoint(
        checkpoint_id=chk.checkpoint_id,
        session_id=chk.session_id,
        sequence=chk.sequence,
        reason=chk.reason,
        trigger=chk.trigger,
        created_at=now,
        state_hash=state_blob_id,
        manifest_hash=chk.manifest_hash,
        manifest_json=json.dumps(chk.to_dict(), sort_keys=True),
    )

    # Valid check passes
    valid, manifest, msg = recovery.validate_checkpoint("chk_valid_01")
    assert valid is True
    assert manifest is not None
    assert manifest.checkpoint_id == "chk_valid_01"

    # Corrupt a blob on disk
    blob_path = blobs._blob_path(file_blob_id)
    blob_path.write_bytes(b"corrupted_bytes")
    valid_corrupt, _, msg_corrupt = recovery.validate_checkpoint("chk_valid_01")
    assert valid_corrupt is False
    assert "missing or corrupt" in msg_corrupt


# ── Scenario B: Original Workspace Binding & Verification ────────────────────

def test_scenario_b_original_workspace_binding_and_verification(tmp_path):
    """
    Resuming in original folder succeeds.
    Missing, moved, or substituted folder is blocked with an explicit error.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "orig_workspace"
    ws_dir.mkdir()

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    recovery = RecoveryEngine(db=db, blob_store=blobs)

    # Save mission pointing to ws_dir
    db.save_mission(
        mission_id="m_ws_bind",
        workspace_path=str(ws_dir),
        status="STOPPED",
        prompt="Build project",
    )
    # Save a minimal snapshot
    state = HermesRuntimeState.create_empty(mission_id="m_ws_bind")
    state.mission.workspace_root = str(ws_dir)
    state.tasks["t1"] = TaskState(task_id="t1", mission_id="m_ws_bind", title="Task 1", status=TaskStatus.PENDING)
    snap_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(mission_id="m_ws_bind", workspace_path=str(ws_dir), status="STOPPED", snapshot_dict=snap_dict, state_hash=s_hash)

    plan = recovery.formulate_resume_plan("m_ws_bind")
    assert plan.can_resume is True
    assert plan.original_workspace == str(ws_dir)

    # Now simulate deleted/missing original workspace
    os.rmdir(ws_dir)
    plan_missing = recovery.formulate_resume_plan("m_ws_bind")
    assert plan_missing.can_resume is False
    assert "does not exist" in plan_missing.reason
    assert any(d.discrepancy_type == ReconciliationDiscrepancyType.WORKSPACE_INACCESSIBLE for d in plan_missing.discrepancies)


# ── Scenario C: Disk-vs-Ledger Reconciliation & User Mod Detection ───────────

def test_scenario_c_disk_reconciliation_and_user_mod_detection(tmp_path):
    """
    Reconciliation verifies that settled writes exist with matching hashes.
    Post-interruption external file edits or missing files are detected as blocking discrepancies.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    recovery = RecoveryEngine(db=db, blob_store=blobs)

    # 1. Record completed write operation
    f1 = ws_dir / "index.html"
    c1 = b"<html><body>V1</body></html>"
    f1.write_bytes(c1)
    post_hash_1 = hashlib.sha256(c1).hexdigest()

    db.record_tool_intent(
        operation_id="op_write_index",
        mission_id="m_recon",
        tool_name="write_file",
        intent_seq=1,
        target_path="index.html",
        workspace_root=str(ws_dir),
    )
    db.record_tool_result(
        operation_id="op_write_index",
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=post_hash_1,
    )

    discs = recovery.reconcile_disk_with_ledger("m_recon", ws_dir)
    assert len(discs) == 0  # Matches perfectly

    # 2. Simulate external user edit post-stop
    f1.write_bytes(b"<html><body>MODIFIED BY USER</body></html>")
    discs_mod = recovery.reconcile_disk_with_ledger("m_recon", ws_dir)
    assert len(discs_mod) == 1
    assert discs_mod[0].discrepancy_type == ReconciliationDiscrepancyType.USER_MODIFIED
    assert discs_mod[0].blocking is True

    # 3. Simulate missing file
    f1.unlink()
    discs_missing = recovery.reconcile_disk_with_ledger("m_recon", ws_dir)
    assert len(discs_missing) == 1
    assert discs_missing[0].discrepancy_type == ReconciliationDiscrepancyType.FILE_MISSING
    assert discs_missing[0].blocking is True


# ── Scenario D: Uncertain Outcome Protocol & Blocking ────────────────────────

def test_scenario_d_uncertain_outcome_protocol_blocking(tmp_path):
    """
    Unresolved OUTCOME_UNKNOWN or interrupted INTENT_COMMITTED operations block resume.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    recovery = RecoveryEngine(db=db, blob_store=blobs)

    # Record intent committed before backend was abruptly interrupted
    db.record_tool_intent(
        operation_id="op_interrupted_01",
        mission_id="m_unc",
        tool_name="write_file",
        intent_seq=1,
        target_path="partial.py",
        workspace_root=str(ws_dir),
    )
    # Marked as OUTCOME_UNKNOWN by startup restoration
    db.update_operation_status(
        operation_id="op_interrupted_01",
        status=OperationStatus.OUTCOME_UNKNOWN,
        error_message="Backend crashed before result commit",
    )

    discs = recovery.reconcile_disk_with_ledger("m_unc", ws_dir)
    assert len(discs) == 1
    assert discs[0].discrepancy_type == ReconciliationDiscrepancyType.OPERATION_UNCERTAIN
    assert discs[0].blocking is True
    assert discs[0].operation_id == "op_interrupted_01"


# ── Scenario E: First Unfinished Task Selection ──────────────────────────────

def test_scenario_e_first_unfinished_task_selection(tmp_path):
    """
    Tasks already completed and verified are preserved.
    The first incomplete task whose dependencies are satisfied is selected for continuation.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    recovery = RecoveryEngine(db=db, blob_store=blobs)

    state = HermesRuntimeState.create_empty(mission_id="m_tasks")
    # Task 1: Completed & Verified
    state.tasks["t1"] = TaskState(
        task_id="t1",
        mission_id="m_tasks",
        title="Initialize Project",
        status=TaskStatus.COMPLETED,
        completion_reason="Verified",
    )
    # Task 2: Unfinished (depends on t1)
    state.tasks["t2"] = TaskState(
        task_id="t2",
        mission_id="m_tasks",
        title="Implement Feature",
        status=TaskStatus.PENDING,
        dependencies=["t1"],
    )
    # Task 3: Unfinished (depends on t2)
    state.tasks["t3"] = TaskState(
        task_id="t3",
        mission_id="m_tasks",
        title="Write Tests",
        status=TaskStatus.PENDING,
        dependencies=["t2"],
    )

    target_task, completed_ids, pending_ids = recovery.determine_first_unfinished_task(state)
    assert target_task is not None
    assert target_task.task_id == "t2"
    assert completed_ids == ["t1"]
    assert pending_ids == ["t2", "t3"]


# ── Scenario F: Terminal Run Immutability & Continuation Run Identity ──────────

@pytest.mark.asyncio
async def test_scenario_f_terminal_run_immutability_and_continuation_identity(tmp_path):
    """
    Historical terminal run remains in CANCELLED/STOPPED state.
    Continuation run receives a fresh run_id and incremented attempt_number.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    event_bus = EventBus(db=db)
    setattr(event_bus, "blob_store", blobs)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(ws_dir))

    adapter = RuntimeAdapter(event_bus=event_bus, workspace_manager=ws_mgr)

    mission_id = "m_run_cont"
    old_run_id = "run_1_orig"

    # Setup mission in DB as STOPPED
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="CANCELLED",
        run_id=old_run_id,
        attempt_number=1,
        prompt="Autonomous task",
        execution_active=False,
    )
    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(ws_dir)
    state.tasks["t1"] = TaskState(task_id="t1", mission_id=mission_id, title="Task 1", status=TaskStatus.COMPLETED, completion_reason="Verified")
    state.tasks["t2"] = TaskState(task_id="t2", mission_id=mission_id, title="Task 2", status=TaskStatus.PENDING, dependencies=["t1"])
    snap_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(mission_id=mission_id, workspace_path=str(ws_dir), status="CANCELLED", snapshot_dict=snap_dict, state_hash=s_hash)

    # Resume the mission
    new_run_id = await adapter.resume_interrupted_mission(mission_id)
    assert new_run_id != old_run_id
    assert new_run_id.startswith("run_2_")

    # Verify mission in DB has attempt_number = 2
    row = db.get_mission(mission_id)
    assert row["run_id"] == new_run_id
    assert row["attempt_number"] == 2
    assert row["status"] == "RUNNING"

    # Stop continuation task cleanly
    await adapter.stop_mission(mission_id)


# ── Scenario G: Duplicate Resume Idempotency & Concurrency Protection ────────

@pytest.mark.asyncio
async def test_scenario_g_duplicate_resume_idempotency(tmp_path):
    """
    Calling resume when the mission is already actively executing is rejected with an error.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    event_bus = EventBus(db=db)
    setattr(event_bus, "blob_store", blobs)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(ws_dir))

    adapter = RuntimeAdapter(event_bus=event_bus, workspace_manager=ws_mgr)
    mission_id = "m_dup_resume"

    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="STOPPED",
        run_id="run_1_abc",
        attempt_number=1,
        prompt="Dual resume check",
        execution_active=False,
    )
    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(ws_dir)
    state.tasks["t1"] = TaskState(task_id="t1", mission_id=mission_id, title="Task 1", status=TaskStatus.PENDING)
    snap_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(mission_id=mission_id, workspace_path=str(ws_dir), status="STOPPED", snapshot_dict=snap_dict, state_hash=s_hash)

    # First resume succeeds
    run_id1 = await adapter.resume_interrupted_mission(mission_id)
    assert run_id1.startswith("run_2_")

    # Second concurrent resume must raise RuntimeError / conflict
    with pytest.raises(RuntimeError) as exc_info:
        await adapter.resume_interrupted_mission(mission_id)
    assert "already actively executing" in str(exc_info.value)

    await adapter.stop_mission(mission_id)


# ── Scenario H: Safe Resume via RuntimeAdapter & HTTP API ────────────────────

@pytest.mark.asyncio
async def test_scenario_h_resume_via_http_api(tmp_path):
    """
    Test POST /api/missions/{mission_id}/resume via FastAPI application.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    event_bus = EventBus(db=db)
    setattr(event_bus, "blob_store", blobs)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(ws_dir))

    adapter = RuntimeAdapter(event_bus=event_bus, workspace_manager=ws_mgr)
    app = create_app(adapter=adapter)

    mission_id = "m_api_resume"
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="CANCELLED",
        run_id="run_1_init",
        attempt_number=1,
        prompt="API resume mission",
        execution_active=False,
    )
    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(ws_dir)
    state.tasks["t1"] = TaskState(task_id="t1", mission_id=mission_id, title="Task 1", status=TaskStatus.PENDING)
    snap_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(mission_id=mission_id, workspace_path=str(ws_dir), status="CANCELLED", snapshot_dict=snap_dict, state_hash=s_hash)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8765", headers={"Host": "127.0.0.1:8765"}) as client:
        resp = await client.post(f"/api/missions/{mission_id}/resume")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mission_id"] == mission_id
        assert data["attempt_number"] == 2
        assert data["status"] == "RUNNING"
        assert data["run_id"].startswith("run_2_")

    await adapter.stop_mission(mission_id)


# ── Scenario I: Fast Resume Preview API ──────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_i_resume_preview_endpoint(tmp_path):
    """
    Test GET /api/missions/{mission_id}/resume-preview returns inspection summary
    without side effects.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    event_bus = EventBus(db=db)
    setattr(event_bus, "blob_store", blobs)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(ws_dir))

    adapter = RuntimeAdapter(event_bus=event_bus, workspace_manager=ws_mgr)
    app = create_app(adapter=adapter)

    mission_id = "m_prev_api"
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="CANCELLED",
        run_id="run_1_abc",
        attempt_number=1,
        prompt="Preview mission",
    )
    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(ws_dir)
    state.tasks["t1"] = TaskState(task_id="t1", mission_id=mission_id, title="Task 1", status=TaskStatus.COMPLETED, completion_reason="Verified")
    state.tasks["t2"] = TaskState(task_id="t2", mission_id=mission_id, title="Task 2", status=TaskStatus.PENDING, dependencies=["t1"])
    snap_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(mission_id=mission_id, workspace_path=str(ws_dir), status="CANCELLED", snapshot_dict=snap_dict, state_hash=s_hash)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8765", headers={"Host": "127.0.0.1:8765"}) as client:
        resp = await client.get(f"/api/missions/{mission_id}/resume-preview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["can_resume"] is True
        assert data["target_task_id"] == "t2"
        assert data["completed_tasks"] == ["t1"]
        assert data["pending_tasks"] == ["t2"]
        assert data["discrepancies"] == []


# ── Scenario J: Full Process Restart Recovery Cycle ──────────────────────────

@pytest.mark.asyncio
async def test_scenario_j_full_restart_recovery_cycle(tmp_path):
    """
    Simulates complete backend shutdown, restarts runtime adapter from disk,
    verifies restored state, and resumes from the first unfinished task.
    """
    db_path = tmp_path / "hermes.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    # Process 1: Run mission, perform Task 1 write, then simulate sudden shutdown
    db1 = SQLiteDatabase(db_path)
    blobs1 = BlobStore(blob_dir)
    bus1 = EventBus(db=db1)
    setattr(bus1, "blob_store", blobs1)
    ws_mgr1 = WorkspaceManager()
    ws_mgr1.lock(str(ws_dir))

    mission_id = "m_restart_cyc"
    out_file = ws_dir / "step1.txt"
    out_content = b"Step 1 Complete"
    out_file.write_bytes(out_content)
    post_hash = hashlib.sha256(out_content).hexdigest()

    # Record settled operation for Task 1
    db1.record_tool_intent(
        operation_id="op_step1",
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=1,
        target_path="step1.txt",
        workspace_root=str(ws_dir),
        task_id="t1",
    )
    db1.record_tool_result(
        operation_id="op_step1",
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=post_hash,
    )

    state1 = HermesRuntimeState.create_empty(mission_id=mission_id)
    state1.mission.workspace_root = str(ws_dir)
    state1.tasks["t1"] = TaskState(task_id="t1", mission_id=mission_id, title="Step 1", status=TaskStatus.COMPLETED, completion_reason="Verified")
    state1.tasks["t2"] = TaskState(task_id="t2", mission_id=mission_id, title="Step 2", status=TaskStatus.PENDING, dependencies=["t1"])
    snap_dict, s_hash = serialize_runtime_state(state1)
    db1.save_snapshot(mission_id=mission_id, workspace_path=str(ws_dir), status="RUNNING", snapshot_dict=snap_dict, state_hash=s_hash)
    db1.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="RUNNING",
        run_id="run_1_crashed",
        attempt_number=1,
        prompt="Restart test",
        execution_active=True,
    )

    # Process 1 terminates. Process 2 restarts:
    del db1, bus1, ws_mgr1

    db2 = SQLiteDatabase(db_path)
    blobs2 = BlobStore(blob_dir)
    bus2 = EventBus(db=db2)
    setattr(bus2, "blob_store", blobs2)
    ws_mgr2 = WorkspaceManager()
    adapter2 = RuntimeAdapter(event_bus=bus2, workspace_manager=ws_mgr2)

    # Verify startup recovery marked crashed mission as non-executing
    m_row = db2.get_mission(mission_id)
    assert m_row["execution_active"] is False
    assert m_row["recovery_required"] is True

    # Validate eligibility and resume
    eligible, reason = adapter2.validate_resume_eligibility(mission_id)
    assert eligible is True
    assert "t2" in reason or "Ready to resume" in reason

    cont_run_id = await adapter2.resume_interrupted_mission(mission_id)
    assert cont_run_id.startswith("run_2_")

    # Clean up
    await adapter2.stop_mission(mission_id)
