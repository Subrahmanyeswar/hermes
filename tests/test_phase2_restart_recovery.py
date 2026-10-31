"""
Phase 2 Test Suite: Restart, Crash Recovery & Cold Resume.

Verifies:
- Scenario E: Process crash simulation and resume
- Scenario J: Startup reconciliation (marking dead processes and orphaned tasks)
- Cold restart resume preserving completed progress
"""

import os
import sys
import uuid
import tempfile
import asyncio
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.event_bus import EventBus
from core.workspace import WorkspaceManager
from core.server.runtime_adapter import RuntimeAdapter
from core.persistence.recovery import RecoveryEngine
from core.persistence.blobs import BlobStore
from core.checkpoints.engine import CheckpointEngine
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import MissionStatus


@pytest.mark.asyncio
async def test_scenario_j_startup_reconciliation_clears_stale_pid_missions():
    """Verify that upon adapter startup, missions recorded with non-existent PIDs or execution_active=True are marked recovery_required / not executing."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_startup_recon_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()

    # Pre-seed a mission that has execution_active=True
    mission_id = f"m_stale_{test_id}"
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="RUNNING",
        execution_active=True,
    )

    # Initialize RuntimeAdapter - restore_persisted_missions runs during init
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)

    # Worker liveness check must report false
    assert adapter.is_worker_alive(mission_id) is False

    # Database record must have execution_active = False and recovery_required = True
    m_row = db.get_mission(mission_id)
    assert m_row["execution_active"] == 0
    assert m_row["recovery_required"] == 1


@pytest.mark.asyncio
async def test_scenario_e_cold_restart_resume_preserves_completed_tasks():
    """Verify that after an abrupt halt/crash, a mission can formulate a resume plan and resume without re-running completed tasks."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_cold_resume_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Create a real workspace file for task 1
    (tmp_dir / "step1.txt").write_text("done step 1", encoding="utf-8")

    db_path = tmp_dir / "test.db"
    db = SQLiteDatabase(db_path)
    blob_dir = tmp_dir / "blobs"
    blob_store = BlobStore(blob_dir)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    bus = EventBus(db=db)
    chk_engine = CheckpointEngine(base_dir=tmp_dir / "checkpoints", workspace_root=tmp_dir, db=db, blob_store=blob_store, event_bus=bus)
    recovery_engine = RecoveryEngine(
        db=db,
        blob_store=blob_store,
        checkpoint_engine=chk_engine,
        workspace_manager=ws_mgr,
    )

    mission_id = f"m_crash_{test_id}"

    # Record mission state before crash with 1 completed task and 1 pending task
    store = bus.get_or_create_state(mission_id)
    bus.publish_durable(HermesEvent(
        event_type=EventType.MISSION_STARTED,
        mission_id=mission_id,
        attempt_number=1,
    ))
    bus.publish_durable(HermesEvent(
        event_type=EventType.TASK_STARTED,
        mission_id=mission_id,
        attempt_number=1,
        payload={"task_id": "task_1", "description": "Write step 1"},
    ))
    bus.publish_durable(HermesEvent(
        event_type=EventType.TASK_COMPLETED,
        mission_id=mission_id,
        attempt_number=1,
        payload={"task_id": "task_1", "result": "step1.txt created"},
    ))
    bus.publish_durable(HermesEvent(
        event_type=EventType.TASK_STARTED,
        mission_id=mission_id,
        attempt_number=1,
        payload={"task_id": "task_2", "description": "Write step 2"},
    ))

    # Persist snapshot
    snap = store.get_snapshot()
    from core.persistence.serializer import serialize_runtime_state
    s_dict, s_hash = serialize_runtime_state(snap)
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="RUNNING",
        attempt_number=1,
        execution_active=True,
    )
    db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="RUNNING",
        snapshot_dict=s_dict,
        state_hash=s_hash,
        attempt_number=1,
    )

    # Simulate CRASH: new adapter instance, no active memory tasks
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    assert adapter.is_worker_alive(mission_id) is False

    # Formulate resume plan
    plan = recovery_engine.formulate_resume_plan(mission_id)
    assert plan.can_resume is True
    # The plan must recognize that task_1 is already done and resume from task_2
    assert "task_1" in plan.completed_tasks
    assert plan.target_task_id == "task_2"
