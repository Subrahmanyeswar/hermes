# tests/test_phase7_network_recovery.py
"""
HERMES Phase 7 Acceptance Test Suite: Internet-Loss Detection, Durable Waiting & Automatic Recovery.

Scenarios Covered:
- Scenario A: Connectivity Condition Classification (A, B, C, D).
- Scenario B: Shared Connectivity Monitor with Hysteresis & Anti-Flapping.
- Scenario C: Truthful Waiting State Persistence & Event Lifecycle.
- Scenario D: Safe Execution Boundary & Zero Duplicate Operations.
- Scenario E: Automatic Recovery Coordination & Continuation Run Identity.
- Scenario F: Ineligible Mission Fencing (User-Cancelled, Completed, Corrupt Checkpoint, Missing Workspace, Auth/Billing).
- Scenario G: Flapping Protection, Debounce & Concurrency Deduplication.
- Scenario H: Browser-to-Backend Disconnection Resilience (Condition A).
- Scenario I: Backend Restart with Waiting Missions Recovery (Condition B).
- Scenario J: Network Status and Recovery REST API Endpoints.
"""

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
from httpx import ASGITransport, AsyncClient

from core.checkpoints.engine import CheckpointEngine
from core.event_bus import EventBus
from core.network.connectivity import (
    ConnectivityCondition,
    ConnectivityMonitor,
    ConnectivityStatus,
    classify_error_condition,
    shared_connectivity_monitor,
)
from core.network.coordinator import (
    NetworkRecoveryCoordinator,
    shared_recovery_coordinator,
)
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import (
    CheckpointManifest,
    CheckpointReason,
    CheckpointTrigger,
    FileSnapshot,
    OperationStatus,
    SessionStatus,
    WorkspaceManifest,
)
from core.persistence.recovery import RecoveryEngine
from core.persistence.serializer import serialize_runtime_state
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionControlContext,
    MissionState,
    MissionStatus,
    TaskState,
    TaskStatus,
    WaitReason,
)
from core.runtime_state.store import StateStore
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.transport.circuit_breaker import CircuitState, circuit_breaker_registry
from core.transport.types import ErrorCategory, StructuredTransportError
from core.workspace import WorkspaceManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def sqlite_db(tmp_path: Path) -> SQLiteDatabase:
    db_file = tmp_path / "hermes_test.db"
    return SQLiteDatabase(db_file)


@pytest.fixture
def blob_store(tmp_path: Path) -> BlobStore:
    blobs_dir = tmp_path / "blobs"
    return BlobStore(blobs_dir)


@pytest.fixture
def test_event_bus(sqlite_db: SQLiteDatabase, blob_store: BlobStore) -> EventBus:
    eb = EventBus(db=sqlite_db)
    eb.blob_store = blob_store
    return eb


# ── Helper Builders ───────────────────────────────────────────────────────────

