# ui/viewmodels/tasks.py
"""Task Queue ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class TaskItemViewModel:
    task_id: str
    order_index: int
    title: str
    status: str            # PENDING, RUNNING, COMPLETED, FAILED, BLOCKED, CANCELLED
    attempts: int = 0
    repair_state: str = "NOT_REQUIRED"
    failure_reason: Optional[str] = None


@dataclass(frozen=True)
class TaskQueueViewModel:
    tasks: Tuple[TaskItemViewModel, ...] = ()
    current_task_id: Optional[str] = None
    completed_count: int = 0
    total_count: int = 0
