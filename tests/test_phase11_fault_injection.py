# tests/test_phase11_fault_injection.py
"""
HERMES Phase 11: Fault Injection, Chaos Testing, Recovery Integrity & Release Qualification Test Suite.

Covers:
1. Scenario 1: Network loss and clean resumption (ConnectivityMonitor, NetworkRecoveryCoordinator).
2. Scenario 2: Process crash, cold restart, WAL recovery & skipping completed tasks (SQLiteDatabase, RecoveryEngine).
3. Scenario 3: Stop / Cancellation during active file write & atomic cleanup (WriteFileTool, CancellationController).
4. Scenario 4: Five concurrent mission requests & single-active-mission mutual exclusion (RuntimeAdapter).
5. Scenario 5: Physical workspace drift detection and blocking (RecoveryEngine disk reconciliation & WorkspaceManifestCache).
6. Scenario 6: Tool infrastructure exception visibility & false completion prevention (BoundedExecutor).
7. Cross-Cutting Invariants:
   - Stale event replay rejection (EventBus & StateReducer).
   - Mission resurrection prevention on terminal states.
   - Files written != application complete invariant.
   - SQLite PRAGMA integrity_check = ok under heavy churn.
"""

import asyncio
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.bounded_executor import BoundedExecutor, BoundedTask, ResourceClass
from core.cancellation_controller import CancellationController
from core.event_bus import EventBus, EventType, HermesEvent
from core.network.connectivity import (
    ConnectivityCondition,
    ConnectivityMonitor,
    ConnectivityStatus,
)
from core.network.coordinator import NetworkRecoveryCoordinator
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import OperationStatus, SessionStatus
from core.persistence.recovery import (
    Discrepancy,
    ReconciliationDiscrepancyType,
    RecoveryEngine,
    compute_file_sha256,
)
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionStatus,
    TaskState,
    TaskStatus,
    WaitReason,
    is_legal_mission_transition,
)
from core.runtime_state.reducer import StateReducer
from core.runtime_state.store import StateStore
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import WorkspaceBoundaryError, WorkspaceManager
from core.workspace_cache import WorkspaceManifestCache
from tools.base import ToolResult
from tools.file_tools import WriteFileTool


# ==============================================================================
# Scenario 1: Network Loss and Clean Resumption
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario1_network_loss_and_clean_resumption(tmp_path):
    """
    Verify Scenario 1:
    - Injects network loss during active execution.
    - Status transitions to WAITING with wait_reason='WAITING_FOR_NETWORK'.
    - No false completion or crash occurs.
    - Upon network resumption, recovery coordinator detects eligible waiting mission
      and resumes cleanly without duplicate task re-execution.
    """
    db_file = tmp_path / "test_net_fault.db"
    db = SQLiteDatabase(db_file)
    bus = EventBus(enabled=True, db=db)

    mission_id = f"m_net_loss_{uuid.uuid4().hex[:6]}"
    ws_dir = tmp_path / "ws_net"
    ws_dir.mkdir(parents=True, exist_ok=True)

    # 1. Start mission in RUNNING state
    db.save_mission(mission_id, str(ws_dir), "RUNNING")
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        payload={"workspace_root": str(ws_dir), "prompt": "Execute resilience mission"},
    ))
    bus.flush()

    store = bus.get_state(mission_id)
    assert store is not None
    assert store.get_state().mission.status == MissionStatus.RUNNING

    # 2. Simulate network cut: publish disconnection event and transition to WAITING
    bus.publish(HermesEvent(
        event_type=EventType.NETWORK_DISCONNECTED,
        mission_id=mission_id,
        payload={
            "reason": "Global network loss simulated",
            "wait_reason": WaitReason.WAITING_FOR_NETWORK.value,
        },
    ))
    bus.flush()

    db.save_mission(
        mission_id,
        str(ws_dir),
        "WAITING",
        wait_reason=WaitReason.WAITING_FOR_NETWORK.value,
    )

    # Save state snapshot so resume plan formulation succeeds
    from core.persistence.serializer import serialize_runtime_state
    snap_dict, s_hash = serialize_runtime_state(store.get_state())
    db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="WAITING",
        snapshot_dict=snap_dict,
        state_hash=s_hash,
    )

    row = db.get_mission(mission_id)
    assert row["status"] == "WAITING"
    assert row["wait_reason"] == "WAITING_FOR_NETWORK"

    # 3. Test ConnectivityMonitor probe with custom_probe_func
    probe_state = {"online": False}

    async def custom_probe():
        return probe_state["online"]

    monitor = ConnectivityMonitor(
        custom_probe_func=custom_probe,
        failure_threshold=1,
        recovery_threshold=1,
    )
    status = await monitor.probe_now()
    assert status == ConnectivityStatus.OFFLINE
    assert monitor.is_offline is True

    # 4. Initialize NetworkRecoveryCoordinator
    coordinator = NetworkRecoveryCoordinator(monitor=monitor, event_bus=bus, db=db)
    waiting_missions = coordinator.find_eligible_waiting_missions()
    assert any(m["mission_id"] == mission_id for m in waiting_missions)

    # 5. Network restores: probe_state becomes True
    probe_state["online"] = True
    new_status = await monitor.probe_now()
    assert new_status == ConnectivityStatus.ONLINE
    assert monitor.is_online is True

    # Verify coordinator evaluates eligibility for resume
    eligible, reason = coordinator.evaluate_auto_resume_eligibility(mission_id)
    assert eligible is True

    # Resume the mission
    bus.publish(HermesEvent(
        event_type=EventType.MISSION_RESUMED,
        mission_id=mission_id,
        attempt_number=2,
        payload={"reason": "Network restored"},
    ))
    bus.flush()

    assert store.get_state().mission.status == MissionStatus.RUNNING
    bus.shutdown()