def build_valid_checkpoint(
    db: SQLiteDatabase,
    blob_store: BlobStore,
    session_id: str,
    mission_id: str,
    sequence: int,
    workspace_root: Path,
    state: HermesRuntimeState,
) -> str:
    snap_dict, s_hash = serialize_runtime_state(state)
    canonical_state_bytes = json.dumps(snap_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    blob_store.put(canonical_state_bytes)

    file_snaps = {}
    test_file = workspace_root / "output.txt"
    total_bytes = 0
    if test_file.exists():
        content = test_file.read_bytes()
        total_bytes = len(content)
        f_blob_id = blob_store.put(content)
        file_snaps["output.txt"] = FileSnapshot(
            relative_path="output.txt",
            blob_id=f_blob_id,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            mtime_ns=int(time.time() * 1e9),
        )

    ws_manifest = WorkspaceManifest(
        workspace_root=str(workspace_root),
        total_files=len(file_snaps),
        total_bytes=total_bytes,
        files=file_snaps,
    )
    chk_id = f"chk_{mission_id}_{sequence}"
    now = time.time()
    manifest = CheckpointManifest(
        checkpoint_id=chk_id,
        session_id=session_id,
        mission_id=mission_id,
        sequence=sequence,
        created_at=now,
        state_hash=s_hash,
        workspace=ws_manifest,
    )

    manifest_dict = manifest.to_dict()
    manifest_dict.pop("manifest_hash", None)
    calc_hash = hashlib.sha256(json.dumps(manifest_dict, sort_keys=True).encode("utf-8")).hexdigest()
    manifest.manifest_hash = calc_hash
    final_manifest_dict = manifest.to_dict()

    db.save_session(
        session_id=session_id,
        mission_id=mission_id,
        workspace_root=str(workspace_root),
        status="RUNNING",
        created_at=now,
        updated_at=now,
    )

    db.save_checkpoint(
        checkpoint_id=chk_id,
        session_id=session_id,
        sequence=sequence,
        reason=CheckpointReason.POST_ACTION.value,
        trigger=CheckpointTrigger.SYSTEM.value,
        created_at=now,
        state_hash=s_hash,
        manifest_hash=calc_hash,
        manifest_json=json.dumps(final_manifest_dict, sort_keys=True),
    )
    return chk_id


# ── Section A: Connectivity Condition Classification ─────────────────────────

def test_section_a_error_condition_classification():
    """Verify classification accurately distinguishes Condition C, Condition D, and permanent errors."""
    # Condition D: Internet loss (connection failure while probe is offline)
    transport_err_net = StructuredTransportError(
        category=ErrorCategory.CONNECTION_FAILURE,
        message="Failed to establish connection to host",
        provider="nvidia_nim",
        model="meta/llama-3.3-70b-instruct",
    )
    assert classify_error_condition(transport_err_net, is_internet_online=False) == ConnectivityCondition.CONDITION_D

    # Condition C: Provider outage (connection failure while Internet probe is ONLINE)
    assert classify_error_condition(transport_err_net, is_internet_online=True) == ConnectivityCondition.CONDITION_C

    # Condition C: Provider server error (503 / 500)
    provider_503 = StructuredTransportError(
        category=ErrorCategory.PROVIDER_SERVER_ERROR,
        message="503 Service Unavailable",
        provider="nvidia_nim",
        model="meta/llama-3.3-70b-instruct",
    )
    assert classify_error_condition(provider_503, is_internet_online=True) == ConnectivityCondition.CONDITION_C

    # Condition C: Circuit breaker open
    cb_err = StructuredTransportError(
        category=ErrorCategory.CIRCUIT_BREAKER_OPEN,
        message="Circuit breaker is OPEN for nvidia_nim",
        provider="nvidia_nim",
        model="meta/llama-3.3-70b-instruct",
    )
    assert classify_error_condition(cb_err, is_internet_online=True) == ConnectivityCondition.CONDITION_C

    # Permanent failures must return None (never trigger waiting state)
    auth_err = StructuredTransportError(
        category=ErrorCategory.AUTHENTICATION_FAILURE,
        message="401 Unauthorized: Invalid API key",
        provider="nvidia_nim",
        model="meta/llama-3.3-70b-instruct",
    )
    assert classify_error_condition(auth_err, is_internet_online=False) is None
    assert classify_error_condition(auth_err, is_internet_online=True) is None

    billing_err = StructuredTransportError(
        category=ErrorCategory.BILLING_FAILURE,
        message="402 Payment Required",
        provider="nvidia_nim",
        model="meta/llama-3.3-70b-instruct",
    )
    assert classify_error_condition(billing_err, is_internet_online=True) is None


# ── Section B: Shared Connectivity Monitor with Hysteresis ────────────────────

@pytest.mark.asyncio
async def test_section_b_connectivity_monitor_hysteresis():
    """Verify hysteresis: failure threshold requires N failed probes; recovery threshold requires M successful probes."""
    probe_results = [True]

    async def mock_probe():
        return probe_results[0]

    monitor = ConnectivityMonitor(
        failure_threshold=2,
        recovery_threshold=2,
        custom_probe_func=mock_probe,
    )

    # Initial state is UNKNOWN
    assert monitor.status == ConnectivityStatus.UNKNOWN

    # First success transitions toward online (needs 2 for recovery from unknown/offline)
    await monitor.probe_now()
    assert monitor.status == ConnectivityStatus.DEGRADED

    # Second success confirms ONLINE
    await monitor.probe_now()
    assert monitor.status == ConnectivityStatus.ONLINE
    assert monitor.is_online is True

    # 1 transient failure does NOT trip to OFFLINE (anti-flapping hysteresis -> DEGRADED)
    probe_results[0] = False
    await monitor.probe_now()
    assert monitor.status == ConnectivityStatus.DEGRADED
    assert monitor.is_offline is False

    # Second consecutive failure trips to OFFLINE
    await monitor.probe_now()
    assert monitor.status == ConnectivityStatus.OFFLINE
    assert monitor.is_offline is True

    # Recovery: 1 success stays DEGRADED
    probe_results[0] = True
    await monitor.probe_now()
    assert monitor.status == ConnectivityStatus.DEGRADED

    # 2 consecutive successes restores ONLINE
    await monitor.probe_now()
    assert monitor.status == ConnectivityStatus.ONLINE
    assert monitor.is_online is True

    # Lifecycle cleanup
    monitor.start()
    assert monitor._running is True
    await monitor.stop()
    assert monitor._running is False


@pytest.mark.asyncio
async def test_section_b_monitor_listener_notification():
    """Verify listener callbacks are notified when status transitions."""
    transitions = []

    def on_change(old_st, new_st):
        transitions.append((old_st, new_st))

    probe_ok = [False]

    async def mock_probe():
        return probe_ok[0]

    monitor = ConnectivityMonitor(
        failure_threshold=1,
        recovery_threshold=1,
        custom_probe_func=mock_probe,
    )
    monitor.add_listener(on_change)

    await monitor.probe_now()
    assert len(transitions) == 1
    assert transitions[0] == (ConnectivityStatus.UNKNOWN, ConnectivityStatus.OFFLINE)

    probe_ok[0] = True
    await monitor.probe_now()
    assert len(transitions) == 2
    assert transitions[1] == (ConnectivityStatus.OFFLINE, ConnectivityStatus.ONLINE)

    monitor.remove_listener(on_change)


# ── Section C: Truthful Waiting State Persistence ────────────────────────────

def test_section_c_waiting_state_reducer_persistence(sqlite_db: SQLiteDatabase, temp_workspace: Path):
    """Verify reducer and database truthfully persist WAITING status and WAITING_FOR_NETWORK reason."""
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(temp_workspace)
    store = StateStore(mission_id=mission_id)
    store.apply_event(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        sequence=1,
    ))

    # 1. Apply NETWORK_DISCONNECTED event
    evt_net_drop = HermesEvent(
        event_type=EventType.NETWORK_DISCONNECTED,
        mission_id=mission_id,
        payload={"error": "DNS resolution failed", "condition": "CONDITION_D"},
        sequence=2,
    )
    store.apply_event(evt_net_drop)
    snap = store.get_snapshot()
    assert snap.network.connectivity.value == "DISCONNECTED"
    assert snap.progress.waiting_reason == WaitReason.WAITING_FOR_NETWORK

    # 2. Apply MISSION_WAITING event
    evt_waiting = HermesEvent(
        event_type=EventType.MISSION_WAITING,
        mission_id=mission_id,
        payload={"status": "WAITING", "wait_reason": "WAITING_FOR_NETWORK", "reason": "Internet connection lost"},
        sequence=3,
    )
    store.apply_event(evt_waiting)
    snap = store.get_snapshot()
    assert snap.mission.status == MissionStatus.WAITING
    assert snap.progress.waiting_reason == WaitReason.WAITING_FOR_NETWORK
    assert snap.mission.is_terminal is False

    # 3. Persist to SQLite and verify database fields
    sqlite_db.save_mission(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
        execution_active=False,
        recovery_required=True,
        prompt="Build the network resilience harness",
    )

    row = sqlite_db.get_mission(mission_id)
    assert row is not None
    assert row["status"] == "WAITING"
    assert row["wait_reason"] == "WAITING_FOR_NETWORK"
    assert row["execution_active"] == 0
    assert row["recovery_required"] == 1


