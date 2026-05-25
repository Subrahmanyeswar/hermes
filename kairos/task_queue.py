# kairos/task_queue.py
# Task queue interface for HERMES.
# The orchestrator registers tasks here at the start of each pipeline run.
# KAIROS daemon reads from here to find PENDING, STUCK, and FAILED tasks.
# All writes go through kairos/db.py — never import sqlite3 directly here.
# Task lifecycle: PENDING → RUNNING → COMPLETED or FAILED or STUCK

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger

from kairos.db import execute_write, execute_read, DB_PATH


class TaskStatus(str, Enum):
    PENDING   = "PENDING"
    RUNNING   = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED    = "FAILED"
    STUCK     = "STUCK"


@dataclass
class QueuedTask:
    """A task row from the database."""

    id: int
    session_id: str
    title: str
    status: TaskStatus
    priority: int
    complexity: float
    retry_count: int
    max_retries: int
    description: str = ""
    last_error: Optional[str] = None
    tool_name: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> QueuedTask:
        """Build from a sqlite3.Row object."""
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            status=TaskStatus(row["status"]),
            priority=row["priority"],
            complexity=row["complexity"],
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            description=row["description"] or "",
            last_error=row["last_error"],
            tool_name=row["tool_name"],
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    @property
    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries and self.status == TaskStatus.FAILED

    @property
    def is_stuck(self) -> bool:
        """A RUNNING task with no update in over 15 minutes is stuck."""
        if self.status != TaskStatus.RUNNING or not self.started_at:
            return False
        try:
            start = datetime.fromisoformat(self.started_at)
            elapsed_minutes = (datetime.now() - start).total_seconds() / 60
            return elapsed_minutes > 15
        except (ValueError, TypeError):
            return False


# ── Task registration ────────────────────────────────────────────────────────


def register_task(
    session_id: str,
    title: str,
    description: str = "",
    priority: int = 5,
    complexity: float = 0.5,
    max_retries: int = 3,
    tool_name: str | None = None,
    db_path: Path = DB_PATH,
) -> int:
    """Register a new task at the start of a pipeline run. Returns the new task ID."""
    task_id = execute_write(
        """INSERT INTO tasks (session_id, title, description, status, priority, complexity, max_retries, tool_name)
           VALUES (?, ?, ?, 'PENDING', ?, ?, ?, ?)""",
        (session_id, title, description, priority, complexity, max_retries, tool_name),
        db_path=db_path,
    )
    logger.debug(f"TaskQueue: registered task {task_id} | '{title[:50]}' | priority={priority}")
    return task_id


# ── State transitions ────────────────────────────────────────────────────────


def mark_running(task_id: int, db_path: Path = DB_PATH) -> bool:
    """Transition a PENDING task to RUNNING. Returns False if not in PENDING state."""
    rows_affected = execute_write(
        """UPDATE tasks SET status='RUNNING', started_at=datetime('now'), updated_at=datetime('now')
           WHERE id=? AND status='PENDING'""",
        (task_id,),
        db_path=db_path,
    )
    if rows_affected == 0:
        logger.warning(f"TaskQueue: could not mark task {task_id} as RUNNING (not in PENDING state)")
        return False
    logger.debug(f"TaskQueue: task {task_id} → RUNNING")
    return True


def mark_completed(task_id: int, db_path: Path = DB_PATH) -> bool:
    """Transition a RUNNING task to COMPLETED."""
    rows_affected = execute_write(
        """UPDATE tasks SET status='COMPLETED', completed_at=datetime('now'), updated_at=datetime('now')
           WHERE id=? AND status='RUNNING'""",
        (task_id,),
        db_path=db_path,
    )
    logger.info(f"TaskQueue: task {task_id} → COMPLETED")
    _increment_kairos_counter(db_path)
    return rows_affected > 0


def mark_failed(task_id: int, error: str, db_path: Path = DB_PATH) -> bool:
    """Transition a task to FAILED and record the error."""
    execute_write(
        """UPDATE tasks
           SET status='FAILED', last_error=?, retry_count=retry_count+1, updated_at=datetime('now')
           WHERE id=?""",
        (error[:1000], task_id),
        db_path=db_path,
    )
    logger.warning(f"TaskQueue: task {task_id} → FAILED | error={error[:80]!r}")
    return True


def mark_stuck(
    task_id: int,
    reason: str = "Runaway detection: exceeded 15-minute limit",
    db_path: Path = DB_PATH,
) -> bool:
    """Transition a task to STUCK with a reason."""
    execute_write(
        """UPDATE tasks SET status='STUCK', last_error=?, updated_at=datetime('now')
           WHERE id=?""",
        (reason, task_id),
        db_path=db_path,
    )
    logger.warning(f"TaskQueue: task {task_id} → STUCK | reason={reason[:80]}")
    return True