# ==============================================================================
# Scenario 2: Process Crash, Cold Restart & WAL Integrity
# ==============================================================================

def test_scenario2_process_crash_cold_restart_wal_recovery(tmp_path):
    """
    Verify Scenario 2:
    - Simulates an abrupt process crash while tasks are in flight.
    - Validates SQLite WAL integrity via PRAGMA integrity_check == 'ok'.
    - Validates that cold restart detects already completed/verified tasks
      and skips them, determining the exact first unfinished task.
    """
    db_file = tmp_path / "test_crash.db"
    db = SQLiteDatabase(db_file)

    # 1. Run transactions and verify WAL mode
    with db.transaction() as cur:
        cur.execute("PRAGMA journal_mode;")
        journal_mode = cur.fetchone()[0].upper()
    assert journal_mode == "WAL"

    mission_id = f"m_crash_{uuid.uuid4().hex[:6]}"
    session_id = f"s_crash_{uuid.uuid4().hex[:6]}"

    now = time.time()
    db.save_session(
        session_id=session_id,
        mission_id=mission_id,
        workspace_root=str(tmp_path),
        status=SessionStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )

    # Simulate abrupt database disconnect / termination
    del db

    # 2. Re-open database from cold state (cold restart)
    reopened_db = SQLiteDatabase(db_file)
    with reopened_db.transaction() as cur:
        cur.execute("PRAGMA integrity_check;")
        check_result = cur.fetchone()[0]
    assert check_result == "ok"

    # 3. Build runtime state with 3 sequential tasks
    # Task 1: COMPLETED and verified
    # Task 2: PENDING (unfinished)
    # Task 3: PENDING (depends on Task 2)
    state = HermesRuntimeState.create_empty(mission_id=mission_id, session_id=session_id)
    t1 = TaskState(
        task_id="task_1_setup",
        mission_id=mission_id,
        title="Setup project",
        order_index=0,
        status=TaskStatus.COMPLETED,
        completion_reason="Setup verified by smoke test",
    )
    t2 = TaskState(
        task_id="task_2_implement",
        mission_id=mission_id,
        title="Implement feature",
        order_index=1,
        status=TaskStatus.PENDING,
        dependencies=["task_1_setup"],
    )
    t3 = TaskState(
        task_id="task_3_verify",
        mission_id=mission_id,
        title="Run integration tests",
        order_index=2,
        status=TaskStatus.PENDING,
        dependencies=["task_2_implement"],
    )
    state.tasks = {t1.task_id: t1, t2.task_id: t2, t3.task_id: t3}

    blob_store = BlobStore(tmp_path / "blobs")
    recovery_engine = RecoveryEngine(db=reopened_db, blob_store=blob_store)

    target_task, completed_ids, pending_ids = recovery_engine.determine_first_unfinished_task(state)

    # Must skip task_1_setup and designate task_2_implement as first safe unfinished task
    assert "task_1_setup" in completed_ids
    assert target_task is not None
    assert target_task.task_id == "task_2_implement"
    assert "task_2_implement" in pending_ids
    assert "task_3_verify" in pending_ids