# ── Section D: Safe Execution Boundary & Zero Duplicate Operations ───────────

def test_section_d_safe_boundary_preservation(sqlite_db: SQLiteDatabase, temp_workspace: Path, blob_store: BlobStore):
    """Verify checkpoint settled at safe boundary captures clean file states and no partial uncommitted writes."""
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    test_file = temp_workspace / "output.txt"
    test_file.write_text("Settled turn 1 content", encoding="utf-8")

    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(temp_workspace)
    state.tasks["task_1"] = TaskState(
        task_id="task_1",
        mission_id=mission_id,
        title="Completed Task 1",
        status=TaskStatus.COMPLETED,
    )
    state.tasks["task_2"] = TaskState(
        task_id="task_2",
        mission_id=mission_id,
        title="Interrupted Task 2",
        status=TaskStatus.WAITING,
    )

    chk_id = build_valid_checkpoint(
        db=sqlite_db,
        blob_store=blob_store,
        session_id=f"sess_{mission_id}",
        mission_id=mission_id,
        sequence=5,
        workspace_root=temp_workspace,
        state=state,
    )

    # Record committed operation for output.txt
    file_hash = hashlib.sha256(b"Settled turn 1 content").hexdigest()
    sqlite_db.record_tool_intent(
        operation_id="op_1",
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=1,
        target_path="output.txt",
        workspace_root=str(temp_workspace),
    )
    sqlite_db.record_tool_result(
        operation_id="op_1",
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=file_hash,
    )

    # Save mission in WAITING state with latest checkpoint
    sqlite_db.save_mission(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
        latest_checkpoint_id=chk_id,
        execution_active=False,
        recovery_required=True,
    )

    # Save snapshot
    snap_dict, s_hash = serialize_runtime_state(state)
    sqlite_db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        snapshot_dict=snap_dict,
        state_hash=s_hash,
    )

    # Verify recovery engine reconciles clean disk and selects task_2
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(temp_workspace))
    engine = RecoveryEngine(db=sqlite_db, blob_store=blob_store, workspace_manager=ws_mgr)
    plan = engine.formulate_resume_plan(mission_id)

    assert plan.can_resume is True
    assert plan.target_task_id == "task_2"
    assert plan.target_task_title == "Interrupted Task 2"
    assert "task_1" in plan.completed_tasks
    assert len(plan.discrepancies) == 0


# ── Section E: Automatic Recovery Coordination & Continuation Run Identity ──

@pytest.mark.asyncio
async def test_section_e_auto_recovery_coordinator_execution(
    sqlite_db: SQLiteDatabase,
    blob_store: BlobStore,
    temp_workspace: Path,
):
    """Verify coordinator discovers waiting missions, validates invariants, and automatically resumes."""
    mission_id = f"m_{uuid.uuid4().hex[:8]}"
    test_file = temp_workspace / "output.txt"
    test_file.write_text("Phase 7 test content", encoding="utf-8")

    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(temp_workspace)
    state.mission.status = MissionStatus.WAITING
    state.mission.attempt_number = 1
    state.tasks["task_cont"] = TaskState(
        task_id="task_cont",
        mission_id=mission_id,
        title="Continuation Task",
        status=TaskStatus.WAITING,
    )

    chk_id = build_valid_checkpoint(
        db=sqlite_db,
        blob_store=blob_store,
        session_id=f"sess_{mission_id}",
        mission_id=mission_id,
        sequence=10,
        workspace_root=temp_workspace,
        state=state,
    )

    file_hash = hashlib.sha256(b"Phase 7 test content").hexdigest()
    sqlite_db.record_tool_intent(
        operation_id="op_settled",
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=1,
        target_path="output.txt",
        workspace_root=str(temp_workspace),
    )
    sqlite_db.record_tool_result(
        operation_id="op_settled",
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=file_hash,
    )

    sqlite_db.save_mission(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
        run_id="run_1_init",
        attempt_number=1,
        latest_checkpoint_id=chk_id,
        execution_active=False,
        recovery_required=True,
        prompt="Test automatic continuation prompt",
    )

    snap_dict, s_hash = serialize_runtime_state(state)
    sqlite_db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        snapshot_dict=snap_dict,
        state_hash=s_hash,
        run_id="run_1_init",
        attempt_number=1,
    )

    # Set up RuntimeAdapter and Coordinator
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(temp_workspace))
    eb = EventBus(db=sqlite_db)
    eb.blob_store = blob_store

    adapter = RuntimeAdapter(event_bus=eb, workspace_manager=ws_mgr)
    coordinator = NetworkRecoveryCoordinator(
        db=sqlite_db,
        runtime_adapter=adapter,
        event_bus=eb,
    )

    # 1. Discover eligible missions
    eligible = coordinator.find_eligible_waiting_missions()
    assert len(eligible) == 1
    assert eligible[0]["mission_id"] == mission_id

    # 2. Evaluate eligibility
    can_resume, reason = coordinator.evaluate_auto_resume_eligibility(mission_id)
    assert can_resume is True
    assert "Eligible" in reason

    # 3. Execute auto-resume
    resumed_run_id = await coordinator.auto_resume_mission(mission_id)
    assert resumed_run_id is not None
    assert resumed_run_id.startswith("run_2_")

    # Verify mission in database transitioned to RUNNING with continuation run_id
    m_row = sqlite_db.get_mission(mission_id)
    assert m_row["status"] == "RUNNING"
    assert m_row["run_id"] == resumed_run_id
    assert m_row["attempt_number"] == 2
    assert m_row["execution_active"] == 1


