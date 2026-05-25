import pytest
import time
from pathlib import Path
from kairos.db import init_db
from kairos.task_queue import (
    register_task,
    mark_running,
    mark_completed,
    mark_failed,
    mark_stuck,
    requeue_for_retry,
    get_task_by_id,
    get_pending_tasks,
    get_running_tasks,
    get_failed_retriable_tasks,
    get_stuck_tasks,
    get_session_stats,
    get_kairos_state,
    reset_kairos_counter,
    TaskStatus,
    QueuedTask,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path=db_path)
    return db_path


def test_register_task_returns_id(db):
    task_id = register_task("s1", "My task", db_path=db)
    assert task_id > 0


def test_registered_task_is_pending(db):
    task_id = register_task("s1", "Pending task", db_path=db)
    tasks = get_task_by_id(task_id, db_path=db)
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.PENDING


def test_mark_running_transitions_from_pending(db):
    task_id = register_task("s1", "Running task", db_path=db)
    result = mark_running(task_id, db_path=db)
    assert result is True
    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.RUNNING
    assert task.started_at is not None


def test_mark_running_fails_if_not_pending(db):
    task_id = register_task("s1", "Task", db_path=db)
    mark_running(task_id, db_path=db)
    mark_completed(task_id, db_path=db)
    result = mark_running(task_id, db_path=db)  # Already COMPLETED
    assert result is False


def test_mark_completed_transitions_from_running(db):
    task_id = register_task("s1", "Task", db_path=db)
    mark_running(task_id, db_path=db)
    mark_completed(task_id, db_path=db)
    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at is not None


def test_mark_failed_increments_retry_count(db):
    task_id = register_task("s1", "Failing task", db_path=db)
    mark_failed(task_id, "JSON parse error", db_path=db)
    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.FAILED
    assert task.retry_count == 1
    assert "JSON parse error" in task.last_error


def test_requeue_for_retry_works_when_below_max(db):
    task_id = register_task("s1", "Retry task", max_retries=3, db_path=db)
    mark_failed(task_id, "error 1", db_path=db)
    result = requeue_for_retry(task_id, db_path=db)
    assert result is True
    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.PENDING


def test_requeue_blocked_when_max_retries_reached(db):
    task_id = register_task("s1", "Exhausted task", max_retries=1, db_path=db)
    mark_failed(task_id, "error 1", db_path=db)  # retry_count = 1
    result = requeue_for_retry(task_id, db_path=db)
    assert result is False


def test_get_pending_tasks_ordered_by_priority(db):
    register_task("s1", "Low priority", priority=8, db_path=db)
    register_task("s1", "High priority", priority=1, db_path=db)
    tasks = get_pending_tasks(db_path=db)
    assert tasks[0].priority == 1  # Highest priority (lowest number) first


def test_get_session_stats_counts_correctly(db):
    t1 = register_task("s1", "Task 1", db_path=db)
    t2 = register_task("s1", "Task 2", db_path=db)
    t3 = register_task("s1", "Task 3", db_path=db)
    mark_running(t1, db_path=db)
    mark_completed(t1, db_path=db)
    mark_failed(t2, "error", db_path=db)
    stats = get_session_stats("s1", db_path=db)
    assert stats["total"] == 3
    assert stats["completed"] == 1
    assert stats["failed"] == 1
    assert stats["pending"] == 1


def test_kairos_counter_increments_on_completion(db):
    state_before = get_kairos_state(db_path=db)
    t = register_task("s1", "Task", db_path=db)
    mark_running(t, db_path=db)
    mark_completed(t, db_path=db)
    state_after = get_kairos_state(db_path=db)
    assert state_after["tasks_since_consolidation"] == state_before["tasks_since_consolidation"] + 1


def test_reset_kairos_counter_zeros_count(db):
    t = register_task("s1", "Task", db_path=db)
    mark_running(t, db_path=db)
    mark_completed(t, db_path=db)
    reset_kairos_counter(db_path=db)
    state = get_kairos_state(db_path=db)
    assert state["tasks_since_consolidation"] == 0
    assert state["total_consolidations"] == 1
    assert state["last_consolidation_at"] is not None


def test_mark_stuck_sets_status(db):
    task_id = register_task("s1", "Long task", db_path=db)
    mark_running(task_id, db_path=db)
    mark_stuck(task_id, reason="test runaway", db_path=db)
    task = get_task_by_id(task_id, db_path=db)[0]
    assert task.status == TaskStatus.STUCK
    assert "runaway" in task.last_error
