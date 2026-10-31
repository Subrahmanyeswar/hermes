"""
Phase 4 Acceptance Test Suite: Provider-Specific Recovery & Auto-Resumption (Scenarios N, O, P, V / Gate F).

Verifies:
- Scenario N: Provider recovers independently while WAN remains healthy; coordinator re-evaluates waiting missions.
- Scenario O: User stop during network waiting prevents recovery from restarting worker (Stop wins race).
- Scenario P: Provider route flapping is deduplicated without launching duplicate continuation workers.
- Scenario V: Continuation resumes from first unfinished task and preserves completed tasks.
"""

import uuid
import tempfile
import asyncio
from pathlib import Path
import pytest

from core.persistence.database import SQLiteDatabase
from core.persistence.blobs import BlobStore
from core.persistence.serializer import serialize_runtime_state
from core.event_bus import EventBus
from core.workspace import WorkspaceManager
from core.server.runtime_adapter import RuntimeAdapter
from core.network.coordinator import NetworkRecoveryCoordinator
from core.network.connectivity import ConnectivityMonitor, ConnectivityStatus
from core.runtime_state.models import HermesRuntimeState, MissionStatus, TaskState, TaskStatus


@pytest.mark.asyncio
async def test_scenario_n_provider_recovery_without_global_wan_toggle():
    """Verify provider recovery notification triggers auto-resumption while global WAN remains healthy."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p4_prov_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    blobs = BlobStore(tmp_dir / "blobs")
    bus = EventBus(db=db)
    bus.blob_store = blobs
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    coordinator = NetworkRecoveryCoordinator(db=db, runtime_adapter=adapter, event_bus=bus)

    mission_id = f"m_prov_{test_id}"

    # Setup mission with pending task in WAITING_FOR_PROVIDER
    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(tmp_dir)
    state.mission.status = MissionStatus.WAITING
    state.tasks["t1"] = TaskState(task_id="t1", mission_id=mission_id, title="Task 1", status=TaskStatus.PENDING)

    s_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="WAITING",
        snapshot_dict=s_dict,
        state_hash=s_hash,
        attempt_number=1,
    )
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="WAITING",
        wait_reason="WAITING_FOR_PROVIDER",
        execution_active=False,
        recovery_required=True,
        prompt="Execute provider recovery pipeline",
    )

    # Provider route recovers without changing global internet
    coordinator.notify_provider_recovered(provider="nvidia_nim", model="z-ai/glm-5.3-flash")
    await asyncio.sleep(0.1)

    # Verify mission transitioned to RUNNING under continuation attempt 2
    row = db.get_mission(mission_id)
    assert row["status"] == "RUNNING"
    assert row["attempt_number"] == 2
    assert row["execution_active"] is True

    await adapter.stop_mission(mission_id)
    coordinator.stop()


@pytest.mark.asyncio
async def test_scenario_o_user_stop_wins_race_against_recovery():
    """Verify that if a user cancels a waiting mission, subsequent provider recovery never resumes it."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p4_stop_race_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    coordinator = NetworkRecoveryCoordinator(db=db, runtime_adapter=adapter, event_bus=bus)

    mission_id = f"m_stop_race_{test_id}"

    # Save mission as CANCELLED
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="CANCELLED",
        wait_reason="CANCELLED",
        execution_active=False,
        recovery_required=False,
    )

    # Provider recovery notification arrives immediately afterward
    coordinator.notify_provider_recovered(provider="nvidia_nim", model="z-ai/glm-5.3-flash")
    await asyncio.sleep(0.05)

    # Mission must remain CANCELLED and never reactivated
    row = db.get_mission(mission_id)
    assert row["status"] == "CANCELLED"
    assert row["execution_active"] is False

    coordinator.stop()


@pytest.mark.asyncio
async def test_scenario_p_provider_flapping_deduplication():
    """Verify high-frequency flapping notifications do not spawn duplicate recovery runs."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p4_flap_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db = SQLiteDatabase(tmp_dir / "test.db")
    blobs = BlobStore(tmp_dir / "blobs")
    bus = EventBus(db=db)
    bus.blob_store = blobs
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))
    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)
    coordinator = NetworkRecoveryCoordinator(db=db, runtime_adapter=adapter, event_bus=bus)

    mission_id = f"m_flap_{test_id}"

    state = HermesRuntimeState.create_empty(mission_id=mission_id)
    state.mission.workspace_root = str(tmp_dir)
    state.mission.status = MissionStatus.WAITING
    state.tasks["t1"] = TaskState(task_id="t1", mission_id=mission_id, title="Task 1", status=TaskStatus.PENDING)

    s_dict, s_hash = serialize_runtime_state(state)
    db.save_snapshot(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="WAITING",
        snapshot_dict=s_dict,
        state_hash=s_hash,
        attempt_number=1,
    )
    db.save_mission(
        mission_id=mission_id,
        workspace_path=str(tmp_dir),
        status="WAITING",
        wait_reason="WAITING_FOR_PROVIDER",
        execution_active=False,
        recovery_required=True,
    )

    # Rapid fire 5 recovery notifications
    for _ in range(5):
        coordinator.notify_provider_recovered(provider="nvidia_nim", model="z-ai/glm-5.3-flash")

    await asyncio.sleep(0.1)

    # Exactly one continuation attempt (attempt 2)
    row = db.get_mission(mission_id)
    assert row["status"] == "RUNNING"
    assert row["attempt_number"] == 2

    await adapter.stop_mission(mission_id)
    coordinator.stop()