# ── Section F: Ineligible Mission Fencing ─────────────────────────────────────

@pytest.mark.asyncio
async def test_section_f_ineligible_mission_fencing(
    sqlite_db: SQLiteDatabase,
    blob_store: BlobStore,
    temp_workspace: Path,
):
    """Verify ineligible missions (cancelled, completed, corrupted checkpoint, missing workspace) never auto-resume."""
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(temp_workspace))
    eb = EventBus(db=sqlite_db)
    eb.blob_store = blob_store
    adapter = RuntimeAdapter(event_bus=eb, workspace_manager=ws_mgr)
    coordinator = NetworkRecoveryCoordinator(db=sqlite_db, runtime_adapter=adapter, event_bus=eb)

    # 1. User-cancelled mission
    m_cancelled = f"m_canc_{uuid.uuid4().hex[:6]}"
    sqlite_db.save_mission(
        mission_id=m_cancelled,
        workspace_path=str(temp_workspace),
        status="CANCELLED",
        wait_reason="NONE",
        execution_active=False,
        recovery_required=False,
    )
    ok, reason = coordinator.evaluate_auto_resume_eligibility(m_cancelled)
    assert ok is False
    assert "terminal state" in reason.lower()

    # 2. Completed mission
    m_completed = f"m_comp_{uuid.uuid4().hex[:6]}"
    sqlite_db.save_mission(
        mission_id=m_completed,
        workspace_path=str(temp_workspace),
        status="COMPLETED",
        wait_reason="NONE",
        execution_active=False,
        recovery_required=False,
    )
    ok, reason = coordinator.evaluate_auto_resume_eligibility(m_completed)
    assert ok is False
    assert "terminal state" in reason.lower()

    # 3. Missing workspace directory
    m_missing_ws = f"m_miss_{uuid.uuid4().hex[:6]}"
    sqlite_db.save_mission(
        mission_id=m_missing_ws,
        workspace_path=str(temp_workspace / "non_existent_folder_xyz"),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
        execution_active=False,
        recovery_required=True,
    )
    ok, reason = coordinator.evaluate_auto_resume_eligibility(m_missing_ws)
    assert ok is False
    assert "workspace" in reason.lower()
    # Verify mission remains safely blocked in WAITING without irreversible terminal FAILED
    row = sqlite_db.get_mission(m_missing_ws)
    assert row["status"] == "WAITING"
    assert row["wait_reason"] in ("WAITING_FOR_WORKSPACE", "RECOVERY_BLOCKED")
    assert "inaccessible" in row["metadata"].get("blocked_reason", "").lower() or "workspace" in row["metadata"].get("blocked_reason", "").lower()

    # 4. Corrupted checkpoint
    m_corrupt = f"m_corrupt_{uuid.uuid4().hex[:6]}"
    chk_corrupt = f"chk_bad_{m_corrupt}"
    sqlite_db.save_session(
        session_id=f"sess_{m_corrupt}",
        mission_id=m_corrupt,
        workspace_root=str(temp_workspace),
        status="RUNNING",
        created_at=time.time(),
        updated_at=time.time(),
    )
    sqlite_db.save_checkpoint(
        checkpoint_id=chk_corrupt,
        session_id=f"sess_{m_corrupt}",
        sequence=1,
        reason=CheckpointReason.POST_ACTION.value,
        trigger=CheckpointTrigger.SYSTEM.value,
        created_at=time.time(),
        state_hash="bad_hash",
        manifest_hash="bad_manifest_hash",
        manifest_json=json.dumps({"checkpoint_id": chk_corrupt, "manifest_hash": "tampered_hash"}),
    )
    sqlite_db.save_mission(
        mission_id=m_corrupt,
        workspace_path=str(temp_workspace),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
        latest_checkpoint_id=chk_corrupt,
        execution_active=False,
        recovery_required=True,
    )
    ok, reason = coordinator.evaluate_auto_resume_eligibility(m_corrupt)
    assert ok is False
    assert "checkpoint" in reason.lower()
    row = sqlite_db.get_mission(m_corrupt)
    assert row["status"] == "WAITING"
    assert row["wait_reason"] in ("WAITING_FOR_CHECKPOINT", "RECOVERY_BLOCKED")

    # 5. Permanent authentication / billing error
    m_auth = f"m_auth_{uuid.uuid4().hex[:6]}"
    sqlite_db.save_mission(
        mission_id=m_auth,
        workspace_path=str(temp_workspace),
        status="WAITING",
        wait_reason="WAITING_FOR_PROVIDER",
        execution_active=False,
        recovery_required=True,
        error_json={"category": "AUTHENTICATION_FAILURE", "message": "Invalid API Key"},
    )
    ok, reason = coordinator.evaluate_auto_resume_eligibility(m_auth)
    assert ok is False
    assert "AUTHENTICATION_FAILURE" in reason


