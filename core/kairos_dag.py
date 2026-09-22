# core/kairos_dag.py
"""
KAIROS DAG Execution Engine for HERMES vNext (Phase 10).
Provides true dependency-aware, resource-constrained concurrent execution
with cycle detection, dynamic unblocking, file write conflict locks,
and GPU model serialization (preventing VRAM thrashing on RTX 3050 6GB).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple, Callable

from loguru import logger
from config.model_config import KAIROS_DAG_ENABLED, KAIROS_MAX_CONCURRENCY


class TaskState(str, Enum):
    BLOCKED = "BLOCKED"
    READY = "READY"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class TaskNode:
    task_id: str
    title: str
    description: str = ""
    depends_on: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    state: TaskState = TaskState.BLOCKED
    read_files: Set[str] = field(default_factory=set)
    write_files: Set[str] = field(default_factory=set)
    requires_gpu: bool = False
    priority: int = 5
    retry_count: int = 0
    max_retries: int = 2
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0


class DependencyGraph:
    """Directed Acyclic Graph managing task nodes, edges, and state transitions."""

    def __init__(self):
        self.nodes: Dict[str, TaskNode] = {}

    def add_node(self, node: TaskNode) -> None:
        self.nodes[node.task_id] = node

    def add_edge(self, upstream_id: str, downstream_id: str) -> None:
        """downstream_id depends on upstream_id (upstream -> downstream)."""
        if upstream_id in self.nodes and downstream_id in self.nodes:
            self.nodes[downstream_id].depends_on.add(upstream_id)
            self.nodes[upstream_id].dependents.add(downstream_id)

    def detect_cycles(self) -> List[List[str]]:
        """DFS cycle detection."""
        visited = set()
        rec_stack = set()
        cycles = []

        def dfs(node_id: str, path: List[str]):
            visited.add(node_id)
            rec_stack.add(node_id)
            for dep_id in self.nodes[node_id].dependents:
                if dep_id not in visited:
                    dfs(dep_id, path + [dep_id])
                elif dep_id in rec_stack:
                    cycle_start = path.index(dep_id) if dep_id in path else 0
                    cycles.append(path[cycle_start:] + [dep_id])
            rec_stack.remove(node_id)

        for n_id in list(self.nodes.keys()):
            if n_id not in visited:
                dfs(n_id, [n_id])
        return cycles

    def initialize_states(self) -> None:
        """Mark nodes with 0 dependencies as READY, others as BLOCKED."""
        for node in self.nodes.values():
            if not node.depends_on:
                node.state = TaskState.READY
            else:
                node.state = TaskState.BLOCKED

    def get_ready_nodes(self) -> List[TaskNode]:
        """Return all tasks currently in READY state, sorted by priority."""
        ready = [n for n in self.nodes.values() if n.state == TaskState.READY]
        return sorted(ready, key=lambda x: x.priority, reverse=True)

    def mark_completed(self, task_id: str, result: Any = None, duration_ms: float = 0.0) -> List[str]:
        """Mark task COMPLETED and unblock downstream dependents if all prerequisites are done."""
        if task_id not in self.nodes:
            return []
        node = self.nodes[task_id]
        node.state = TaskState.COMPLETED
        node.result = result
        node.duration_ms = duration_ms

        newly_ready = []
        for dep_id in node.dependents:
            dep_node = self.nodes.get(dep_id)
            if dep_node and dep_node.state == TaskState.BLOCKED:
                # Check if all upstream dependencies completed
                all_done = all(self.nodes[u_id].state == TaskState.COMPLETED for u_id in dep_node.depends_on if u_id in self.nodes)
                if all_done:
                    dep_node.state = TaskState.READY
                    newly_ready.append(dep_id)

        return newly_ready

    def mark_failed(self, task_id: str, error: str = "") -> None:
        """Mark task FAILED and block downstream dependents."""
        if task_id not in self.nodes:
            return
        node = self.nodes[task_id]
        if node.retry_count < node.max_retries:
            node.retry_count += 1
            node.state = TaskState.RETRYING
            node.state = TaskState.READY  # Requeue for retry
            logger.info("DependencyGraph: Requeued '{}' for retry ({}/{})", task_id, node.retry_count, node.max_retries)
        else:
            node.state = TaskState.FAILED
            node.error = error
            logger.warning("DependencyGraph: Task '{}' failed permanently. Dependent tasks remain BLOCKED.", task_id)

    @property
    def is_complete(self) -> bool:
        """True if all nodes have reached a terminal state (COMPLETED, FAILED, CANCELLED)."""
        terminal_states = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
        return all(n.state in terminal_states for n in self.nodes.values())


class KairosDAGScheduler:
    """
    Asynchronous event-driven DAG scheduler.
    Enforces hardware safety: 1 GPU model inference at a time (RTX 3050 6GB),
    fine-grained file write locks, and concurrent non-conflicting I/O.
    """

    def __init__(
        self,
        max_concurrency: int = KAIROS_MAX_CONCURRENCY,
        enabled: bool = KAIROS_DAG_ENABLED
    ):
        self.max_concurrency = max_concurrency
        self.enabled = enabled
        self.gpu_semaphore = asyncio.Semaphore(1)  # Single-model residency guard on RTX 3050
        self.file_locks: Dict[str, asyncio.Lock] = {}
        self.events: List[Dict[str, Any]] = []

    def _get_file_lock(self, file_path: str) -> asyncio.Lock:
        if file_path not in self.file_locks:
            self.file_locks[file_path] = asyncio.Lock()
        return self.file_locks[file_path]

    async def execute_dag(
        self,
        graph: DependencyGraph,
        task_executor: Callable[[TaskNode], Any]
    ) -> Dict[str, Any]:
        """Execute the entire DAG concurrently while respecting dependencies and resource limits."""
        start_time = time.perf_counter()
        cycles = graph.detect_cycles()
        if cycles:
            raise ValueError(f"DAG contains circular dependencies: {cycles}")

        graph.initialize_states()
        running_tasks: Dict[str, asyncio.Task] = {}
        concurrency_history: List[int] = []

        async def worker_wrapper(node: TaskNode):
            node_start = time.perf_counter()
            node.state = TaskState.RUNNING

            # Acquire file write locks for all target write files
            acquired_locks = []
            for wf in sorted(node.write_files):
                lock = self._get_file_lock(wf)
                await lock.acquire()
                acquired_locks.append(lock)

            try:
                if node.requires_gpu:
                    # Serialize GPU model inference
                    async with self.gpu_semaphore:
                        if asyncio.iscoroutinefunction(task_executor):
                            res = await task_executor(node)
                        else:
                            res = task_executor(node)
                else:
                    if asyncio.iscoroutinefunction(task_executor):
                        res = await task_executor(node)
                    else:
                        res = task_executor(node)

                dur = (time.perf_counter() - node_start) * 1000.0
                graph.mark_completed(node.task_id, result=res, duration_ms=dur)
                return True, node.task_id, res
            except Exception as exc:
                graph.mark_failed(node.task_id, error=str(exc))
                return False, node.task_id, str(exc)
            finally:
                for l in acquired_locks:
                    l.release()

        # Main Scheduler Loop
        while not graph.is_complete:
            ready_nodes = graph.get_ready_nodes()

            # Launch ready nodes up to max_concurrency
            for node in ready_nodes:
                if len(running_tasks) >= self.max_concurrency:
                    break
                node.state = TaskState.RUNNING
                t = asyncio.create_task(worker_wrapper(node), name=f"kairos-{node.task_id}")
                running_tasks[node.task_id] = t

            concurrency_history.append(len(running_tasks))

            if not running_tasks:
                # Deadlock or all remaining tasks blocked by upstream failure
                break

            # Wait for at least one running task to complete
            done, _ = await asyncio.wait(
                list(running_tasks.values()),
                return_when=asyncio.FIRST_COMPLETED
            )

            # Clean up completed tasks
            for t in done:
                for t_id, task_obj in list(running_tasks.items()):
                    if task_obj == t:
                        del running_tasks[t_id]

        total_dur_ms = (time.perf_counter() - start_time) * 1000.0
        max_conc = max(concurrency_history) if concurrency_history else 1
        avg_conc = sum(concurrency_history) / len(concurrency_history) if concurrency_history else 1.0

        return {
            "success": all(n.state == TaskState.COMPLETED for n in graph.nodes.values()),
            "total_duration_ms": total_dur_ms,
            "max_concurrency": max_conc,
            "avg_concurrency": round(avg_conc, 2),
            "completed_nodes": [n.task_id for n in graph.nodes.values() if n.state == TaskState.COMPLETED],
            "failed_nodes": [n.task_id for n in graph.nodes.values() if n.state == TaskState.FAILED],
            "blocked_nodes": [n.task_id for n in graph.nodes.values() if n.state == TaskState.BLOCKED],
        }


# Global singleton
kairos_dag_scheduler = KairosDAGScheduler()
