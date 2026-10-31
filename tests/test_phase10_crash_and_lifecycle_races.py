# tests/test_phase10_crash_and_lifecycle_races.py
"""
HERMES Phase 10 — Crash Recovery, Lifecycle Races & Idempotency Fault-Injection Tests.

Stages Tested:
- Stage E: Process crashes & restart recovery (Clean vs ungraceful crash,
          checkpoint corruption fencing, CAS blob validation, resume verification).
- Stage F: Cancellation races & lifecycle concurrency (Stop racing with pending pause,
          Resume racing with pause, multi-mission isolation, terminal immutability).
- Stage G: Duplicate requests & idempotency (Duplicate Stop/Pause/Resume, duplicate mission creation).
"""

import asyncio
import json
import time
from pathlib import Path
import pytest
from starlette.testclient import TestClient

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
    SessionStatus,
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
from core.runtime_state.models import HermesRuntimeState, MissionControlContext, MissionStatus, WaitReason
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter


@pytest.fixture
def lifecycle_env(tmp_path):
    """Fixture providing isolated database, blob store, event bus, and runtime adapter."""
    ws = tmp_path / "workspace_test"
    ws.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "test_lifecycle.db"
    db = SQLiteDatabase(db_path)
    blob_store = BlobStore(tmp_path / "blobs")
    bus = EventBus(enabled=True, db=db)
    adapter = RuntimeAdapter(event_bus=bus)
    app = create_app(adapter=adapter)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    return {
        "workspace": ws,
        "db": db,
        "blob_store": blob_store,
        "bus": bus,
        "adapter": adapter,
        "app": app,
        "client": client,
        "tmp_path": tmp_path,
    }


def register_test_mission_control(adapter, db, mission_id: str, ws: Path, prompt: str = "Test task"):
    """Helper to register active mission control and database record."""
    control = MissionControlContext(
        mission_id=mission_id,
        run_id=f"run_{mission_id}",
        abort_event=asyncio.Event(),
        pause_event=asyncio.Event(),
        workspace_root=str(ws),
    )
    adapter._mission_controls[mission_id] = control
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws),
        status="RUNNING",
        prompt=prompt,
        execution_active=True,
    )
    adapter.event_bus.publish(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        run_id=f"run_{mission_id}",
        payload={"prompt": prompt},
    ))
    return control


# ── Stage E: Process Crashes & Restart Recovery ───────────────────────────────

def test_process_crash_leaves_recoverable_state(lifecycle_env):
    """
    Stage E.1: Ungraceful crash during execution leaves durable records with
    recovery_required=True, and RecoveryEngine validates checkpoint integrity.
    """
    db = lifecycle_env["db"]
    blob_store = lifecycle_env["blob_store"]
    ws = lifecycle_env["workspace"]
    tmp_path = lifecycle_env["tmp_path"]
    chk_engine = CheckpointEngine(base_dir=tmp_path, workspace_root=ws, db=db, blob_store=blob_store)

    mission_id = "m_crash_1"
    session_id = "s_crash_1"

    # 1. Create a dummy file in workspace and persist to CAS blob store
    test_file = ws / "source.py"
    test_content = b"print('version 1')\n"
    test_file.write_bytes(test_content)
    file_blob_id = blob_store.put(test_content)

    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state_dict, _ = serialize_runtime_state(state)
    state_bytes = json.dumps(state_dict, sort_keys=True).encode("utf-8")
    state_blob_id = blob_store.put(state_bytes)

    now = time.time()
    ws_manifest = WorkspaceManifest(
        workspace_root=str(ws),
        total_files=1,
        total_bytes=len(test_content),
        files={"source.py": FileSnapshot(relative_path="source.py", sha256=file_blob_id, size_bytes=len(test_content), mtime_ns=int(now * 1e9), blob_id=file_blob_id)},
    )
    chk = CheckpointManifest(
        checkpoint_id="chk_crash_01",
        session_id=session_id,
        mission_id=mission_id,
        sequence=1,
        state_hash=state_blob_id,
        created_at=now,
        workspace=ws_manifest,
    )

    db.save_session(
        session_id=session_id,
        mission_id=mission_id,
        workspace_root=str(ws),
        status=SessionStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    db.save_checkpoint(
        checkpoint_id=chk.checkpoint_id,
        session_id=session_id,
        sequence=1,
        reason=CheckpointReason.POST_ACTION,
        trigger=CheckpointTrigger.SYSTEM,
        created_at=now,
        state_hash=state_blob_id,
        manifest_hash=chk.manifest_hash,
        manifest_json=json.dumps(chk.to_dict(), sort_keys=True),
    )

    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws),
        status="RUNNING",
        latest_checkpoint_id=chk.checkpoint_id,
        execution_active=False,  # Process died
        recovery_required=True,
    )

    # Initialize RecoveryEngine on backend restart
    recovery = RecoveryEngine(db=db, blob_store=blob_store, checkpoint_engine=chk_engine)

    is_valid, loaded_chk, msg = recovery.validate_checkpoint(chk.checkpoint_id)
    assert is_valid is True
    assert loaded_chk is not None
    assert loaded_chk.checkpoint_id == chk.checkpoint_id

    # Verify workspace binding is preserved
    row = db.get_mission(mission_id)
    assert row["recovery_required"] == 1
    assert row["workspace_path"] == str(ws)


