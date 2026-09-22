"""
Unit and Integration Tests for Phase 10 KAIROS DAG Execution Engine.
Tests independent task concurrency, dependency topological ordering,
mixed DAG execution, failure propagation, cycle detection, file write locks,
and GPU model serialization.
"""
import asyncio
import time
import pytest

from core.kairos_dag import (
    TaskState,
    TaskNode,
    DependencyGraph,
    KairosDAGScheduler
)


@pytest.mark.asyncio
async def test_independent_tasks_concurrent_speedup():
    """Three independent 50ms tasks must execute concurrently in ~50-70ms, not 150ms."""
    graph = DependencyGraph()
    graph.add_node(TaskNode(task_id="A", title="Task A"))
    graph.add_node(TaskNode(task_id="B", title="Task B"))
    graph.add_node(TaskNode(task_id="C", title="Task C"))

    async def mock_executor(node: TaskNode):
        await asyncio.sleep(0.05)
        return f"result_{node.task_id}"

    scheduler = KairosDAGScheduler(max_concurrency=3)
    t0 = time.perf_counter()
    summary = await scheduler.execute_dag(graph, mock_executor)
    dur = time.perf_counter() - t0

    assert summary["success"] is True
    assert len(summary["completed_nodes"]) == 3
    assert dur < 0.12  # Concurrency makes 3x 50ms finish in < 120ms


@pytest.mark.asyncio
async def test_dependent_task_ordering():
    """Dependent chain A -> B -> C must execute sequentially."""
    graph = DependencyGraph()
    graph.add_node(TaskNode(task_id="A", title="Task A"))
    graph.add_node(TaskNode(task_id="B", title="Task B"))
    graph.add_node(TaskNode(task_id="C", title="Task C"))
    graph.add_edge("A", "B")
    graph.add_edge("B", "C")

    execution_order = []

    async def mock_executor(node: TaskNode):
        execution_order.append(node.task_id)
        await asyncio.sleep(0.02)
        return "done"

    scheduler = KairosDAGScheduler(max_concurrency=4)
    summary = await scheduler.execute_dag(graph, mock_executor)

    assert summary["success"] is True
    assert execution_order == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_mixed_dag_execution():
    """Mixed DAG: A, B -> D; C independent. A, B, C start first, D waits for A & B."""
    graph = DependencyGraph()
    graph.add_node(TaskNode(task_id="A", title="Task A"))
    graph.add_node(TaskNode(task_id="B", title="Task B"))
    graph.add_node(TaskNode(task_id="C", title="Task C"))
    graph.add_node(TaskNode(task_id="D", title="Task D"))

    graph.add_edge("A", "D")
    graph.add_edge("B", "D")

    active_tasks = []
    max_parallel = 0

    async def mock_executor(node: TaskNode):
        nonlocal max_parallel
        active_tasks.append(node.task_id)
        max_parallel = max(max_parallel, len(active_tasks))
        await asyncio.sleep(0.04)
        active_tasks.remove(node.task_id)
        return "done"

    scheduler = KairosDAGScheduler(max_concurrency=4)
    summary = await scheduler.execute_dag(graph, mock_executor)

    assert summary["success"] is True
    assert max_parallel >= 2  # A, B, C ran concurrently
    assert set(summary["completed_nodes"]) == {"A", "B", "C", "D"}


@pytest.mark.asyncio
async def test_failure_propagation():
    """If B fails in A, B -> D; C, then D remains BLOCKED while A and C complete."""
    graph = DependencyGraph()
    graph.add_node(TaskNode(task_id="A", title="Task A"))
    graph.add_node(TaskNode(task_id="B", title="Task B", max_retries=0))
    graph.add_node(TaskNode(task_id="C", title="Task C"))
    graph.add_node(TaskNode(task_id="D", title="Task D"))

    graph.add_edge("A", "D")
    graph.add_edge("B", "D")

    async def mock_executor(node: TaskNode):
        if node.task_id == "B":
            raise RuntimeError("Task B intentional failure")
        await asyncio.sleep(0.02)
        return "done"

    scheduler = KairosDAGScheduler(max_concurrency=4)
    summary = await scheduler.execute_dag(graph, mock_executor)

    assert summary["success"] is False
    assert "A" in summary["completed_nodes"]
    assert "C" in summary["completed_nodes"]
    assert "B" in summary["failed_nodes"]
    assert "D" in summary["blocked_nodes"]


def test_cycle_detection_rejects_circular_graph():
    """Circular graph A -> B -> C -> A must be detected."""
    graph = DependencyGraph()
    graph.add_node(TaskNode(task_id="A", title="Task A"))
    graph.add_node(TaskNode(task_id="B", title="Task B"))
    graph.add_node(TaskNode(task_id="C", title="Task C"))

    graph.add_edge("A", "B")
    graph.add_edge("B", "C")
    graph.add_edge("C", "A")

    cycles = graph.detect_cycles()
    assert len(cycles) > 0


@pytest.mark.asyncio
async def test_file_write_conflict_serialization():
    """Tasks modifying the same file are safely serialized by file write locks."""
    graph = DependencyGraph()
    graph.add_node(TaskNode(task_id="A", title="Write A", write_files={"auth.py"}))
    graph.add_node(TaskNode(task_id="B", title="Write B", write_files={"auth.py"}))

    concurrent_writes = 0
    max_concurrent_writes = 0

    async def mock_executor(node: TaskNode):
        nonlocal concurrent_writes, max_concurrent_writes
        concurrent_writes += 1
        max_concurrent_writes = max(max_concurrent_writes, concurrent_writes)
        await asyncio.sleep(0.03)
        concurrent_writes -= 1
        return "done"

    scheduler = KairosDAGScheduler(max_concurrency=4)
    summary = await scheduler.execute_dag(graph, mock_executor)

    assert summary["success"] is True
    assert max_concurrent_writes == 1  # Never concurrent on same file!


@pytest.mark.asyncio
async def test_gpu_inference_serialization():
    """Tasks requiring GPU inference are serialized to protect 6GB VRAM."""
    graph = DependencyGraph()
    graph.add_node(TaskNode(task_id="G1", title="GPU Task 1", requires_gpu=True))
    graph.add_node(TaskNode(task_id="G2", title="GPU Task 2", requires_gpu=True))

    concurrent_gpu = 0
    max_concurrent_gpu = 0

    async def mock_executor(node: TaskNode):
        nonlocal concurrent_gpu, max_concurrent_gpu
        concurrent_gpu += 1
        max_concurrent_gpu = max(max_concurrent_gpu, concurrent_gpu)
        await asyncio.sleep(0.03)
        concurrent_gpu -= 1
        return "done"

    scheduler = KairosDAGScheduler(max_concurrency=4)
    summary = await scheduler.execute_dag(graph, mock_executor)

    assert summary["success"] is True
    assert max_concurrent_gpu == 1  # Strictly 1 GPU model at a time!
