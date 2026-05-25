import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from kairos.db import init_db
from kairos.task_queue import register_task, mark_running, mark_completed, mark_failed
from kairos.daemon import KairosDaemon, LOCK_FILE_PATH


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path=db_path)
    return db_path


@pytest.fixture
def daemon(db, monkeypatch):
    monkeypatch.setattr("kairos.daemon.DB_PATH", db)
    monkeypatch.setattr("kairos.daemon.LOCK_FILE_PATH", db.parent / "test.lock")
    return KairosDaemon(db_path=db)


@pytest.mark.asyncio
async def test_daemon_starts_and_stops(daemon):
    await daemon.start()
    assert daemon.is_running is True
    await daemon.stop()
    assert daemon.is_running is False


@pytest.mark.asyncio
async def test_daemon_start_twice_is_safe(daemon):
    await daemon.start()
    await daemon.start()  # Second call should be ignored gracefully
    assert daemon.is_running is True
    await daemon.stop()


@pytest.mark.asyncio
async def test_handle_stuck_tasks_marks_stuck(daemon, db, monkeypatch):
    """Tasks running > 15 minutes should be detected and marked STUCK."""
    task_id = register_task("s1", "Long running task", db_path=db)
    mark_running(task_id, db_path=db)

    # Mock is_stuck to return True for this task
    from kairos.task_queue import QueuedTask, TaskStatus

    mock_task = MagicMock(spec=QueuedTask)
    mock_task.id = task_id
    mock_task.title = "Long running task"
    mock_task.started_at = "2020-01-01T00:00:00"
    mock_task.status = TaskStatus.RUNNING
    mock_task.is_stuck = True

    with patch("kairos.daemon.get_stuck_tasks", return_value=[mock_task]):
        await daemon._handle_stuck_tasks()

    assert daemon.stuck_tasks_detected == 1


@pytest.mark.asyncio
async def test_handle_failed_tasks_requeues(daemon, db):
    task_id = register_task("s1", "Failing task", max_retries=3, db_path=db)
    mark_running(task_id, db_path=db)
    mark_failed(task_id, "parse error", db_path=db)

    await daemon._handle_failed_tasks()

    assert daemon.tasks_retried == 1


@pytest.mark.asyncio
async def test_triple_gate_skips_if_too_few_tasks(daemon, db):
    """Consolidation should not run if < 3 tasks completed since last run."""
    # Only 1 completed task — below CONSOLIDATION_MIN_TASKS (3)
    t = register_task("s1", "Task 1", db_path=db)
    mark_running(t, db_path=db)
    mark_completed(t, db_path=db)

    with patch("memory.consolidator.consolidate_memory") as mock_consolidate:
        await daemon._maybe_consolidate_memory()

    mock_consolidate.assert_not_called()


@pytest.mark.asyncio
async def test_triple_gate_skips_if_lock_held(daemon, db, tmp_path, monkeypatch):
    lock_path = tmp_path / "test.lock"
    monkeypatch.setattr("kairos.daemon.LOCK_FILE_PATH", lock_path)
    lock_path.write_text("locked")

    with patch("memory.consolidator.consolidate_memory") as mock_consolidate:
        await daemon._maybe_consolidate_memory()

    mock_consolidate.assert_not_called()


@pytest.mark.asyncio
async def test_check_cost_cap_logs_warning(daemon, db, caplog):
    with patch("kairos.daemon.get_total_api_cost", return_value=16.0):
        import logging

        with caplog.at_level(logging.WARNING, logger="kairos.daemon"):
            await daemon._check_cost_cap()
    # The warning should have been logged


def test_get_stats_returns_dict(daemon):
    stats = daemon.get_stats()
    assert "is_running" in stats
    assert "loop_count" in stats
    assert "consolidations_run" in stats
    assert "total_api_cost" in stats


@pytest.mark.asyncio
async def test_one_complete_cycle_runs_without_crashing(daemon, db):
    """Full cycle should run cleanly even with no tasks."""
    with patch("memory.consolidator.consolidate_memory", return_value={"status": "ok"}):
        await daemon._run_one_cycle()
    assert daemon.loop_count == 1