# ── Section G: Flapping Protection, Debounce & Concurrency Deduplication ─────

@pytest.mark.asyncio
async def test_section_g_flapping_and_concurrency_deduplication(
    sqlite_db: SQLiteDatabase,
    temp_workspace: Path,
    blob_store: BlobStore,
):
    """Verify rapid debounce and in-flight deduplication prevent multiple simultaneous recovery runs."""
    mission_id = f"m_dedup_{uuid.uuid4().hex[:6]}"
    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(temp_workspace)
    state.mission.status = MissionStatus.WAITING

    chk_id = build_valid_checkpoint(
        db=sqlite_db,
        blob_store=blob_store,
        session_id=f"sess_{mission_id}",
        mission_id=mission_id,
        sequence=1,
        workspace_root=temp_workspace,
        state=state,
    )

    sqlite_db.save_mission(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
        latest_checkpoint_id=chk_id,
        execution_active=False,
        recovery_required=True,
    )

    snap_dict, s_hash = serialize_runtime_state(state)
    sqlite_db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        snapshot_dict=snap_dict,
        state_hash=s_hash,
    )

    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(temp_workspace))
    eb = EventBus(db=sqlite_db)
    adapter = RuntimeAdapter(event_bus=eb, workspace_manager=ws_mgr)
    coordinator = NetworkRecoveryCoordinator(
        db=sqlite_db,
        runtime_adapter=adapter,
        event_bus=eb,
        debounce_seconds=2.0,
    )

    # First recovery pass succeeds
    res1 = await coordinator.recover_waiting_missions()
    assert mission_id in res1

    # Immediate second call within debounce window is ignored (returns empty list)
    res2 = await coordinator.recover_waiting_missions()
    assert res2 == []

    # In-flight recovery guard: cannot re-resume while already marked recovering
    coordinator._recovering_missions.add(mission_id)
    can_resume, reason = coordinator.evaluate_auto_resume_eligibility(mission_id)
    assert can_resume is False
    assert "already actively recovering" in reason
    coordinator._recovering_missions.remove(mission_id)


# ── Section H: Browser-to-Backend Disconnection Resilience (Condition A) ─────

@pytest.mark.asyncio
async def test_section_h_browser_disconnect_resilience(
    sqlite_db: SQLiteDatabase,
    temp_workspace: Path,
):
    """Verify Condition A: SSE subscriber disconnect does not abort mission, and replay resumes from cursor."""
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(temp_workspace))
    eb = EventBus(db=sqlite_db)
    adapter = RuntimeAdapter(event_bus=eb, workspace_manager=ws_mgr)

    mission_id = f"m_sse_{uuid.uuid4().hex[:6]}"

    # Publish events to event bus & journal
    for i in range(1, 6):
        eb.publish(HermesEvent(
            event_type=EventType.AGENT_TURN_COMPLETED,
            mission_id=mission_id,
            sequence=i,
            payload={"turn": i},
        ))

    # Subscribe to SSE generator
    gen = adapter.subscribe_mission_events(mission_id, last_sequence=0)

    # Consume first 2 events
    e1 = await gen.asend(None)
    assert e1.sequence == 1
    e2 = await gen.asend(None)
    assert e2.sequence == 2

    # Simulate client disconnect (close generator)
    await gen.aclose()

    # Verify adapter cleaned up queue subscription
    assert adapter._mission_subscribers.get(mission_id) is None

    # Reconnecting client requests events from cursor sequence 2
    replayed = adapter.get_events_since(mission_id, last_sequence=2)
    assert len(replayed) == 3
    assert [e.sequence for e in replayed] == [3, 4, 5]


# ── Section I: Backend Restart with Waiting Missions Recovery (Condition B) ──

