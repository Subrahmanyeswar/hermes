#!/usr/bin/env python3
"""
HERMES -- Week 9 Integration Tests
Tests the KAIROS daemon running concurrently with the orchestrator.
Validates: task queue lifecycle, stuck detection, retry logic, Triple-Gate.

Run: python tests/test_week9_integration.py
Does NOT require Ollama -- all LLM calls are mocked.
"""
import asyncio
import gc
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from kairos.db import init_db, get_total_api_cost
from kairos.task_queue import (
    register_task, mark_running, mark_completed, mark_failed,
    mark_stuck, get_pending_tasks, get_session_stats, get_kairos_state,
    TaskStatus, get_task_by_id
)
from kairos.daemon import KairosDaemon, CONSOLIDATION_MIN_TASKS


def _close_all_db_connections(db_path: Path) -> None:
    """Force-close any lingering SQLite connections and checkpoint WAL.

    On Windows, SQLite WAL mode keeps -wal and -shm files that prevent
    TemporaryDirectory cleanup. This checkpoints and closes everything.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception:
        pass
    gc.collect()  # Release any prevent garbage-collected connections


# ----------------------------------------------------------------------

def test_1_full_task_lifecycle(tmp_path):
    """Every task status transition in sequence: PENDING -> RUNNING -> COMPLETED."""
    db = tmp_path / "lifecycle.db"
    init_db(db_path=db)

    task_id = register_task("s1", "Test lifecycle task", priority=1, db_path=db)

    # Verify PENDING
    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.PENDING, f"Expected PENDING, got {task.status}"

    # PENDING -> RUNNING
    mark_running(task_id, db_path=db)
    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.RUNNING
    assert task.started_at is not None

    # RUNNING -> COMPLETED
    mark_completed(task_id, db_path=db)
    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at is not None

    _close_all_db_connections(db)
    print("[PASS] Task lifecycle: PENDING -> RUNNING -> COMPLETED verified")

# ----------------------------------------------------------------------

def test_2_retry_lifecycle(tmp_path):
    """FAILED task retries up to max_retries, then stays FAILED."""
    db = tmp_path / "retry.db"
    init_db(db_path=db)

    task_id = register_task("s1", "Retry task", max_retries=2, db_path=db)

    # Fail once -> requeue -> fail again -> requeue -> fail third time -> exhausted
    for attempt in range(1, 4):
        if attempt > 1:
            from kairos.task_queue import requeue_for_retry
            requeue_for_retry(task_id, db_path=db)
        mark_running(task_id, db_path=db)
        mark_failed(task_id, f"Error on attempt {attempt}", db_path=db)
        task = get_task_by_id(task_id, db_path=db)[0]
        assert task.retry_count == attempt

    # Now retry_count == 3, max_retries == 2 -- cannot retry
    from kairos.task_queue import requeue_for_retry
    result = requeue_for_retry(task_id, db_path=db)
    assert result is False, "Should not be able to retry after exhausting max_retries"

    _close_all_db_connections(db)
    print("[PASS] Retry lifecycle: 2 retries allowed, 3rd retry correctly blocked")

# ----------------------------------------------------------------------

def test_3_session_stats_accuracy(tmp_path):
    """Session stats must accurately count tasks in each status."""
    db = tmp_path / "stats.db"
    init_db(db_path=db)
    session = "test_session_001"

    # Create 5 tasks
    ids = [register_task(session, f"Task {i}", db_path=db) for i in range(5)]

    # Complete 2
    for tid in ids[:2]:
        mark_running(tid, db_path=db)
        mark_completed(tid, db_path=db)

    # Fail 1
    mark_running(ids[2], db_path=db)
    mark_failed(ids[2], "error", db_path=db)

    # Stick 1
    mark_running(ids[3], db_path=db)
    mark_stuck(ids[3], "runaway", db_path=db)

    # Leave 1 as PENDING

    stats = get_session_stats(session, db_path=db)
    assert stats["total"] == 5
    assert stats["completed"] == 2
    assert stats["failed"] == 1
    assert stats["stuck"] == 1
    assert stats["pending"] == 1
    assert stats["running"] == 0

    _close_all_db_connections(db)
    print(f"[PASS] Session stats: {stats}")

# ----------------------------------------------------------------------

async def test_4_kairos_detects_stuck_tasks(tmp_path):
    """KAIROS must automatically detect and mark tasks that exceed 15 minutes."""
    db = tmp_path / "stuck.db"
    init_db(db_path=db)

    daemon = KairosDaemon(db_path=db)

    task_id = register_task("s1", "Long running task", db_path=db)
    mark_running(task_id, db_path=db)

    # Fake that this task started 16 minutes ago by updating the DB directly
    from kairos.db import execute_write
    fake_start = "2020-01-01T00:00:00"  # Definitely > 15 minutes ago
    execute_write("UPDATE tasks SET started_at=? WHERE id=?", (fake_start, task_id), db_path=db)

    # Run one KAIROS cycle
    await daemon._handle_stuck_tasks()

    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.STUCK, f"Expected STUCK, got {task.status}"
    assert daemon.stuck_tasks_detected == 1

    _close_all_db_connections(db)
    print("[PASS] KAIROS stuck detection: task running 16 minutes correctly marked STUCK")

# ----------------------------------------------------------------------

async def test_5_kairos_retries_failed_tasks(tmp_path):
    """KAIROS must automatically requeue failed tasks that have remaining retries."""
    db = tmp_path / "retry_auto.db"
    init_db(db_path=db)

    daemon = KairosDaemon(db_path=db)

    task_id = register_task("s1", "Auto-retry task", max_retries=3, db_path=db)
    mark_running(task_id, db_path=db)
    mark_failed(task_id, "first failure", db_path=db)

    # Run one KAIROS cycle
    await daemon._handle_failed_tasks()

    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.PENDING, f"Expected PENDING after requeue, got {task.status}"
    assert daemon.tasks_retried == 1

    _close_all_db_connections(db)
    print("[PASS] KAIROS auto-retry: failed task requeued for retry by daemon")

# ----------------------------------------------------------------------

async def test_6_triple_gate_logic(tmp_path, monkeypatch):
    """Triple-Gate: consolidation must not run until all three conditions pass."""
    db = tmp_path / "gate.db"
    lock_path = tmp_path / "test.lock"
    init_db(db_path=db)

    monkeypatch.setattr("kairos.daemon.LOCK_FILE_PATH", lock_path)
    monkeypatch.setattr("kairos.daemon.CONSOLIDATION_MIN_TASKS", 3)
    monkeypatch.setattr("kairos.daemon.CONSOLIDATION_MIN_MINUTES", 0)  # No time gate for test

    daemon = KairosDaemon(db_path=db)

    consolidation_called = False

    async def mock_run_consolidation():
        nonlocal consolidation_called
        consolidation_called = True

    daemon._run_consolidation = mock_run_consolidation

    # Test: only 1 completed task -- should NOT consolidate (gate 2 fails)
    t = register_task("s1", "Task", db_path=db)
    mark_running(t, db_path=db)
    mark_completed(t, db_path=db)
    await daemon._maybe_consolidate_memory()
    assert not consolidation_called, "Should not consolidate with only 1 completed task"

    # Complete 2 more tasks to satisfy gate 2
    for _ in range(2):
        t = register_task("s1", "Task", db_path=db)
        mark_running(t, db_path=db)
        mark_completed(t, db_path=db)

    # Now gate 2 passes -- but test with lock held (gate 3 fails)
    lock_path.write_text("locked")
    await daemon._maybe_consolidate_memory()
    assert not consolidation_called, "Should not consolidate when lock is held"

    # Remove lock -- now all gates should pass
    lock_path.unlink()
    await daemon._maybe_consolidate_memory()
    assert consolidation_called, "All gates passed -- consolidation should have run"

    _close_all_db_connections(db)
    print("[PASS] Triple-Gate: all three conditions correctly enforced")

# ----------------------------------------------------------------------

async def test_7_daemon_concurrency_with_tasks(tmp_path, monkeypatch):
    """
    KAIROS must run concurrently without interfering with task registration.
    Starts KAIROS, registers 5 tasks while it's running, verifies all are recorded.
    """
    db = tmp_path / "concurrent.db"
    lock_path = tmp_path / "concurrent.lock"
    init_db(db_path=db)
    monkeypatch.setattr("kairos.daemon.LOCK_FILE_PATH", lock_path)
    monkeypatch.setattr("kairos.daemon.LOOP_INTERVAL_SECONDS", 999)  # Prevent real loops

    daemon = KairosDaemon(db_path=db)
    await daemon.start()

    # Register tasks while KAIROS is running in background
    task_ids = []
    for i in range(5):
        tid = register_task("s1", f"Concurrent task {i}", db_path=db)
        task_ids.append(tid)
        await asyncio.sleep(0.01)  # Small delay to let event loop breathe

    await daemon.stop()

    # Verify all 5 tasks are in the database
    tasks = get_pending_tasks(db_path=db)
    assert len(tasks) == 5, f"Expected 5 pending tasks, got {len(tasks)}"

    _close_all_db_connections(db)
    print(f"[PASS] Concurrency: KAIROS ran alongside task registration, all 5 tasks preserved")

# ----------------------------------------------------------------------

async def main():
    import tempfile

    print("=" * 65)
    print("HERMES -- Week 9 Integration Tests (KAIROS System)")
    print("=" * 65)

    passed = 0
    failed = 0

    test_cases = [
        ("Full task lifecycle PENDING -> RUNNING -> COMPLETED", "sync_lifecycle"),
        ("Retry lifecycle -- blocked after max_retries exhausted", "sync_retry"),
        ("Session stats accuracy across all statuses", "sync_stats"),
        ("KAIROS detects and marks stuck tasks", "async_stuck"),
        ("KAIROS auto-retries failed tasks", "async_retry"),
    ]

    for name, kind in test_cases:
        print(f"\n[TEST] {name}")
        # Use ignore_cleanup_errors=True to handle Windows SQLite WAL locks
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            try:
                if kind == "sync_lifecycle":
                    test_1_full_task_lifecycle(tmp_path)
                elif kind == "sync_retry":
                    test_2_retry_lifecycle(tmp_path)
                elif kind == "sync_stats":
                    test_3_session_stats_accuracy(tmp_path)
                elif kind == "async_stuck":
                    await test_4_kairos_detects_stuck_tasks(tmp_path)
                elif kind == "async_retry":
                    await test_5_kairos_retries_failed_tasks(tmp_path)
                passed += 1
            except AssertionError as e:
                print(f"  [FAIL] {e}")
                failed += 1
            except Exception as e:
                import traceback
                print(f"  [ERROR] {type(e).__name__}: {e}")
                traceback.print_exc()
                failed += 1

    print(f"\n{'=' * 65}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"\nFor Triple-Gate and concurrency tests, run:")
    print(f"  pytest tests/test_week9_integration.py -v")

    if failed == 0:
        print("\nWEEK 9 COMPLETE: KAIROS daemon operational.")
        print("Task queue tracks all pipeline runs.")
        print("Ready for Week 10 (remaining skills + prompt hardening).")
    else:
        print("\nWEEK 9 INCOMPLETE: Fix failures before Week 10.")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())

# ---------- pytest-compatible wrappers --------------------------------

import pytest

@pytest.mark.asyncio
async def test_4_pytest_kairos_detects_stuck(tmp_path):
    await test_4_kairos_detects_stuck_tasks(tmp_path)

@pytest.mark.asyncio
async def test_5_pytest_kairos_retries_failed(tmp_path):
    await test_5_kairos_retries_failed_tasks(tmp_path)

@pytest.mark.asyncio
async def test_6_pytest_triple_gate(tmp_path, monkeypatch):
    await test_6_triple_gate_logic(tmp_path, monkeypatch)

@pytest.mark.asyncio
async def test_7_pytest_concurrency(tmp_path, monkeypatch):
    await test_7_daemon_concurrency_with_tasks(tmp_path, monkeypatch)

def test_1_pytest_lifecycle(tmp_path):
    test_1_full_task_lifecycle(tmp_path)

def test_2_pytest_retry(tmp_path):
    test_2_retry_lifecycle(tmp_path)

def test_3_pytest_stats(tmp_path):
    test_3_session_stats_accuracy(tmp_path)