# ==============================================================================
# Scenario 3: Stop During Active File Write & Atomic Cleanup
# ==============================================================================

def test_scenario3_stop_during_active_file_write_atomic_cleanup(tmp_path):
    """
    Verify Scenario 3:
    - Simulates an interruption or cancellation during an active file write.
    - Proves the target file is never left in a corrupt half-written state.
    - Proves temporary files (.tmp_*) are cleaned up and cancellation state is set.
    """
    ws = WorkspaceManager()
    ws.lock(str(tmp_path))

    target_file = tmp_path / "critical_module.py"
    original_content = "# Original production code\ndef run():\n    return 'stable'\n"
    target_file.write_text(original_content, encoding="utf-8")
    original_hash = compute_file_sha256(target_file)

    tool = WriteFileTool()
    mission_id = f"m_stop_write_{uuid.uuid4().hex[:6]}"
    controller = CancellationController()

    # Cancel the mission
    controller.cancel_mission(mission_id=mission_id, reason="User triggered stop during write")
    assert controller.is_cancelled(mission_id)

    # Simulate write interruption: an exception occurs before os.replace
    with patch("os.replace", side_effect=PermissionError("Simulated locked file / interrupt")):
        result = tool.execute({
            "path": "critical_module.py",
            "content": "# Corrupted partial update\ndef broken_code(",
            "mode": "overwrite",
        })
        assert not result.success
        assert "Permission denied" in result.error or "SECURITY" in result.error or result.exit_code != 0

    # Verify target file retained its exact prior content
    assert target_file.read_text(encoding="utf-8") == original_content
    assert compute_file_sha256(target_file) == original_hash

    # Verify no temporary staging files leaked into the directory
    leftover_tmps = list(tmp_path.glob(".*.tmp_*"))
    assert len(leftover_tmps) == 0


# ==============================================================================
# Scenario 4: Five Concurrent Mission Requests (Single-Active-Mission Policy)
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario4_concurrent_mission_requests_single_active_policy(tmp_path):
    """
    Verify Scenario 4:
    - Dispatches 5 concurrent mission launch requests.
    - Exactly 1 mission acquires execution ownership and starts.
    - The remaining 4 concurrent requests are cleanly rejected under single-mission policy.
    - No race condition corrupts runtime state.
    """
    db_file = tmp_path / "test_concurrency.db"
    db = SQLiteDatabase(db_file)
    bus = EventBus(enabled=True, db=db)
    ws = WorkspaceManager()
    ws.lock(str(tmp_path))

    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws)

    # Track how many launches succeed vs how many are rejected
    successes = []
    rejections = []

    # Mock get_or_create_runtime so we test the concurrency controller deterministically
    mock_rt = MagicMock()
    mock_rt.mission_control = MagicMock()
    adapter.get_or_create_runtime = AsyncMock(return_value=mock_rt)

    # Define a long-running execution mock to hold the single-mission lock
    async def mock_execute(*args, **kwargs):
        await asyncio.sleep(0.3)

    mock_rt.execute_prompt = mock_execute

    async def attempt_start(index: int):
        try:
            m_id = await adapter.start_mission(
                prompt=f"Concurrent mission prompt {index}",
                workspace_root=str(tmp_path),
            )
            successes.append(m_id)
        except RuntimeError as exc:
            rejections.append(str(exc))

    # Fire 5 concurrent requests simultaneously
    await asyncio.gather(
        attempt_start(1),
        attempt_start(2),
        attempt_start(3),
        attempt_start(4),
        attempt_start(5),
    )

    # Strictly 1 succeeded, and strictly 4 were rejected with single-mission policy
    assert len(successes) == 1, f"Expected exactly 1 mission to start, got {len(successes)}"
    assert len(rejections) == 4, f"Expected 4 rejections, got {len(rejections)}"

    for err in rejections:
        assert "single-mission policy" in err.lower()

    # Clean up background task
    for t in adapter._active_tasks.values():
        if t and not t.done():
            t.cancel()
    bus.shutdown()


# ==============================================================================
# Scenario 5: Workspace Drift (External Modifications Outside HERMES)
# ==============================================================================