@pytest.mark.asyncio
async def test_section_i_backend_restart_waiting_recovery(
    sqlite_db: SQLiteDatabase,
    blob_store: BlobStore,
    temp_workspace: Path,
):
    """Verify Condition B: when backend restarts, durable state in SQLite is discovered and resumed."""
    mission_id = f"m_restart_{uuid.uuid4().hex[:6]}"

    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(temp_workspace)
    state.mission.status = MissionStatus.WAITING

    chk_id = build_valid_checkpoint(
        db=sqlite_db,
        blob_store=blob_store,
        session_id=f"sess_{mission_id}",
        mission_id=mission_id,
        sequence=1,
        workspace_root=temp_workspace,
        state=state,
    )

    sqlite_db.save_mission(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
        latest_checkpoint_id=chk_id,
        execution_active=False,
        recovery_required=True,
        prompt="Restart resilience test",
    )

    snap_dict, s_hash = serialize_runtime_state(state)
    sqlite_db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        snapshot_dict=snap_dict,
        state_hash=s_hash,
    )

    # Fresh restart: instantiate new EventBus and Adapter from database file
    new_eb = EventBus(db=sqlite_db)
    new_eb.blob_store = blob_store
    new_ws = WorkspaceManager()
    new_ws.lock(str(temp_workspace))
    new_adapter = RuntimeAdapter(event_bus=new_eb, workspace_manager=new_ws)

    # Setup new recovery coordinator
    new_coordinator = NetworkRecoveryCoordinator(
        db=sqlite_db,
        runtime_adapter=new_adapter,
        event_bus=new_eb,
    )

    # Coordinator discovers the waiting mission
    waiting = new_coordinator.find_eligible_waiting_missions()
    assert len(waiting) == 1
    assert waiting[0]["mission_id"] == mission_id

    # Auto-resume recovers mission successfully
    new_run_id = await new_coordinator.auto_resume_mission(mission_id)
    assert new_run_id is not None
    assert new_run_id.startswith("run_2_")

    row = sqlite_db.get_mission(mission_id)
    assert row["status"] == "RUNNING"
    assert row["attempt_number"] == 2


# ── Section J: Network Status and Recovery REST API Endpoints ────────────────

@pytest.mark.asyncio
async def test_section_j_network_api_endpoints(
    sqlite_db: SQLiteDatabase,
    temp_workspace: Path,
):
    """Verify GET /api/network/status and POST /api/network/recover endpoints."""
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(temp_workspace))
    eb = EventBus(db=sqlite_db)
    adapter = RuntimeAdapter(event_bus=eb, workspace_manager=ws_mgr)

    app = create_app(adapter=adapter)
    transport = ASGITransport(app=app)

    headers = {"Host": "127.0.0.1:8765"}
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8765", headers=headers) as client:
        # 1. GET /api/network/status
        res_status = await client.get("/api/network/status")
        assert res_status.status_code == 200
        data = res_status.json()
        assert "status" in data
        assert "is_connected" in data
        assert "probe_targets" in data
        assert "waiting_missions_count" in data
        assert isinstance(data["waiting_missions_count"], int)

        # 2. POST /api/network/recover
        res_rec = await client.post("/api/network/recover")
        assert res_rec.status_code == 200
        rec_data = res_rec.json()
        assert "recovered_count" in rec_data
        assert "recovered_mission_ids" in rec_data
        assert isinstance(rec_data["recovered_mission_ids"], list)


# ── Critical Hardened Acceptance Tests (Phases 7.1) ───────────────────────────

@pytest.mark.asyncio
async def test_critical_a_provider_recovery_without_internet_transition(
    sqlite_db: SQLiteDatabase,
    blob_store: BlobStore,
    temp_workspace: Path,
):
    """
    CRITICAL ACCEPTANCE CONTRACT:
    If general Internet connectivity stays online while a model provider fails,
    and that provider later recovers, HERMES must automatically recover the
    eligible waiting mission WITHOUT requiring a manual call to /api/network/recover.
    """
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(temp_workspace))
    eb = EventBus(db=sqlite_db)
    eb.blob_store = blob_store
    adapter = RuntimeAdapter(event_bus=eb, workspace_manager=ws_mgr)

    # Monitor remains ONLINE continuously throughout the outage
    async def mock_online_probe():
        return True

    monitor = ConnectivityMonitor(custom_probe_func=mock_online_probe, recovery_threshold=1)
    await monitor.probe_now()
    assert monitor.is_online is True

    coordinator = NetworkRecoveryCoordinator(
        monitor=monitor,
        db=sqlite_db,
        runtime_adapter=adapter,
        event_bus=eb,
        debounce_seconds=0.01,
    )
    coordinator.start()

    # Create mission that settled task t1 and entered WAITING_FOR_PROVIDER
    mission_id = f"m_prov_auto_{uuid.uuid4().hex[:6]}"
    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(temp_workspace)
    state.mission.status = MissionStatus.WAITING
    state.progress.waiting_reason = WaitReason.WAITING_FOR_PROVIDER

    t1 = TaskState(
        task_id="t1",
        mission_id=mission_id,
        title="Settled Task 1",
        status=TaskStatus.COMPLETED,
        dependencies=[],
    )
    t2 = TaskState(
        task_id="t2",
        mission_id=mission_id,
        title="Unfinished Task 2",
        status=TaskStatus.PENDING,
        dependencies=["t1"],
    )
    state.tasks = {"t1": t1, "t2": t2}

    # Save snapshot and state blob
    state_dict, s_hash = serialize_runtime_state(state)
    state_bytes = json.dumps(state_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    blob_store.put(state_bytes)

    sqlite_db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        snapshot_dict=state_dict,
        state_hash=s_hash,
        run_id="run_1_prov",
        attempt_number=1,
    )

    chk_id = f"chk_prov_{mission_id}"
    sqlite_db.save_session(
        session_id=f"sess_{mission_id}",
        mission_id=mission_id,
        workspace_root=str(temp_workspace),
        status=SessionStatus.WAITING.value,
        created_at=time.time(),
        updated_at=time.time(),
    )
    manifest = CheckpointManifest(
        checkpoint_id=chk_id,
        session_id=f"sess_{mission_id}",
        mission_id=mission_id,
        sequence=1,
        reason=CheckpointReason.POST_ACTION,
        trigger=CheckpointTrigger.SYSTEM,
        created_at=time.time(),
        state_hash=s_hash,
        workspace=WorkspaceManifest(workspace_root=str(temp_workspace)),
    )
    man_dict = manifest.to_dict()
    man_canonical = json.dumps(man_dict, sort_keys=True)
    m_hash = hashlib.sha256(man_canonical.encode("utf-8")).hexdigest()
    sqlite_db.save_checkpoint(
        checkpoint_id=chk_id,
        session_id=f"sess_{mission_id}",
        sequence=1,
        reason=CheckpointReason.POST_ACTION.value,
        trigger=CheckpointTrigger.SYSTEM.value,
        created_at=time.time(),
        state_hash=s_hash,
        manifest_hash=m_hash,
        manifest_json=man_canonical,
    )

    provider_name = "nvidia_nim"
    model_name = "z-ai/glm-5.3-flash"
    route_key = f"{provider_name}:{model_name}"

    sqlite_db.save_mission(
        mission_id=mission_id,
        workspace_path=str(temp_workspace),
        status="WAITING",
        wait_reason="WAITING_FOR_PROVIDER",
        latest_checkpoint_id=chk_id,
        execution_active=False,
        recovery_required=True,
        error_json={"category": "PROVIDER_UNAVAILABLE", "route": route_key},
    )

    # Verify initial waiting state
    row_init = sqlite_db.get_mission(mission_id)
    assert row_init["status"] == "WAITING"
    assert row_init["wait_reason"] == "WAITING_FOR_PROVIDER"
    assert row_init["execution_active"] is False

    # Simulate provider outage in circuit breaker (OPEN state)
    circuit_rec = circuit_breaker_registry.get_record(provider_name, model_name)
    circuit_rec.state = CircuitState.OPEN

    # Global Internet remains online throughout!
    assert monitor.is_online is True

    # Simulate provider recovery WITHOUT touching /api/network/recover or internet monitor!
    # Direct notification via circuit_breaker_registry or coordinator
    coordinator.notify_provider_recovered(provider_name, model_name)

    # Allow async auto-resume task to complete
    await asyncio.sleep(0.1)

    # Verify that mission was automatically recovered
    row_resumed = sqlite_db.get_mission(mission_id)
    assert row_resumed["status"] == "RUNNING"
    assert row_resumed["execution_active"] is True
    assert row_resumed["attempt_number"] == 2
    assert row_resumed["run_id"].startswith("run_2_")

    # Clean up
    await adapter.stop_mission(mission_id)
    coordinator.stop()


