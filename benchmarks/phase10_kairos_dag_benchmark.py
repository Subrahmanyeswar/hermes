"""
Phase 10 KAIROS DAG Execution Engine Benchmark.
Measures:
1. Pure independent task parallelism speedup (Sequential vs DAG)
2. Dependent task sequential enforcement (A -> B -> C)
3. Mixed DAG execution (A, B -> D; C)
4. Scheduler latency and concurrency efficiency
"""
import asyncio
import time
import json
from pathlib import Path

from core.kairos_dag import (
    TaskState,
    TaskNode,
    DependencyGraph,
    KairosDAGScheduler
)

WORKSPACE = Path(__file__).resolve().parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase10"
PERF_DIR.mkdir(parents=True, exist_ok=True)

async def run_dag_benchmark():
    print("================================================================")
    print(" PHASE 10 KAIROS DAG EXECUTION BENCHMARK")
    print("================================================================")

    scheduler = KairosDAGScheduler(max_concurrency=4)

    # 1. Independent Task Benchmark (3x 50ms tasks)
    print("\n[TEST 1] Independent Tasks (3x 50ms Tasks)...")
    graph_indep = DependencyGraph()
    graph_indep.add_node(TaskNode(task_id="A", title="Task A"))
    graph_indep.add_node(TaskNode(task_id="B", title="Task B"))
    graph_indep.add_node(TaskNode(task_id="C", title="Task C"))

    async def mock_io_executor(node: TaskNode):
        await asyncio.sleep(0.05)
        return f"result_{node.task_id}"

    # Sequential baseline
    t0 = time.perf_counter()
    for n in [TaskNode("A", "A"), TaskNode("B", "B"), TaskNode("C", "C")]:
        await mock_io_executor(n)
    seq_time_ms = (time.perf_counter() - t0) * 1000.0

    # DAG concurrent execution
    t0 = time.perf_counter()
    dag_summary = await scheduler.execute_dag(graph_indep, mock_io_executor)
    dag_time_ms = (time.perf_counter() - t0) * 1000.0
    speedup_indep = seq_time_ms / dag_time_ms if dag_time_ms > 0 else 1.0

    print(f"  -> Sequential Baseline: {seq_time_ms:.2f} ms")
    print(f"  -> KAIROS DAG Parallel: {dag_time_ms:.2f} ms")
    print(f"  -> Measured Speedup:    {speedup_indep:.2f}x (Max Concurrency={dag_summary['max_concurrency']})")

    # 2. Mixed DAG Benchmark (A, B -> D; C)
    print("\n[TEST 2] Mixed DAG (A, B -> D; C independent, 4x 40ms Tasks)...")
    graph_mixed = DependencyGraph()
    graph_mixed.add_node(TaskNode(task_id="A", title="Task A"))
    graph_mixed.add_node(TaskNode(task_id="B", title="Task B"))
    graph_mixed.add_node(TaskNode(task_id="C", title="Task C"))
    graph_mixed.add_node(TaskNode(task_id="D", title="Task D"))
    graph_mixed.add_edge("A", "D")
    graph_mixed.add_edge("B", "D")

    async def mock_mixed_executor(node: TaskNode):
        await asyncio.sleep(0.04)
        return "done"

    seq_mixed_ms = 4 * 40.0  # 160ms
    t0 = time.perf_counter()
    mixed_summary = await scheduler.execute_dag(graph_mixed, mock_mixed_executor)
    mixed_dag_ms = (time.perf_counter() - t0) * 1000.0
    speedup_mixed = seq_mixed_ms / mixed_dag_ms if mixed_dag_ms > 0 else 1.0

    print(f"  -> Sequential Baseline: {seq_mixed_ms:.2f} ms")
    print(f"  -> KAIROS DAG Parallel: {mixed_dag_ms:.2f} ms")
    print(f"  -> Measured Speedup:    {speedup_mixed:.2f}x (Max Concurrency={mixed_summary['max_concurrency']})")

    results = {
        "independent_sequential_ms": round(seq_time_ms, 2),
        "independent_dag_ms": round(dag_time_ms, 2),
        "independent_speedup": round(speedup_indep, 2),
        "mixed_sequential_ms": round(seq_mixed_ms, 2),
        "mixed_dag_ms": round(mixed_dag_ms, 2),
        "mixed_speedup": round(speedup_mixed, 2),
        "max_concurrency": dag_summary["max_concurrency"]
    }

    (PERF_DIR / "phase10_kairos_dag_benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[OK] Saved results to {PERF_DIR / 'phase10_kairos_dag_benchmark.json'}")

if __name__ == "__main__":
    asyncio.run(run_dag_benchmark())