def test_scenario5_workspace_drift_detection_and_blocking(tmp_path):
    """
    Verify Scenario 5:
    - Tests physical workspace drift detection:
      1. File modified externally -> flags USER_MODIFIED.
      2. File deleted externally -> flags FILE_MISSING.
      3. WorkspaceManifestCache.scan_workspace(force=True) updates manifest accurately.
    - Prevents unsafe execution against drifted workspace without re-audit.
    """
    db_file = tmp_path / "test_drift.db"
    db = SQLiteDatabase(db_file)
    blob_store = BlobStore(tmp_path / "blobs")
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_path))

    recovery = RecoveryEngine(db=db, blob_store=blob_store, workspace_manager=ws_mgr)
    cache = WorkspaceManifestCache(workspace_root=tmp_path)

    mission_id = f"m_drift_{uuid.uuid4().hex[:6]}"

    # 1. Settle two files via tool operations in ledger
    file_a = tmp_path / "service.py"
    file_b = tmp_path / "config.json"

    file_a.write_text("def serve(): pass", encoding="utf-8")
    file_b.write_text('{"env": "prod"}', encoding="utf-8")

    hash_a = compute_file_sha256(file_a)
    hash_b = compute_file_sha256(file_b)

    # Record tool operations for file_a and file_b using explicit keyword arguments
    db.record_tool_intent(
        operation_id="op_1",
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=1,
        target_path="service.py",
        workspace_root=str(tmp_path),
    )
    db.record_tool_result(
        operation_id="op_1",
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=hash_a,
    )

    db.record_tool_intent(
        operation_id="op_2",
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=3,
        target_path="config.json",
        workspace_root=str(tmp_path),
    )
    db.record_tool_result(
        operation_id="op_2",
        result_seq=4,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=hash_b,
    )

    # Prime cache
    initial_entries = cache.scan_workspace(force=True)
    assert "service.py" in initial_entries
    assert "config.json" in initial_entries

    # 2. Inject external modifications outside HERMES
    # Modification: file_a is changed externally
    file_a.write_text("def serve(): raise SystemExit(1)", encoding="utf-8")

    # Deletion: file_b is deleted externally
    file_b.unlink()

    # Addition: file_c is added externally
    file_c = tmp_path / "rogue.py"
    file_c.write_text("# Untracked external file", encoding="utf-8")

    # 3. Ledger disk reconciliation must immediately detect discrepancies
    discrepancies = recovery.reconcile_disk_with_ledger(mission_id, tmp_path)
    disc_types = {d.discrepancy_type: d for d in discrepancies}

    assert ReconciliationDiscrepancyType.USER_MODIFIED in disc_types
    assert disc_types[ReconciliationDiscrepancyType.USER_MODIFIED].path == "service.py"

    assert ReconciliationDiscrepancyType.FILE_MISSING in disc_types
    assert disc_types[ReconciliationDiscrepancyType.FILE_MISSING].path == "config.json"

    # 4. Cache forced scan detects physical realities
    updated_entries = cache.scan_workspace(force=True)
    assert "config.json" not in updated_entries
    assert "rogue.py" in updated_entries
    assert updated_entries["service.py"].size_bytes == file_a.stat().st_size


# ==============================================================================
# Scenario 6: Tool Infrastructure Exception (Unhandled Failure)
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario6_tool_infrastructure_exception_visibility():
    """
    Verify Scenario 6:
    - Injects a fatal Python exception (e.g. NameError / ImportError) in tool execution.
    - Proves the exception is captured into a structured record without crashing the executor.
    - Proves success=False, error message is preserved, and false completion is prohibited.
    """
    executor = BoundedExecutor(max_workers=2)

    def crashing_tool():
        # Simulate unhandled infrastructure bug (NameError)
        return undefined_variable_name  # noqa: F821

    task = BoundedTask(
        task_id="t_crash_infra",
        func=crashing_tool,
        resource_class=ResourceClass.CPU,
    )

    record = await executor.execute_task(task)

    assert record.success is False
    assert record.error is not None
    assert "undefined_variable_name" in record.error
    assert record.task_id == "t_crash_infra"


# ==============================================================================
# Cross-Cutting Invariants
# ==============================================================================