def requeue_for_retry(task_id: int, db_path: Path = DB_PATH) -> bool:
    """Move a FAILED task back to PENDING for retry.

    Only works if retry_count < max_retries.
    """
    tasks = get_task_by_id(task_id, db_path)
    if not tasks:
        return False
    task = tasks[0]
    if not task.can_retry:
        logger.warning(
            f"TaskQueue: task {task_id} cannot retry (count={task.retry_count}/{task.max_retries})"
        )
        return False
    execute_write(
        """UPDATE tasks SET status='PENDING', started_at=NULL, updated_at=datetime('now')
           WHERE id=?""",
        (task_id,),
        db_path=db_path,
    )
    logger.info(f"TaskQueue: task {task_id} requeued for retry #{task.retry_count + 1}")
    return True


# ── Queries ──────────────────────────────────────────────────────────────────


def get_task_by_id(task_id: int, db_path: Path = DB_PATH) -> list[QueuedTask]:
    """Fetch a single task by ID. Returns a list (empty if not found)."""
    rows = execute_read("SELECT * FROM tasks WHERE id=?", (task_id,), db_path=db_path)
    return [QueuedTask.from_row(r) for r in rows]


def get_pending_tasks(db_path: Path = DB_PATH) -> list[QueuedTask]:
    """Get all PENDING tasks, ordered by priority (lowest number = highest priority) then creation time."""
    rows = execute_read(
        "SELECT * FROM tasks WHERE status='PENDING' ORDER BY priority ASC, created_at ASC",
        db_path=db_path,
    )
    return [QueuedTask.from_row(r) for r in rows]


def get_running_tasks(db_path: Path = DB_PATH) -> list[QueuedTask]:
    """Get all RUNNING tasks, ordered by start time."""
    rows = execute_read(
        "SELECT * FROM tasks WHERE status='RUNNING' ORDER BY started_at ASC",
        db_path=db_path,
    )
    return [QueuedTask.from_row(r) for r in rows]


def get_failed_retriable_tasks(db_path: Path = DB_PATH) -> list[QueuedTask]:
    """Get all FAILED tasks that still have retries remaining."""
    rows = execute_read(
        "SELECT * FROM tasks WHERE status='FAILED' AND retry_count < max_retries ORDER BY priority ASC",
        db_path=db_path,
    )
    return [QueuedTask.from_row(r) for r in rows]


def get_stuck_tasks(db_path: Path = DB_PATH) -> list[QueuedTask]:
    """Find tasks that are RUNNING but have exceeded 15 minutes without completion."""
    running = get_running_tasks(db_path)
    return [t for t in running if t.is_stuck]


# ── Session stats ────────────────────────────────────────────────────────────


def get_session_stats(session_id: str, db_path: Path = DB_PATH) -> dict:
    """Get a summary of task counts for a session."""
    rows = execute_read(
        """SELECT
               COUNT(*) as total,
               SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) as completed,
               SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) as failed,
               SUM(CASE WHEN status='STUCK' THEN 1 ELSE 0 END) as stuck,
               SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) as pending,
               SUM(CASE WHEN status='RUNNING' THEN 1 ELSE 0 END) as running
           FROM tasks WHERE session_id=?""",
        (session_id,),
        db_path=db_path,
    )
    row = rows[0] if rows else None
    return {
        "session_id": session_id,
        "total": row["total"] if row else 0,
        "completed": row["completed"] if row else 0,
        "failed": row["failed"] if row else 0,
        "stuck": row["stuck"] if row else 0,
        "pending": row["pending"] if row else 0,
        "running": row["running"] if row else 0,
    }


# ── KAIROS consolidation tracking ───────────────────────────────────────────


def _increment_kairos_counter(db_path: Path = DB_PATH) -> None:
    """Increment the tasks_since_consolidation counter in kairos_state.

    Called after every COMPLETED task.
    """
    execute_write(
        "UPDATE kairos_state SET tasks_since_consolidation = tasks_since_consolidation + 1 WHERE id=1",
        db_path=db_path,
    )


def get_kairos_state(db_path: Path = DB_PATH) -> dict:
    """Get the current KAIROS daemon state (consolidation counters)."""
    rows = execute_read("SELECT * FROM kairos_state WHERE id=1", db_path=db_path)
    if not rows:
        return {
            "last_consolidation_at": None,
            "tasks_since_consolidation": 0,
            "total_consolidations": 0,
        }
    r = rows[0]
    return {
        "last_consolidation_at": r["last_consolidation_at"],
        "tasks_since_consolidation": r["tasks_since_consolidation"],
        "total_consolidations": r["total_consolidations"],
    }


def reset_kairos_counter(db_path: Path = DB_PATH) -> None:
    """Reset the tasks_since_consolidation counter and record the consolidation timestamp.

    Called by KAIROS after each consolidation run.
    """
    execute_write(
        """UPDATE kairos_state
           SET tasks_since_consolidation=0,
               last_consolidation_at=datetime('now'),
               total_consolidations=total_consolidations+1
           WHERE id=1""",
        db_path=db_path,
    )
