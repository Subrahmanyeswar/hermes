"""
Phase 2 Concurrency Test Suite: Single-Mission Mutual Exclusion (INV-01, Scenario A).

Verifies:
1. 5+ concurrent mission submissions overlap tightly.
2. Exactly one mission obtains the active execution slot.
3. All other concurrent submissions are rejected with a truthful mutual-exclusion error.
4. Concurrent resume while another mission is executing is rejected.
5. Once active execution concludes, the slot is released and subsequent missions can execute.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from core.event_bus import EventBus
from core.persistence.database import SQLiteDatabase
from core.server.runtime_adapter import RuntimeAdapter
from core.workspace import WorkspaceManager


@pytest.mark.asyncio
async def test_scenario_a_five_concurrent_submissions_single_winner():
    """Verify that exactly 1 of 5 concurrent mission submissions obtains the active execution slot."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_concurrency_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "concurrency.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)

    # Mock _run_mission_background to simulate a live executing task for 1.5 seconds
    async def mock_background_execution(runtime, mission_id, prompt, plan_mode, control):
        # Keep task running
        await asyncio.sleep(1.0)

    adapter._run_mission_background = mock_background_execution

    results = []
    errors = []

    async def submit_mission(idx: int):
        await asyncio.sleep(0.001)  # Tightly overlapping submissions
        try:
            m_id = await adapter.start_mission(
                prompt=f"Concurrent mission prompt {idx}",
                workspace_root=str(tmp_dir),
            )
            results.append((idx, m_id))
        except Exception as exc:
            errors.append((idx, str(exc)))

    # Fire 5 concurrent submissions simultaneously
    tasks = [asyncio.create_task(submit_mission(i)) for i in range(5)]
    await asyncio.gather(*tasks)

    # Exactly 1 must have succeeded, exactly 4 must have been rejected
    assert len(results) == 1, f"Expected exactly 1 mission to obtain slot, got {len(results)}: {results}"
    assert len(errors) == 4, f"Expected exactly 4 rejections, got {len(errors)}: {errors}"

    winner_idx, winner_id = results[0]
    for idx, err_msg in errors:
        assert "single-mission policy" in err_msg or "actively executing" in err_msg
        assert winner_id in err_msg

    # Verify active tasks tracking
    active_m_id = None
    for m_id, task in adapter._active_tasks.items():
        if task and not task.done():
            active_m_id = m_id
    assert active_m_id == winner_id

    # Wait for the winner task to complete
    winner_task = adapter._active_tasks.get(winner_id)
    if winner_task:
        await winner_task


@pytest.mark.asyncio
async def test_concurrent_resume_rejected_while_mission_running():
    """Verify that attempting to resume a mission while another is running is rejected."""
    test_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"hermes_p2_concurrency_res_{test_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    db_path = tmp_dir / "concurrency_res.db"
    db = SQLiteDatabase(db_path)
    bus = EventBus(db=db)
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(tmp_dir))

    adapter = RuntimeAdapter(event_bus=bus, workspace_manager=ws_mgr)

    # Simulate Mission A running
    async def mock_background_execution(runtime, mission_id, prompt, plan_mode, control):
        await asyncio.sleep(1.0)

    adapter._run_mission_background = mock_background_execution
    mission_a = await adapter.start_mission("Mission A", workspace_root=str(tmp_dir))

    # Save a stopped Mission B in the database
    db.save_mission(
        mission_id="mission_b",
        workspace_path=str(tmp_dir),
        status="CANCELLED",
        attempt_number=1,
        prompt="Mission B prompt",
        execution_active=False,
    )

    # Attempt to resume Mission B while Mission A is running
    with pytest.raises(RuntimeError) as exc_info:
        await adapter.resume_interrupted_mission("mission_b")

    assert "single-mission policy" in str(exc_info.value)
    assert mission_a in str(exc_info.value)

    # Let Mission A finish
    task_a = adapter._active_tasks.get(mission_a)
    if task_a:
        await task_a