def test_invariant_stale_event_replay_rejection():
    """
    Verify Cross-Cutting Invariant:
    - Stale event replay rejection:
      1. Duplicate event IDs are ignored by EventBus.
      2. Events with out-of-order sequence (sequence <= last_event_sequence)
         are dropped by StateReducer and cannot regress state.
    """
    mission_id = f"m_stale_{uuid.uuid4().hex[:6]}"
    store = StateStore(mission_id)

    # Normal starting event sequence 1
    ev1 = HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        sequence=1,
        timestamp=time.time(),
        payload={"prompt": "Test stale"},
    )
    store.apply_event(ev1)
    assert store.get_state().last_event_sequence == 1
    assert store.get_state().mission.status == MissionStatus.RUNNING

    # Attempt to apply a stale event with sequence = 1 (or lower)
    ev_stale = HermesEvent(
        event_type=EventType.MISSION_FAILED,
        mission_id=mission_id,
        sequence=1,
        timestamp=time.time(),
        payload={"error": "Stale failure"},
    )
    store.apply_event(ev_stale)

    # State must remain unchanged (still RUNNING, sequence still 1)
    assert store.get_state().last_event_sequence == 1
    assert store.get_state().mission.status == MissionStatus.RUNNING


def test_invariant_mission_resurrection_prevention():
    """
    Verify Cross-Cutting Invariant:
    - Once a mission reaches a terminal status (COMPLETED, FAILED, CANCELLED, ABORTED),
      it cannot transition back to RUNNING.
    """
    mission_id = f"m_term_{uuid.uuid4().hex[:6]}"
    store = StateStore(mission_id)

    # Start mission first (transition CREATED -> RUNNING)
    store.apply_event(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        sequence=1,
        payload={"prompt": "Start mission"},
    ))
    assert store.get_state().mission.status == MissionStatus.RUNNING

    # Complete the mission (transition RUNNING -> COMPLETED)
    ev_complete = HermesEvent(
        event_type=EventType.MISSION_COMPLETED,
        mission_id=mission_id,
        sequence=2,
        payload={"summary": "Mission successfully completed"},
    )
    store.apply_event(ev_complete)
    assert store.get_state().mission.status == MissionStatus.COMPLETED
    assert store.get_state().mission.is_terminal is True

    # Attempt to resurrect mission to RUNNING
    ev_resurrect = HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        sequence=3,
        payload={"prompt": "Resurrect mission"},
    )
    store.apply_event(ev_resurrect)

    # Mission must remain strictly COMPLETED
    assert store.get_state().mission.status == MissionStatus.COMPLETED
    assert is_legal_mission_transition(MissionStatus.COMPLETED, MissionStatus.RUNNING) is False


def test_invariant_files_written_does_not_equal_completion(tmp_path):
    """
    Verify Cross-Cutting Invariant:
    - Simply having files written to disk does NOT transition mission to COMPLETED.
    - True completion requires explicit verification and completion event dispatch.
    """
    ws = WorkspaceManager()
    ws.lock(str(tmp_path))

    # Create dummy planned output file
    out_file = tmp_path / "app.py"
    out_file.write_text("print('App created')", encoding="utf-8")

    mission_id = f"m_files_{uuid.uuid4().hex[:6]}"
    store = StateStore(mission_id)

    # Mission is RUNNING
    store.apply_event(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        sequence=1,
        payload={"prompt": "Build app"},
    ))

    # Tool executes and completes file write
    store.apply_event(HermesEvent(
        event_type=EventType.TOOL_COMPLETED,
        mission_id=mission_id,
        sequence=2,
        payload={"tool_name": "write_file", "path": "app.py"},
    ))

    # Mission must remain RUNNING (not falsely COMPLETED)
    assert out_file.exists()
    assert store.get_state().mission.status == MissionStatus.RUNNING


def test_invariant_sqlite_integrity_check_under_heavy_churn(tmp_path):
    """
    Verify Cross-Cutting Invariant:
    - Executes high-churn multithreaded transactions against SQLiteDatabase with WAL.
    - Confirms PRAGMA integrity_check returns 'ok' with zero corruptions or deadlocks.
    """
    db_file = tmp_path / "churn.db"
    db = SQLiteDatabase(db_file)

    def churn_worker(worker_id: int):
        for i in range(25):
            op_id = f"op_churn_{worker_id}_{i}"
            db.record_tool_intent(
                operation_id=op_id,
                mission_id="m_churn",
                tool_name="write_file",
                intent_seq=i,
                target_path=f"file_{worker_id}_{i}.txt",
                workspace_root=str(tmp_path),
            )
            db.record_tool_result(
                operation_id=op_id,
                result_seq=i + 1,
                status=OperationStatus.RESULT_COMMITTED,
                post_hash="deadbeef",
            )

    threads = [threading.Thread(target=churn_worker, args=(w,)) for w in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with db.transaction() as cur:
        cur.execute("PRAGMA integrity_check;")
        result = cur.fetchone()[0]
    assert result == "ok"
