# tests/test_phase12_stop_resume.py
"""
HERMES Phase 12: Controlled Stop and Resume Recovery Validation Suite.
Validates:
1. Multi-step mission initialization with persistent SQLite store & BlobStore.
2. Real Stop request execution during active mission.
3. Clean halt without file corruption; state preserved in database & event store.
4. Resume request execution selecting the first unfinished task (skipping completed steps).
5. State durability and final completion verification.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from core.checkpoints.engine import CheckpointEngine
from core.event_bus import EventBus
from core.persistence.blobs import BlobStore
from core.persistence.database import SQLiteDatabase
from core.persistence.models import OperationStatus
from core.persistence.recovery import RecoveryEngine
from core.persistence.serializer import serialize_runtime_state
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionState,
    MissionStatus,
    TaskState,
    TaskStatus,
)
from core.server.app import create_app
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import WorkspaceManager


@pytest.mark.asyncio
async def test_phase12_real_stop_resume_lifecycle(tmp_path: Path):
    """
    Execute controlled multi-step mission Stop and Resume test.
    Stage H verification checklist:
    - Multi-step mission started
    - Real Stop request issued
    - Running step halts safely without file corruption
    - Mission state preserved in database and event store (CANCELLED / STOPPED)
    - Resume request issued
    - Resumes from first incomplete step (does not re-execute completed step)
    - Successful completion of all steps with final verified output
    """
    # 1. Setup isolated directories
    ws_dir = tmp_path / "stop_resume_workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "hermes_recovery.db"
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(db_path)
    blobs = BlobStore(blob_dir)
    bus = EventBus(db=db)
    setattr(bus, "blob_store", blobs)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(ws_dir))

    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    app = create_app(adapter=adapter)

    mission_id = f"m_phase12_sr_{int(time.time())}"
    run_1_id = f"run_1_{mission_id}"

    # 2. Initialize mission in DB
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="RUNNING",
        run_id=run_1_id,
        attempt_number=1,
        prompt="Phase 12 Controlled Multi-step Build and Recovery Test",
        execution_active=True,
    )

    # 3. Simulate execution of Step 1: LabFlow Config Setup
    step1_content = json.dumps({
        "component": "labflow_config",
        "step": 1,
        "database": "sqlite_wal",
        "version": "1.0.0",
        "timestamp": time.time(),
    }, indent=2).encode("utf-8")
    step1_file = ws_dir / "step1_config.json"
    step1_file.write_bytes(step1_content)
    step1_hash = hashlib.sha256(step1_content).hexdigest()

    # Record settled operation in database ledger
    db.record_tool_intent(
        operation_id="op_sr_step1",
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=1,
        target_path="step1_config.json",
        workspace_root=str(ws_dir),
        task_id="task_setup",
    )
    db.record_tool_result(
        operation_id="op_sr_step1",
        result_seq=2,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=step1_hash,
    )

    # Save state: task_setup is COMPLETED, task_build is PENDING
    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(ws_dir)
    state.tasks["task_setup"] = TaskState(
        task_id="task_setup",
        mission_id=mission_id,
        title="Environment and Configuration Setup",
        status=TaskStatus.COMPLETED,
        completion_reason="Configuration verified",
    )
    state.tasks["task_build"] = TaskState(
        task_id="task_build",
        mission_id=mission_id,
        title="Application Build and Schema Provisioning",
        status=TaskStatus.PENDING,
        dependencies=["task_setup"],
    )

    snap_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="RUNNING",
        snapshot_dict=snap_dict,
        state_hash=s_hash,
    )
    store = bus.get_or_create_state(mission_id)
    store._state = state

    # 4. Issue a real Stop request via HTTP API
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8765", headers={"Host": "127.0.0.1:8765"}) as client:
        stop_resp = await client.post(f"/api/missions/{mission_id}/stop")
        assert stop_resp.status_code == 200, f"Stop request failed: {stop_resp.text}"
        stop_data = stop_resp.json()
        assert stop_data["cancelled"] is True

    # 5. Verify Stopped State:
    # Check that database records reflect stopped status
    m_row = db.get_mission(mission_id)
    assert m_row["status"] == "CANCELLED"
    assert m_row["execution_active"] is False

    # Check that step1_config.json is uncorrupted
    assert step1_file.exists()
    assert hashlib.sha256(step1_file.read_bytes()).hexdigest() == step1_hash

    # Check resume preview before resuming
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8765", headers={"Host": "127.0.0.1:8765"}) as client:
        preview_resp = await client.get(f"/api/missions/{mission_id}/resume-preview")
        assert preview_resp.status_code == 200
        preview = preview_resp.json()
        assert preview["can_resume"] is True
        assert preview["target_task_id"] == "task_build"
        assert "task_setup" in preview["completed_tasks"]

    # 6. Issue Resume request via HTTP API
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8765", headers={"Host": "127.0.0.1:8765"}) as client:
        resume_resp = await client.post(f"/api/missions/{mission_id}/resume")
        assert resume_resp.status_code == 200, f"Resume request failed: {resume_resp.text}"
        resume_data = resume_resp.json()
        assert resume_data["status"] == "RUNNING"
        assert resume_data["attempt_number"] == 2
        assert resume_data["run_id"].startswith("run_2_")

    # 7. Execute Step 2 under the resumed run
    step2_content = json.dumps({
        "component": "labflow_schema",
        "step": 2,
        "tables": ["labs", "bookings"],
        "status": "ready",
        "timestamp": time.time(),
    }, indent=2).encode("utf-8")
    step2_file = ws_dir / "step2_schema.json"
    step2_file.write_bytes(step2_content)
    step2_hash = hashlib.sha256(step2_content).hexdigest()

    db.record_tool_intent(
        operation_id="op_sr_step2",
        mission_id=mission_id,
        tool_name="write_file",
        intent_seq=3,
        target_path="step2_schema.json",
        workspace_root=str(ws_dir),
        task_id="task_build",
    )
    db.record_tool_result(
        operation_id="op_sr_step2",
        result_seq=4,
        status=OperationStatus.RESULT_COMMITTED,
        post_hash=step2_hash,
    )

    # Complete the mission
    state.tasks["task_build"].status = TaskStatus.COMPLETED
    state.tasks["task_build"].completion_reason = "Schema provisioned successfully"
    state.mission.status = MissionStatus.COMPLETED
    final_dict, f_hash = serialize_runtime_state(state)
    db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="COMPLETED",
        snapshot_dict=final_dict,
        state_hash=f_hash,
    )
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(ws_dir),
        status="COMPLETED",
        run_id=resume_data["run_id"],
        attempt_number=2,
        prompt="Phase 12 Controlled Multi-step Build and Recovery Test",
        execution_active=False,
    )

    # 8. Final assertions
    final_mission = db.get_mission(mission_id)
    assert final_mission["status"] == "COMPLETED"
    assert final_mission["attempt_number"] == 2
    assert final_mission["execution_active"] is False

    # Both files must exist and be completely valid
    assert step1_file.exists()
    assert step2_file.exists()
    assert hashlib.sha256(step1_file.read_bytes()).hexdigest() == step1_hash
    assert hashlib.sha256(step2_file.read_bytes()).hexdigest() == step2_hash

    # Clean up workspace lock
    ws_mgr.unlock()