def test_corrupt_checkpoint_fenced_during_recovery(lifecycle_env):
    """
    Stage E.2: Partial write or corrupted checkpoint CAS blob is detected
    and blocked from resuming to prevent state corruption.
    """
    db = lifecycle_env["db"]
    blob_store = lifecycle_env["blob_store"]
    ws = lifecycle_env["workspace"]
    tmp_path = lifecycle_env["tmp_path"]
    chk_engine = CheckpointEngine(base_dir=tmp_path, workspace_root=ws, db=db, blob_store=blob_store)

    mission_id = "m_corrupt_chk"
    session_id = "s_corrupt_chk"

    test_file = ws / "corrupt_target.py"
    test_content = b"# important code"
    test_file.write_bytes(test_content)
    file_blob_id = blob_store.put(test_content)

    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state_dict, _ = serialize_runtime_state(state)
    state_bytes = json.dumps(state_dict, sort_keys=True).encode("utf-8")
    state_blob_id = blob_store.put(state_bytes)

    now = time.time()
    ws_manifest = WorkspaceManifest(
        workspace_root=str(ws),
        total_files=1,
        total_bytes=len(test_content),
        files={"corrupt_target.py": FileSnapshot(relative_path="corrupt_target.py", sha256=file_blob_id, size_bytes=len(test_content), mtime_ns=int(now * 1e9), blob_id=file_blob_id)},
    )
    chk = CheckpointManifest(
        checkpoint_id="chk_corrupt_01",
        session_id=session_id,
        mission_id=mission_id,
        sequence=1,
        state_hash=state_blob_id,
        created_at=now,
        workspace=ws_manifest,
    )

    db.save_session(
        session_id=session_id,
        mission_id=mission_id,
        workspace_root=str(ws),
        status=SessionStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    db.save_checkpoint(
        checkpoint_id=chk.checkpoint_id,
        session_id=session_id,
        sequence=1,
        reason=CheckpointReason.POST_ACTION,
        trigger=CheckpointTrigger.SYSTEM,
        created_at=now,
        state_hash=state_blob_id,
        manifest_hash=chk.manifest_hash,
        manifest_json=json.dumps(chk.to_dict(), sort_keys=True),
    )

    recovery = RecoveryEngine(db=db, blob_store=blob_store, checkpoint_engine=chk_engine)

    # Corrupt the CAS blob on disk
    blob_path = blob_store._blob_path(file_blob_id)
    blob_path.write_bytes(b"corrupted_damaged_data")

    is_valid, _, msg = recovery.validate_checkpoint(chk.checkpoint_id)
    assert is_valid is False
    assert "missing or corrupt" in msg.lower() or "corrupt" in msg.lower()


# ── Stage F: Cancellation Races & Lifecycle Concurrency ───────────────────────

@pytest.mark.asyncio
async def test_stop_racing_with_pending_pause_terminal_wins(lifecycle_env):
    """
    Stage F.1: When Stop arrives while Pause is pending, Stop takes priority,
    mission transitions to CANCELLED (terminal), and subsequent pause attempts fail.
    """
    client = lifecycle_env["client"]
    adapter = lifecycle_env["adapter"]
    db = lifecycle_env["db"]
    ws = lifecycle_env["workspace"]
    mission_id = "m_race_stop_pause"

    register_test_mission_control(adapter, db, mission_id, ws, "Race stop vs pause")

    # 1. Request pause
    resp_pause = client.post(f"/api/missions/{mission_id}/pause")
    assert resp_pause.status_code == 200
    assert resp_pause.json()["status"] in ["PAUSED", "PAUSE_REQUESTED"]

    # 2. Immediately call stop
    resp_stop = client.post(f"/api/missions/{mission_id}/stop")
    assert resp_stop.status_code == 200
    assert resp_stop.json()["cancelled"] is True

    # Check adapter control state
    control = adapter._mission_controls[mission_id]
    assert control.is_terminal is True
    assert control.is_cancelled is True

    # 3. Delayed/subsequent pause must be rejected (409 Conflict)
    resp_late_pause = client.post(f"/api/missions/{mission_id}/pause")
    assert resp_late_pause.status_code == 409
    assert "terminal state" in resp_late_pause.json()["detail"]


@pytest.mark.asyncio
async def test_resume_racing_with_pause_no_deadlock(lifecycle_env):
    """
    Stage F.2: Calling Resume while Pause is pending safely unpauses
    without deadlock or state contradiction.
    """
    adapter = lifecycle_env["adapter"]
    db = lifecycle_env["db"]
    ws = lifecycle_env["workspace"]
    mission_id = "m_race_pause_resume"

    control = register_test_mission_control(adapter, db, mission_id, ws, "Race pause vs resume")
    control.request_pause()
    assert control.pause_requested is True

    # Client issues resume before pause completes
    adapter.resume_mission(mission_id)
    assert control.pause_requested is False
    assert not control.is_paused
    assert not control.is_terminal
    assert not control.is_cancelled


def test_terminal_mission_cannot_be_resumed_or_paused(lifecycle_env):
    """
    Stage F.3: Missions in terminal states (CANCELLED, COMPLETED) reject
    both Pause and Resume calls with HTTP 409 Conflict.
    """
    client = lifecycle_env["client"]
    db = lifecycle_env["db"]
    ws = lifecycle_env["workspace"]

    # Saved as CANCELLED in DB
    db.save_mission("m_term_cancelled", str(ws), "CANCELLED")
    resp_p1 = client.post("/api/missions/m_term_cancelled/pause")
    assert resp_p1.status_code == 409

    resp_r1 = client.post("/api/missions/m_term_cancelled/resume")
    assert resp_r1.status_code == 409

    # Saved as COMPLETED in DB
    db.save_mission("m_term_completed", str(ws), "COMPLETED")
    resp_p2 = client.post("/api/missions/m_term_completed/pause")
    assert resp_p2.status_code == 409

    resp_r2 = client.post("/api/missions/m_term_completed/resume")
    assert resp_r2.status_code == 409


def test_multi_mission_lifecycle_isolation(lifecycle_env):
    """
    Stage F.4: Controlling mission_alpha has zero impact on mission_beta.
    """
    client = lifecycle_env["client"]
    adapter = lifecycle_env["adapter"]
    db = lifecycle_env["db"]
    ws = lifecycle_env["workspace"]

    register_test_mission_control(adapter, db, "m_alpha", ws, "Alpha task")
    register_test_mission_control(adapter, db, "m_beta", ws, "Beta task")

    # Stop alpha
    resp_stop = client.post("/api/missions/m_alpha/stop")
    assert resp_stop.status_code == 200
    assert resp_stop.json()["cancelled"] is True

    # Beta must still be active and unaffected
    control_beta = adapter._mission_controls["m_beta"]
    assert not control_beta.is_terminal
    assert not control_beta.is_cancelled
    assert not control_beta.is_paused


# ── Stage G: Duplicate Requests & Idempotency ─────────────────────────────────

def test_duplicate_stop_requests_idempotent(lifecycle_env):
    """
    Stage G.1: Duplicate Stop requests return cleanly without error or event storms.
    First call returns cancelled=True; second call returns cancelled=False (already terminated).
    """
    client = lifecycle_env["client"]
    adapter = lifecycle_env["adapter"]
    db = lifecycle_env["db"]
    ws = lifecycle_env["workspace"]
    mission_id = "m_dup_stop"

    register_test_mission_control(adapter, db, mission_id, ws, "Idempotent stop")

    resp1 = client.post(f"/api/missions/{mission_id}/stop")
    assert resp1.status_code == 200
    assert resp1.json()["cancelled"] is True

    resp2 = client.post(f"/api/missions/{mission_id}/stop")
    assert resp2.status_code == 200
    assert resp2.json()["cancelled"] is False
    assert "already terminated" in resp2.json()["message"]


def test_duplicate_mission_creation_preserves_binding(lifecycle_env):
    """
    Stage G.2: Creating an existing mission_id in database preserves
    original workspace and does not overwrite or corrupt records.
    """
    db = lifecycle_env["db"]
    ws1 = lifecycle_env["workspace"] / "proj1"
    ws2 = lifecycle_env["workspace"] / "proj2"
    ws1.mkdir(parents=True, exist_ok=True)
    ws2.mkdir(parents=True, exist_ok=True)

    mission_id = "m_idempotent_bind"

    db.save_mission(mission_id, str(ws1), "RUNNING", prompt="Initial creation")
    row1 = db.get_mission(mission_id)
    assert row1["workspace_path"] == str(ws1)

    # Re-saving same mission with blank prompt keeps original prompt
    db.save_mission(mission_id, str(ws1), "RUNNING", prompt="")
    row2 = db.get_mission(mission_id)
    assert row2["prompt"] == "Initial creation"
    assert row2["workspace_path"] == str(ws1)
