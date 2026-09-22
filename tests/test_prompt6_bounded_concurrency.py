# tests/test_prompt6_bounded_concurrency.py
"""
Unit and integration test suite for Prompt 6 Bounded Concurrency Executor.
Verifies bounded worker limits, GPU serialization, file write conflict locks,
dependency handling, cancellation, timeout, and failure isolation.
"""

import asyncio
import pytest
import time

from core.bounded_executor import (
    BoundedExecutor,
    BoundedTask,
    ResourceClass,
    TaskExecutionRecord,
)


@pytest.mark.asyncio
async def test_independent_cpu_tasks_concurrency():
    """Verify two independent CPU tasks execute concurrently under max_workers=2."""
    executor = BoundedExecutor(max_workers=2)

    async def mock_cpu_task(dur_s: float, val: int):
        await asyncio.sleep(dur_s)
        return val * 2

    t1 = BoundedTask(task_id="t1", func=mock_cpu_task, args=(0.1, 5), resource_class=ResourceClass.CPU)
    t2 = BoundedTask(task_id="t2", func=mock_cpu_task, args=(0.1, 10), resource_class=ResourceClass.CPU)

    start = time.perf_counter()
    records = await executor.execute_batch([t1, t2], refresh_index_barrier=False)
    elapsed = time.perf_counter() - start

    assert len(records) == 2
    assert records[0].success is True and records[0].result == 10
    assert records[1].success is True and records[1].result == 20
    # Both took ~0.1s; concurrent total time should be substantially less than serial (0.2s)
    assert elapsed < 0.18


@pytest.mark.asyncio
async def test_same_file_conflict_serialization():
    """Verify tasks targeting the same file are serialized by per-file locks."""
    executor = BoundedExecutor(max_workers=2)
    execution_timeline = []

    async def file_task(task_name: str, dur_s: float):
        execution_timeline.append(f"{task_name}_start")
        await asyncio.sleep(dur_s)
        execution_timeline.append(f"{task_name}_end")
        return task_name

    # Both tasks target "shared/index.html"
    t1 = BoundedTask(
        task_id="t1", func=file_task, args=("t1", 0.08),
        resource_class=ResourceClass.IO, target_files={"shared/index.html"}
    )
    t2 = BoundedTask(
        task_id="t2", func=file_task, args=("t2", 0.08),
        resource_class=ResourceClass.IO, target_files={"./shared/index.html"}  # Normalized match
    )

    records = await executor.execute_batch([t1, t2], refresh_index_barrier=False)
    assert len(records) == 2
    assert all(r.success for r in records)

    # Serialized timeline check: t1 must end before t2 starts or vice versa
    if execution_timeline[0] == "t1_start":
        assert execution_timeline == ["t1_start", "t1_end", "t2_start", "t2_end"]
    else:
        assert execution_timeline == ["t2_start", "t2_end", "t1_start", "t1_end"]


@pytest.mark.asyncio
async def test_gpu_inference_serialization_guard():
    """Verify GPU inference tasks remain strictly serialized (max_gpu_workers=1) on RTX 3050."""
    executor = BoundedExecutor(max_workers=4, max_gpu_workers=1)
    concurrent_gpu_count = 0
    max_concurrent_gpu = 0

    async def gpu_model_task():
        nonlocal concurrent_gpu_count, max_concurrent_gpu
        concurrent_gpu_count += 1
        max_concurrent_gpu = max(max_concurrent_gpu, concurrent_gpu_count)
        await asyncio.sleep(0.05)
        concurrent_gpu_count -= 1
        return True

    t1 = BoundedTask(task_id="gpu_1", func=gpu_model_task, resource_class=ResourceClass.GPU)
    t2 = BoundedTask(task_id="gpu_2", func=gpu_model_task, resource_class=ResourceClass.GPU)

    records = await executor.execute_batch([t1, t2], refresh_index_barrier=False)
    assert len(records) == 2
    assert all(r.success for r in records)
    assert max_concurrent_gpu == 1  # Never exceeded 1 concurrent GPU task


@pytest.mark.asyncio
async def test_dependent_task_ordering():
    """Verify task B with depends_on=[A] waits for A to complete before starting."""
    executor = BoundedExecutor(max_workers=2)
    timeline = []

    async def step(name: str):
        timeline.append(name)
        await asyncio.sleep(0.04)
        return name

    t_a = BoundedTask(task_id="A", func=step, args=("A",), resource_class=ResourceClass.CPU)
    t_b = BoundedTask(task_id="B", func=step, args=("B",), depends_on={"A"}, resource_class=ResourceClass.CPU)

    records = await executor.execute_batch([t_a, t_b], refresh_index_barrier=False)
    assert len(records) == 2
    assert records[0].task_id == "A"
    assert records[1].task_id == "B"
    assert timeline == ["A", "B"]


@pytest.mark.asyncio
async def test_cancellation_safety():
    """Verify abort_event immediately halts execution without zombie tasks."""
    executor = BoundedExecutor(max_workers=2)
    abort_event = asyncio.Event()

    async def cancellable_task():
        await asyncio.sleep(0.2)
        return "finished"

    t1 = BoundedTask(task_id="c1", func=cancellable_task, resource_class=ResourceClass.CPU)
    abort_event.set()  # Pre-cancelled

    record = await executor.execute_task(t1, abort_event=abort_event)
    assert record.success is False
    assert record.cancelled is True


@pytest.mark.asyncio
async def test_timeout_safety():
    """Verify tasks exceeding timeout_seconds are aborted cleanly."""
    executor = BoundedExecutor(max_workers=2)

    async def long_task():
        await asyncio.sleep(1.0)
        return "done"

    t1 = BoundedTask(task_id="slow", func=long_task, timeout_seconds=0.05, resource_class=ResourceClass.CPU)
    record = await executor.execute_task(t1)

    assert record.success is False
    assert record.timeout is True
    assert "timed out" in record.error.lower()