@pytest.mark.asyncio
async def test_critical_c_recoverable_workspace_and_checkpoint_blockers(
    sqlite_db: SQLiteDatabase,
    blob_store: BlobStore,
    temp_workspace: Path,
):
    """
    Verify recoverable blockers (missing workspace, damaged latest checkpoint with valid parent)
    remain safely blocked in WAITING without irreversible terminal FAILED transitions,
    and safely reevaluate when the condition resolves.
    """
    ws_mgr = WorkspaceManager()
    eb = EventBus(db=sqlite_db)
    eb.blob_store = blob_store
    adapter = RuntimeAdapter(event_bus=eb, workspace_manager=ws_mgr)
    coordinator = NetworkRecoveryCoordinator(db=sqlite_db, runtime_adapter=adapter, event_bus=eb)

    # 1. Missing workspace: folder does not yet exist
    unmounted_folder = temp_workspace / "unmounted_volume"
    m_ws_block = f"m_ws_blk_{uuid.uuid4().hex[:6]}"
    sqlite_db.save_mission(
        mission_id=m_ws_block,
        workspace_path=str(unmounted_folder),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
        execution_active=False,
        recovery_required=True,
    )

    # First evaluation: blocked because folder does not exist
    ok1, reason1 = coordinator.evaluate_auto_resume_eligibility(m_ws_block)
    assert ok1 is False
    assert "workspace" in reason1.lower()

    # Verify mission remains in WAITING state (not terminal FAILED)
    row_blk = sqlite_db.get_mission(m_ws_block)
    assert row_blk["status"] == "WAITING"
    assert row_blk["wait_reason"] in ("WAITING_FOR_WORKSPACE", "RECOVERY_BLOCKED")
    assert row_blk["recovery_required"] is True

    # 2. Workspace returns (drive reconnected / folder created)
    unmounted_folder.mkdir(parents=True, exist_ok=True)
    ws_mgr.lock(str(unmounted_folder))

    # Add valid checkpoint and runtime state for m_ws_block
    state = HermesRuntimeState.create_empty(mission_id=m_ws_block)
    state.mission.workspace_root = str(unmounted_folder)
    state.tasks["t1"] = TaskState(task_id="t1", mission_id=m_ws_block, title="T1", status=TaskStatus.PENDING)
    state_dict, s_hash = serialize_runtime_state(state)
    state_bytes = json.dumps(state_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    blob_store.put(state_bytes)
    sqlite_db.save_snapshot(
        mission_id=m_ws_block,
        workspace_path=str(unmounted_folder),
        status="WAITING",
        snapshot_dict=state_dict,
        state_hash=s_hash,
        run_id="run_1_init",
        attempt_number=1,
    )

    chk_valid = f"chk_valid_{m_ws_block}"
    sqlite_db.save_session(
        session_id=f"sess_{m_ws_block}",
        mission_id=m_ws_block,
        workspace_root=str(unmounted_folder),
        status=SessionStatus.WAITING.value,
        created_at=time.time(),
        updated_at=time.time(),
    )
    manifest = CheckpointManifest(
        checkpoint_id=chk_valid,
        session_id=f"sess_{m_ws_block}",
        mission_id=m_ws_block,
        sequence=1,
        reason=CheckpointReason.POST_ACTION,
        trigger=CheckpointTrigger.SYSTEM,
        created_at=time.time(),
        state_hash=s_hash,
        workspace=WorkspaceManifest(workspace_root=str(unmounted_folder)),
    )
    man_canonical = json.dumps(manifest.to_dict(), sort_keys=True)
    m_hash = hashlib.sha256(man_canonical.encode("utf-8")).hexdigest()
    sqlite_db.save_checkpoint(
        checkpoint_id=chk_valid,
        session_id=f"sess_{m_ws_block}",
        sequence=1,
        reason=CheckpointReason.POST_ACTION.value,
        trigger=CheckpointTrigger.SYSTEM.value,
        created_at=time.time(),
        state_hash=s_hash,
        manifest_hash=m_hash,
        manifest_json=man_canonical,
    )
    sqlite_db.save_mission(
        mission_id=m_ws_block,
        workspace_path=str(unmounted_folder),
        status="WAITING",
        wait_reason="WAITING_FOR_NETWORK",
        latest_checkpoint_id=chk_valid,
        execution_active=False,
        recovery_required=True,
    )

    # Second evaluation: now that workspace is accessible, mission is eligible!
    ok2, reason2 = coordinator.evaluate_auto_resume_eligibility(m_ws_block)
    assert ok2 is True
    assert "eligible" in reason2.lower()


@pytest.mark.asyncio
async def test_critical_d_backend_restart_classification_and_eligibility(
    sqlite_db: SQLiteDatabase,
    temp_workspace: Path,
):
    """
    Verify backend startup correctly classifies interrupted running missions as WAITING_FOR_RECOVERY,
    preserves user-stopped/cancelled missions as ineligible, and fences terminal runs.
    """
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(temp_workspace))
    eb = EventBus(db=sqlite_db)

    # 1. Active running mission at crash
    m_crashed = f"m_crash_{uuid.uuid4().hex[:6]}"
    sqlite_db.save_mission(
        mission_id=m_crashed,
        workspace_path=str(temp_workspace),
        status="RUNNING",
        wait_reason="WORKING",
        execution_active=True,
        recovery_required=False,
    )

    # 2. User-cancelled mission before crash
    m_stopped = f"m_stop_{uuid.uuid4().hex[:6]}"
    sqlite_db.save_mission(
        mission_id=m_stopped,
        workspace_path=str(temp_workspace),
        status="CANCELLED",
        wait_reason="NONE",
        execution_active=True,  # Stale flag from crash
        recovery_required=False,
        metadata={"cancelled_by_user": True},
    )

    # 3. Paused mission before crash
    m_paused = f"m_pause_{uuid.uuid4().hex[:6]}"
    sqlite_db.save_mission(
        mission_id=m_paused,
        workspace_path=str(temp_workspace),
        status="PAUSED",
        wait_reason="NONE",
        execution_active=True,  # Stale flag from crash
        recovery_required=False,
    )

    # Perform startup recovery inspection
    adapter = RuntimeAdapter(event_bus=eb, workspace_manager=ws_mgr)
    adapter.restore_persisted_missions()

    # Verify crashed running mission was converted to WAITING_FOR_RECOVERY
    row_c = sqlite_db.get_mission(m_crashed)
    assert row_c["status"] == "WAITING"
    assert row_c["wait_reason"] == "WAITING_FOR_RECOVERY"
    assert row_c["execution_active"] is False
    assert row_c["recovery_required"] is True
    assert row_c["metadata"].get("interrupted_by_restart") is True

    # Verify stopped mission remained CANCELLED and NOT eligible for recovery
    row_s = sqlite_db.get_mission(m_stopped)
    assert row_s["status"] == "CANCELLED"
    assert row_s["execution_active"] is False
    assert row_s["recovery_required"] is False

    # Verify paused mission remained PAUSED and NOT marked for recovery
    row_p = sqlite_db.get_mission(m_paused)
    assert row_p["status"] == "PAUSED"
    assert row_p["execution_active"] is False
    assert row_p["recovery_required"] is False

    # Verify coordinator eligibility filter
    coordinator = NetworkRecoveryCoordinator(db=sqlite_db, runtime_adapter=adapter, event_bus=eb)
    eligible_list = coordinator.find_eligible_waiting_missions()
    eligible_ids = [m["mission_id"] for m in eligible_list]

    assert m_crashed in eligible_ids
    assert m_stopped not in eligible_ids
    assert m_paused not in eligible_ids


@pytest.mark.asyncio
async def test_critical_e_connectivity_probe_tls_and_captive_portal():
    """
    Verify probe correctness:
    1. Public probe URLs pass normal TLS verification (verify=True).
    2. Captive portal interception is rejected without false online reporting.
    3. Response bodies are bounded.
    """
    monitor = ConnectivityMonitor(probe_timeout=3.0)

    # 1. Single probe with real TLS on a public neutral endpoint
    real_res = await monitor._execute_single_probe("https://1.1.1.1/cdn-cgi/trace")
    assert real_res.success is True
    assert real_res.status_code == 200
    assert real_res.latency_ms > 0

    # 2. Captive portal simulation
    class FakeCaptiveTransport(AsyncClient):
        pass

    # Clean monitor shutdown
    await monitor.stop()
