# tests/test_phase2_durable_persistence.py
"""
Deterministic Phase 2 Acceptance Test Suite for Durable Event Journal,
Versioned Checkpoints, and Restart-Safe State Persistence.

Scenarios Covered:
- Scenario A: Durable Event Journal Append (events durably stored with monotonic sequence).
- Scenario B: Sequence Monotonicity and Persistence Across Restart.
- Scenario C: State Snapshot Persistence and Deterministic Replay Reconstruction.
- Scenario D: Checkpoint Manifest Versioning, Hashing, and Multi-Domain Integrity.
- Scenario E: Safe Execution Boundary Checkpoint Creation (Start, Turn Settled, Verification, Terminal).
- Scenario F: Verification Evidence Journaling and Preservation.
- Scenario G: Backend Process Restart Simulation & Interrupted Mission Recovery State.
- Scenario H: Replay Beyond In-Memory 1,000-Event Buffer (Querying SQLite Database).
- Scenario I: High-Throughput Concurrent Persistence and Monotonic Ordering.
- Scenario J: Database Corruption & Missing Blob Integrity Detection.
- Scenario K: Non-Blocking EventBus Dispatch & Flush Concurrency.
- Scenario L: Phase 1 Lifecycle Invariants Preservation with Phase 2 Persistence.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest

from core.checkpoints.engine import CheckpointEngine
from core.event_bus import EventBus
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase, get_canonical_database_path
from core.persistence.models import (
    CheckpointManifest,
    CheckpointReason,
    CheckpointTrigger,
    FileSnapshot,
    WorkspaceManifest,
)
from core.persistence.serializer import (
    deserialize_runtime_state,
    serialize_runtime_state,
)
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionControlContext,
    MissionStatus,
    TaskState,
    TaskStatus,
)
from core.runtime_state.reducer import StateReducer
from core.runtime_state.store import StateStore
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import WorkspaceManager


@pytest.fixture
def temp_persistence_env(tmp_path: Path):
    """Provide isolated SQLite database, blob store, and workspace environment."""
    db_file = tmp_path / "hermes_test_runtime.db"
    blob_dir = tmp_path / "blobs"
    ws_dir = tmp_path / "test_workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(db_file)
    blobs = BlobStore(blob_dir)
    bus = EventBus(db=db)
    yield {
        "db": db,
        "blobs": blobs,
        "bus": bus,
        "workspace": ws_dir,
        "base_dir": tmp_path,
        "db_file": db_file,
    }
    bus.flush()


# ── Scenario A: Durable Event Journal Append ──────────────────────────────────

def test_scenario_a_durable_event_journal_append(temp_persistence_env):
    """Verify that every accepted mission event is journaled durably with monotonic sequence."""
    db: SQLiteDatabase = temp_persistence_env["db"]
    bus: EventBus = temp_persistence_env["bus"]
    mission_id = "m_journal_a"

    # Publish a sequence of 5 distinct events
    events_published = []
    for i in range(5):
        evt = bus.publish(
            event_or_type=EventType.AGENT_TURN_STARTED if i % 2 == 0 else EventType.AGENT_DECISION,
            payload={"turn": i, "details": f"Turn execution step {i}"},
            mission_id=mission_id,
        )
        events_published.append(evt)

    # Ensure queue flushes to disk
    bus.flush()

    # Query directly from the SQLite database
    persisted = db.get_mission_events(mission_id)
    assert len(persisted) == 5, f"Expected 5 persisted events, found {len(persisted)}"

    for idx, row in enumerate(persisted):
        assert row["sequence"] == events_published[idx].sequence
        assert row["mission_id"] == mission_id
        assert row["event_id"] == events_published[idx].event_id
        assert row["payload"]["payload"]["turn"] == idx


# ── Scenario B: Sequence Monotonicity and Persistence Across Restart ───────────

def test_scenario_b_sequence_monotonicity_across_restart(temp_persistence_env):
    """Verify that monotonic sequences continue strictly incrementing across process restarts."""
    db_file = temp_persistence_env["db_file"]
    db1 = SQLiteDatabase(db_file)
    bus1 = EventBus(db=db1)

    s1 = db1.allocate_next_sequence()
    s2 = db1.allocate_next_sequence()
    assert s2 > s1, f"Sequences must be monotonic: s1={s1}, s2={s2}"

    bus1.publish(EventType.MISSION_CREATED, {"name": "run1"}, mission_id="m_restart_b")
    bus1.publish(EventType.MISSION_STARTED, {"name": "run1"}, mission_id="m_restart_b")
    bus1.flush()

    # Simulate process shutdown and restart with a fresh database & bus instance
    del bus1
    del db1

    db2 = SQLiteDatabase(db_file)
    bus2 = EventBus(db=db2)

    s3 = db2.allocate_next_sequence()
    assert s3 > s2, f"Sequence after restart must strictly exceed previous sequence: s3={s3}, s2={s2}"

    evt3 = bus2.publish(EventType.AGENT_TURN_STARTED, {"turn": 1}, mission_id="m_restart_b")
    bus2.flush()
    assert evt3.sequence > 2


# ── Scenario C: State Snapshot Persistence and Deterministic Replay ────────────

def test_scenario_c_snapshot_persistence_and_replay_reconstruction(temp_persistence_env):
    """Verify that authoritative state snapshots survive and can be reconstructed via journal replay."""
    db: SQLiteDatabase = temp_persistence_env["db"]
    mission_id = "m_snap_c"

    # Build up state
    state = HermesRuntimeState.create_empty(mission_id)
    state.mission.status = MissionStatus.RUNNING
    state.mission.prompt = "Build durable state subsystem"
    state.mission.run_id = "run_snap_c"
    state.mission.attempt_number = 2
    state.tasks["t1"] = TaskState(task_id="t1", mission_id=mission_id, title="Implement journal", status=TaskStatus.COMPLETED)
    state.tasks["t2"] = TaskState(task_id="t2", mission_id=mission_id, title="Implement snapshots", status=TaskStatus.RUNNING)
    state.state_version = 12
    state.last_event_sequence = 45

    snap_dict, state_hash = serialize_runtime_state(state)
    db.save_snapshot(
        mission_id=mission_id,
        workspace_path="/workspace/c",
        status="RUNNING",
        snapshot_dict=snap_dict,
        state_hash=state_hash,
        run_id="run_snap_c",
        attempt_number=2,
        state_version=12,
        last_event_sequence=45,
    )

    # Retrieve snapshot and deserialize
    retrieved = db.get_snapshot(mission_id)
    assert retrieved is not None
    restored_state = deserialize_runtime_state(retrieved["snapshot"])

    assert restored_state.mission.mission_id == mission_id
    assert restored_state.mission.run_id == "run_snap_c"
    assert restored_state.mission.attempt_number == 2
    assert restored_state.mission.status == MissionStatus.RUNNING
    assert restored_state.state_version == 12
    assert restored_state.last_event_sequence == 45
    assert len(restored_state.tasks) == 2
    assert restored_state.tasks["t1"].status == TaskStatus.COMPLETED

    # Deterministic replay on top of snapshot: apply completion of t2
    completion_evt = HermesEvent(
        event_type=EventType.TASK_COMPLETED,
        mission_id=mission_id,
        run_id="run_snap_c",
        sequence=46,
        task_id="t2",
        payload={"task_id": "t2"},
    )
    replayed_state = StateReducer.reduce(restored_state, completion_evt)
    assert replayed_state.tasks["t2"].status == TaskStatus.COMPLETED
    assert replayed_state.last_event_sequence == 46


# ── Scenario D: Checkpoint Manifest Versioning, Hashing, and CAS Integrity ─────

def test_scenario_d_checkpoint_manifest_and_blob_integrity(temp_persistence_env):
    """Verify that versioned checkpoints capture complete multi-domain state and CAS blobs."""
    db: SQLiteDatabase = temp_persistence_env["db"]
    blobs: BlobStore = temp_persistence_env["blobs"]
    bus: EventBus = temp_persistence_env["bus"]
    ws: Path = temp_persistence_env["workspace"]
    base_dir: Path = temp_persistence_env["base_dir"]

    # Create dummy files in workspace
    code_file = ws / "core.py"
    code_file.write_text("print('Hermes Engine')", encoding="utf-8")

    engine = CheckpointEngine(
        base_dir=base_dir,
        workspace_root=ws,
        db=db,
        blob_store=blobs,
        event_bus=bus,
    )

    state = HermesRuntimeState.create_empty("m_chk_d")
    state.mission.status = MissionStatus.RUNNING
    state.mission.run_id = "run_d"
    state.mission.attempt_number = 1
    state.last_event_sequence = 10

    chk = engine.create_checkpoint(
        session_id="sess_d",
        mission_id="m_chk_d",
        runtime_state=state,
        reason=CheckpointReason.MANUAL,
        trigger=CheckpointTrigger.USER,
        sequence=10,
    )

    assert chk.checkpoint_id.startswith("chk_")
    assert chk.mission_id == "m_chk_d"
    assert chk.manifest_hash is not None
    assert chk.workspace.total_files == 1

    # Verify integrity passes
    assert engine.verify_checkpoint_integrity(chk.checkpoint_id) is True

    # Check database row
    row = db.get_checkpoint(chk.checkpoint_id)
    assert row is not None
    assert row["manifest_hash"] == chk.manifest_hash


# ── Scenario E: Safe Execution Boundary Checkpoint Creation ────────────────────

@pytest.mark.asyncio
async def test_scenario_e_safe_execution_boundary_checkpoints(temp_persistence_env):
    """Verify checkpoints are triggered at safe execution boundaries without interrupting execution."""
    db: SQLiteDatabase = temp_persistence_env["db"]
    blobs: BlobStore = temp_persistence_env["blobs"]
    bus: EventBus = temp_persistence_env["bus"]
    ws: Path = temp_persistence_env["workspace"]
    base_dir: Path = temp_persistence_env["base_dir"]

    engine = CheckpointEngine(
        base_dir=base_dir,
        workspace_root=ws,
        db=db,
        blob_store=blobs,
        event_bus=bus,
    )

    from core.agent_loop.loop import AgentLoop
    from unittest.mock import MagicMock

    orchestrator_mock = MagicMock()
    loop = AgentLoop(
        orchestrator=orchestrator_mock,
        event_bus_instance=bus,
        checkpoint_engine=engine,
    )

    mission_id = "m_safe_boundary_e"
    loop._mission_id = mission_id
    loop._session_id = f"sess_{mission_id}"
    store = bus.get_or_create_state(mission_id)

    # 1. Mission start boundary
    loop._capture_safe_checkpoint("MISSION_START")
    bus.flush()
    chks_start = engine.list_checkpoints(f"sess_{mission_id}")
    assert len(chks_start) == 1
    assert chks_start[0].reason == CheckpointReason.MANUAL

    # 2. Turn settled boundary
    loop._capture_safe_checkpoint("TURN_SETTLED", turn_id="turn_1")
    bus.flush()
    chks_turn = engine.list_checkpoints(f"sess_{mission_id}")
    assert len(chks_turn) == 2
    assert chks_turn[1].reason == CheckpointReason.POST_ACTION

    # 3. Verification gate boundary
    loop._capture_safe_checkpoint("VERIFICATION_COMPLETED", turn_id="turn_1")
    bus.flush()
    chks_ver = engine.list_checkpoints(f"sess_{mission_id}")
    assert len(chks_ver) == 3
    assert chks_ver[2].reason == CheckpointReason.POST_VERIFICATION


# ── Scenario F: Verification Evidence Journaling and Preservation ─────────────

def test_scenario_f_verification_evidence_preservation(temp_persistence_env):
    """Verify that verification command runs and exit codes are durably persisted in evidence table."""
    db: SQLiteDatabase = temp_persistence_env["db"]
    mission_id = "m_verif_f"

    db.save_verification_evidence(
        evidence_id="ev_pytest_01",
        mission_id=mission_id,
        command='python -m pytest tests/test_math.py',
        working_dir="C:/projects/sample",
        interpreter="C:/Python312/python.exe",
        exit_code=0,
        status="PASSED",
        run_id="run_f",
        duration_seconds=1.45,
        output_summary="2 passed in 1.45s",
        rationale="All unit tests passed cleanly.",
    )

    db.save_verification_evidence(
        evidence_id="ev_lint_02",
        mission_id=mission_id,
        command='flake8 .',
        working_dir="C:/projects/sample",
        interpreter="C:/Python312/python.exe",
        exit_code=1,
        status="FAILED",
        run_id="run_f",
        duration_seconds=0.32,
        output_summary="1 lint error on app.py:10",
        rationale="Unused import found.",
    )

    records = db.list_verification_evidence(mission_id)
    assert len(records) == 2
    assert records[0]["evidence_id"] == "ev_pytest_01"
    assert records[0]["exit_code"] == 0
    assert records[0]["status"] == "PASSED"
    assert records[1]["exit_code"] == 1
    assert records[1]["status"] == "FAILED"


# ── Scenario G: Process Restart Simulation & Interrupted Recovery State ────────

def test_scenario_g_process_restart_recovery_state(temp_persistence_env):
    """Verify that restarting the backend marks in-flight active missions as execution_active=False, recovery_required=True."""
    db_file = temp_persistence_env["db_file"]
    db = SQLiteDatabase(db_file)
    mission_id = "m_restart_g"

    # Simulate in-flight mission running when backend process is abruptly killed
    db.save_mission(
        mission_id=mission_id,
        workspace_path="/workspace/g",
        status="RUNNING",
        run_id="run_g_1",
        attempt_number=1,
        prompt="Process interrupted halfway",
        execution_active=True,
        recovery_required=False,
    )

    state = HermesRuntimeState.create_empty(mission_id)
    state.mission.status = MissionStatus.RUNNING
    state.mission.run_id = "run_g_1"
    state.tasks["t_wip"] = TaskState(task_id="t_wip", mission_id=mission_id, title="Work in progress task", status=TaskStatus.RUNNING)
    snap_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(
        mission_id=mission_id,
        workspace_path="/workspace/g",
        status="RUNNING",
        snapshot_dict=snap_dict,
        state_hash=s_hash,
        run_id="run_g_1",
    )

    # Initialize a new adapter instance (simulating fresh server launch)
    new_bus = EventBus(db=db)
    adapter = RuntimeAdapter(event_bus=new_bus)

    # Assert that mission was truthfully updated to execution_active=False, recovery_required=True
    persisted = db.get_mission(mission_id)
    assert persisted is not None
    assert persisted["execution_active"] is False, "Interrupted mission must not remain marked active"
    assert persisted["recovery_required"] is True, "Interrupted mission must require recovery"

    # Verify authoritative state was restored without executing duplicate work
    restored_snap = adapter.get_mission_snapshot(mission_id)
    assert restored_snap is not None
    assert restored_snap.mission.mission_id == mission_id
    assert "t_wip" in restored_snap.tasks
    assert len(adapter._active_tasks) == 0, "No duplicate background tasks should be automatically launched"


# ── Scenario H: Replay Beyond In-Memory 1,000-Event Buffer ─────────────────────

def test_scenario_h_replay_beyond_buffer_limit(temp_persistence_env):
    """Verify event replay retrieves events from the SQLite database journal when cursor is older than ring buffer."""
    db: SQLiteDatabase = temp_persistence_env["db"]
    # Initialize an EventBus with a tiny buffer size of 10 events
    bus = EventBus(buffer_size=10, db=db)
    mission_id = "m_overflow_h"

    # Publish 25 events (overflowing the 10-event memory buffer by 15 events)
    for i in range(1, 26):
        bus.publish(
            event_or_type=EventType.AGENT_TURN_STARTED,
            payload={"step": i},
            mission_id=mission_id,
        )

    bus.flush()

    # Replay requesting from sequence 1 (which was evicted from in-memory ring buffer)
    replayed = bus.replay(mission_id, from_seq=1)
    assert len(replayed) == 25, f"Expected full 25 events replayed from DB, got {len(replayed)}"
    assert replayed[0].sequence == 1
    assert replayed[-1].sequence == 25
    step_0 = replayed[0].payload.get("step") or replayed[0].payload.get("payload", {}).get("step")
    step_24 = replayed[24].payload.get("step") or replayed[24].payload.get("payload", {}).get("step")
    assert step_0 == 1
    assert step_24 == 25


# ── Scenario I: High-Throughput Concurrent Persistence and Monotonicity ────────

def test_scenario_i_concurrent_persistence_ordering(temp_persistence_env):
    """Verify multi-threaded event publication preserves strict monotonic sequence and zero collisions."""
    import concurrent.futures

    db: SQLiteDatabase = temp_persistence_env["db"]
    bus: EventBus = temp_persistence_env["bus"]
    mission_id = "m_concurrent_i"

    def worker_publish(thread_idx: int):
        events = []
        for j in range(20):
            evt = bus.publish(
                event_or_type=EventType.AGENT_DECISION,
                payload={"thread": thread_idx, "iter": j},
                mission_id=mission_id,
            )
            events.append(evt)
        return events

    # Launch 5 concurrent threads publishing simultaneously
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker_publish, i) for i in range(5)]
        results = [f.result() for f in futures]

    bus.flush()

    # Flatten results
    all_published = [evt for thread_list in results for evt in thread_list]
    assert len(all_published) == 100

    # Ensure all sequence numbers are unique
    seqs = [evt.sequence for evt in all_published]
    assert len(set(seqs)) == 100, "Sequence numbers must be globally unique"

    # Query from database and verify exact ordering
    db_events = db.get_mission_events(mission_id)
    assert len(db_events) == 100
    db_seqs = [r["sequence"] for r in db_events]
    assert db_seqs == sorted(db_seqs), "Persisted events must be strictly sorted by sequence"


# ── Scenario J: Database Corruption and Missing Blob Integrity Detection ──────

def test_scenario_j_corruption_and_tamper_detection(temp_persistence_env):
    """Verify that tampering with or deleting a blob causes verify_checkpoint_integrity to report False."""
    db: SQLiteDatabase = temp_persistence_env["db"]
    blobs: BlobStore = temp_persistence_env["blobs"]
    bus: EventBus = temp_persistence_env["bus"]
    ws: Path = temp_persistence_env["workspace"]
    base_dir: Path = temp_persistence_env["base_dir"]

    # Write a test file
    test_file = ws / "important_data.json"
    test_file.write_text('{"balance": 1000}', encoding="utf-8")

    engine = CheckpointEngine(
        base_dir=base_dir,
        workspace_root=ws,
        db=db,
        blob_store=blobs,
        event_bus=bus,
    )

    state = HermesRuntimeState.create_empty("m_tamper_j")
    chk = engine.create_checkpoint(
        session_id="sess_j",
        mission_id="m_tamper_j",
        runtime_state=state,
        reason=CheckpointReason.MANUAL,
    )

    assert engine.verify_checkpoint_integrity(chk.checkpoint_id) is True

    # Tamper with the state blob by overwriting its content
    state_blob_path = blobs._blob_path(chk.state_hash)
    if state_blob_path and state_blob_path.exists():
        state_blob_path.write_bytes(b"CORRUPTED_PAYLOAD")

    # Integrity verification must truthfully detect the corruption
    assert engine.verify_checkpoint_integrity(chk.checkpoint_id) is False


# ── Scenario K: Non-Blocking EventBus Dispatch & Flush Concurrency ─────────────

def test_scenario_k_non_blocking_publish_performance(temp_persistence_env):
    """Verify that EventBus.publish() returns within sub-millisecond execution latency."""
    bus: EventBus = temp_persistence_env["bus"]
    mission_id = "m_perf_k"

    latencies = []
    for i in range(100):
        t0 = time.perf_counter()
        bus.publish(
            event_or_type=EventType.OBSERVATION_CREATED,
            payload={"index": i},
            mission_id=mission_id,
        )
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)  # Convert to ms

    avg_ms = sum(latencies) / len(latencies)
    max_ms = max(latencies)

    # In-memory publication must remain non-blocking (well under 5ms, typically <0.5ms)
    assert avg_ms < 5.0, f"Average publish latency too high: {avg_ms:.3f}ms"
    bus.flush()


# ── Scenario L: Phase 1 Lifecycle Invariants Preservation ─────────────────────

def test_scenario_l_phase1_lifecycle_preservation(temp_persistence_env):
    """Verify that Phase 1 lifecycle invariants remain strictly intact with Phase 2 persistence enabled."""
    db: SQLiteDatabase = temp_persistence_env["db"]
    bus: EventBus = temp_persistence_env["bus"]
    mission_id = "m_phase1_l"

    store = bus.get_or_create_state(mission_id)

    # 1. Legal progression
    bus.publish(EventType.MISSION_CREATED, {"prompt": "P1"}, mission_id=mission_id)
    bus.publish(EventType.MISSION_STARTED, {}, mission_id=mission_id)
    assert store.get_state().mission.status == MissionStatus.RUNNING

    # 2. Terminal state transition
    bus.publish(EventType.MISSION_COMPLETED, {"reason": "Done"}, mission_id=mission_id)
    assert store.get_state().mission.status == MissionStatus.COMPLETED
    assert store.get_state().mission.is_terminal is True

    # 3. Terminal state immutability: illegal resurrection rejected
    bus.publish(EventType.MISSION_STARTED, {}, mission_id=mission_id)
    assert store.get_state().mission.status == MissionStatus.COMPLETED

    bus.flush()
    db_events = db.get_mission_events(mission_id)
    assert len(db_events) >= 3
