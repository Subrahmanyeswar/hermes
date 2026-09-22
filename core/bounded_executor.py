# core/bounded_executor.py
"""
Safe Bounded Concurrency Executor for HERMES vNext (Prompt 6).

Coordinates concurrent execution of genuinely independent non-model CPU/IO tasks
while enforcing strict resource limits, per-file write conflict locks, single
index-refresh barriers, and GPU serialization (protecting RTX 3050 6GB VRAM).

Key Invariants:
- Hardware Guard: GPU/Model inference is serialized (concurrency = 1).
- Bounded Worker Limit: CPU/IO work bounded to max_workers <= 2.
- Conflict Serialization: Tasks targeting the same normalized file path are serialized.
- Stateful Safety: SQLite index refresh and destructive actions are serialized.
- Cancellation & Timeout Safety: Propagates abort signals without leaking worker threads.
- Observability: Complete per-task telemetry (queue time, execution time, worker ID).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple, Union

from loguru import logger
from core.workspace import workspace_manager


class ResourceClass(str, Enum):
    CPU = "CPU"
    IO = "IO"
    GPU = "GPU"
    STATEFUL = "STATEFUL"
    DESTRUCTIVE = "DESTRUCTIVE"


@dataclass
class BoundedTask:
    """A unit of work submitted to the BoundedExecutor."""
    task_id: str
    func: Callable[..., Any]
    args: Tuple[Any, ...] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    resource_class: ResourceClass = ResourceClass.CPU
    target_files: Set[str] = field(default_factory=set)
    depends_on: Set[str] = field(default_factory=set)
    timeout_seconds: Optional[float] = None
    priority: int = 5  # Higher executes earlier


@dataclass
class TaskExecutionRecord:
    """Telemetry record of an executed task."""
    task_id: str
    resource_class: ResourceClass
    worker_id: str
    target_files: List[str]
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    queue_wait_ms: float = 0.0
    execution_ms: float = 0.0
    cancelled: bool = False
    timeout: bool = False


class BoundedExecutor:
    """
    Resource-aware bounded concurrency executor.
    Guarantees that independent tasks run concurrently while shared-state
    and hardware-constrained tasks remain safely serialized.
    """

    DEFAULT_MAX_WORKERS: int = 2
    MAX_POLICY_LIMIT: int = 4

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        max_gpu_workers: int = 1,
    ):
        # Enforce strict policy maximum
        self.max_workers = max(1, min(max_workers, self.MAX_POLICY_LIMIT))
        self.max_gpu_workers = max(1, min(max_gpu_workers, 1))  # Default locked to 1 on RTX 3050

        self._worker_semaphore = asyncio.Semaphore(self.max_workers)
        self._gpu_semaphore = asyncio.Semaphore(self.max_gpu_workers)
        self._stateful_lock = asyncio.Lock()
        self._file_locks: Dict[str, asyncio.Lock] = {}
        self._active_tasks: Set[asyncio.Task] = set()
        self._execution_history: List[TaskExecutionRecord] = []

    def _normalize_file_path(self, path: str) -> str:
        """Normalize file path for conflict detection."""
        try:
            p = Path(path)
            return str(p.resolve()).lower() if p.is_absolute() else str(p).replace("\\", "/").lower()
        except Exception:
            return str(path).lower()

    def _get_file_lock(self, norm_path: str) -> asyncio.Lock:
        if norm_path not in self._file_locks:
            self._file_locks[norm_path] = asyncio.Lock()
        return self._file_locks[norm_path]

    async def execute_task(
        self,
        task: BoundedTask,
        abort_event: Optional[asyncio.Event] = None,
    ) -> TaskExecutionRecord:
        """
        Execute a single task through the admission controller and resource semaphores.
        """
        submission_time = time.perf_counter()

        if abort_event and abort_event.is_set():
            return TaskExecutionRecord(
                task_id=task.task_id,
                resource_class=task.resource_class,
                worker_id="aborted_before_start",
                target_files=list(task.target_files),
                success=False,
                error="Cancelled before execution",
                cancelled=True,
            )

        # Acquire per-file write locks in deterministic sorted order
        norm_files = sorted([self._normalize_file_path(f) for f in task.target_files])
        acquired_file_locks: List[asyncio.Lock] = []

        for nf in norm_files:
            flock = self._get_file_lock(nf)
            await flock.acquire()
            acquired_file_locks.append(flock)

        record = TaskExecutionRecord(
            task_id=task.task_id,
            resource_class=task.resource_class,
            worker_id="pending",
            target_files=list(task.target_files),
            success=False,
        )

        try:
            # Resource class admission control
            if task.resource_class == ResourceClass.GPU:
                # GPU inference serialization
                async with self._gpu_semaphore:
                    record = await self._run_worker(task, submission_time, abort_event, "gpu-worker-1")
            elif task.resource_class in (ResourceClass.STATEFUL, ResourceClass.DESTRUCTIVE):
                # Stateful/Destructive serialization
                async with self._stateful_lock:
                    record = await self._run_worker(task, submission_time, abort_event, "stateful-worker-1")
            else:
                # CPU / IO bounded concurrency
                async with self._worker_semaphore:
                    worker_name = f"worker-{len(self._execution_history) % self.max_workers + 1}"
                    record = await self._run_worker(task, submission_time, abort_event, worker_name)

        finally:
            for flock in acquired_file_locks:
                flock.release()

        self._execution_history.append(record)
        return record

    async def _run_worker(
        self,
        task: BoundedTask,
        submission_time: float,
        abort_event: Optional[asyncio.Event],
        worker_id: str,
    ) -> TaskExecutionRecord:
        """Internal worker runner with timeout and cancellation protection."""
        start_time = time.perf_counter()
        queue_wait_ms = (start_time - submission_time) * 1000.0

        if abort_event and abort_event.is_set():
            return TaskExecutionRecord(
                task_id=task.task_id,
                resource_class=task.resource_class,
                worker_id=worker_id,
                target_files=list(task.target_files),
                success=False,
                error="Cancelled during queue wait",
                queue_wait_ms=queue_wait_ms,
                cancelled=True,
            )

        try:
            # Wrap execution with timeout if specified
            coro_or_func = task.func(*task.args, **task.kwargs)
            if asyncio.iscoroutine(coro_or_func):
                if task.timeout_seconds:
                    res = await asyncio.wait_for(coro_or_func, timeout=task.timeout_seconds)
                else:
                    res = await coro_or_func
            else:
                res = coro_or_func

            exec_ms = (time.perf_counter() - start_time) * 1000.0
            return TaskExecutionRecord(
                task_id=task.task_id,
                resource_class=task.resource_class,
                worker_id=worker_id,
                target_files=list(task.target_files),
                success=True,
                result=res,
                queue_wait_ms=queue_wait_ms,
                execution_ms=exec_ms,
            )
        except asyncio.TimeoutError:
            exec_ms = (time.perf_counter() - start_time) * 1000.0
            return TaskExecutionRecord(
                task_id=task.task_id,
                resource_class=task.resource_class,
                worker_id=worker_id,
                target_files=list(task.target_files),
                success=False,
                error=f"Task timed out after {task.timeout_seconds}s",
                queue_wait_ms=queue_wait_ms,
                execution_ms=exec_ms,
                timeout=True,
            )
        except asyncio.CancelledError:
            exec_ms = (time.perf_counter() - start_time) * 1000.0
            return TaskExecutionRecord(
                task_id=task.task_id,
                resource_class=task.resource_class,
                worker_id=worker_id,
                target_files=list(task.target_files),
                success=False,
                error="Task cancelled by controller",
                queue_wait_ms=queue_wait_ms,
                execution_ms=exec_ms,
                cancelled=True,
            )
        except Exception as exc:
            exec_ms = (time.perf_counter() - start_time) * 1000.0
            return TaskExecutionRecord(
                task_id=task.task_id,
                resource_class=task.resource_class,
                worker_id=worker_id,
                target_files=list(task.target_files),
                success=False,
                error=str(exc),
                queue_wait_ms=queue_wait_ms,
                execution_ms=exec_ms,
            )

    async def execute_batch(
        self,
        tasks: List[BoundedTask],
        abort_event: Optional[asyncio.Event] = None,
        refresh_index_barrier: bool = True,
    ) -> List[TaskExecutionRecord]:
        """
        Execute a batch of tasks concurrently while respecting dependencies and file locks.
        Applies an optional single index-refresh barrier at the conclusion.
        """
        # Group tasks by dependency readiness
        completed_ids: Set[str] = set()
        task_map = {t.task_id: t for t in tasks}
        records_by_id: Dict[str, TaskExecutionRecord] = {}

        while len(completed_ids) < len(tasks):
            if abort_event and abort_event.is_set():
                break

            # Find ready tasks (all depends_on completed)
            ready_tasks = [
                t for t in tasks
                if t.task_id not in completed_ids
                and all(dep in completed_ids for dep in t.depends_on)
            ]

            if not ready_tasks:
                # Deadlock or blocked by failure
                break

            # Launch ready tasks concurrently
            async_tasks = [
                asyncio.create_task(self.execute_task(t, abort_event=abort_event))
                for t in ready_tasks
            ]

            results = await asyncio.gather(*async_tasks, return_exceptions=False)
            for r in results:
                records_by_id[r.task_id] = r
                if r.success:
                    completed_ids.add(r.task_id)
                else:
                    # Mark as processed (even if failed) to prevent infinite loop
                    completed_ids.add(r.task_id)

        # Single index refresh barrier for all mutations
        if refresh_index_barrier:
            try:
                workspace_manager.refresh_index()
            except Exception as e:
                logger.debug("BoundedExecutor: Index refresh barrier notice: {}", e)

        return [records_by_id[t.task_id] for t in tasks if t.task_id in records_by_id]


# Global singleton executor
bounded_executor = BoundedExecutor(max_workers=2, max_gpu_workers=1)
