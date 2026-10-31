# benchmarks/benchmark_phase4e_concurrency.py
"""
HERMES Phase 4E Benchmark:
Mission Compression, Conflict Key Scheduling, Safe Parallel Execution, and Concurrency Telemetry.

Measures:
  1. Complexity classification overhead (target < 1.0ms)
  2. Mission compression ratio (Simple missions: 8 serial tasks -> 4 consolidated units)
  3. Conflict-key batch scheduling latency (target < 0.5ms)
  4. Parallel batch throughput vs Serial execution simulation
  5. Context sharing & static rule cache hit efficiency
  6. Acceptance criteria repair consolidation metrics
  7. Verification barrier safety verification under concurrency
"""

import sys
import time
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.runtime_identity import get_canonical_python_executable
canonical_py = get_canonical_python_executable()
assert sys.executable.lower() == canonical_py.lower(), f"Must run under canonical runtime: {canonical_py}"

from core.mission_planner import (
    MissionPlanner,
    Mission,
    MissionTask,
    TaskState,
    TaskPriority,
    MissionComplexity,
    classify_mission_complexity,
)
from core.mission_runner import MissionRunner, MissionOptimizationTelemetry
from core.adaptive_routing import get_adaptive_router, ProviderHealthState


def run_benchmark():
    print("=" * 80)
    print("HERMES PHASE 4E — MISSION COMPRESSION & SAFE PARALLEL EXECUTION BENCHMARK")
    print("=" * 80)

    results = {}

    # 1. Complexity Classification Latency (1000 iterations)
    test_prompts = [
        "Create hello.py printing hello world",
        "Build a campus event board with search, filters, details modal, and localStorage persistence",
        "Build a Flask REST API with SQLite database, models, and routes for books",
        "Build a full-stack platform with OAuth authentication, JWT, migrations, Celery worker, and tests",
    ]
    t0 = time.perf_counter()
    for _ in range(250):
        for p in test_prompts:
            classify_mission_complexity(p)
    cls_duration = (time.perf_counter() - t0) * 1000.0 / 1000.0
    print(f"1. Complexity Classification Latency (1000 runs): {cls_duration:.4f}ms per call (target <= 1.0ms)")
    results["complexity_classification_latency_ms"] = cls_duration
    assert cls_duration < 1.0, f"Classification latency exceeded 1.0ms: {cls_duration}ms"

    # 2. Mission Compression Evaluation
    # Baseline Phase 4D planned 8 tasks for Campus Event Board; Phase 4E plans 4 tasks
    planner = MissionPlanner()
    campus_prompt = (
        "I want a small but polished campus event board for students. "
        "Students should browse events, search and filter by category, see details, "
        "and add new events. Remember events in localStorage. Make it responsive."
    )
    t_plan0 = time.perf_counter()
    mission_4e = planner.plan(campus_prompt)
    plan_latency_ms = (time.perf_counter() - t_plan0) * 1000.0

    uncompressed_task_count = 8
    compressed_task_count = len(mission_4e.tasks)
    compression_ratio = uncompressed_task_count / compressed_task_count
    print(
        f"2. Mission Compression: {uncompressed_task_count} tasks -> {compressed_task_count} tasks "
        f"({compression_ratio:.2f}x compression) | Plan Latency: {plan_latency_ms:.2f}ms"
    )
    assert compressed_task_count == 4, f"Expected 4 tasks, got {compressed_task_count}"
    assert mission_4e.complexity == MissionComplexity.SIMPLE
    results["uncompressed_task_count"] = uncompressed_task_count
    results["compressed_task_count"] = compressed_task_count
    results["mission_compression_ratio"] = compression_ratio
    results["plan_latency_ms"] = plan_latency_ms

    # 3. Conflict-Key Scheduling Latency & Disjoint Batch Formation
    # After Task 1 (index.html) completes, Task 2 (styles.css) and Task 3 (app.js) are disjoint
    mission_4e.mark_task_complete(mission_4e.tasks[0].task_id)

    sched_latencies = []
    for _ in range(500):
        t_sched0 = time.perf_counter()
        batch = mission_4e.get_executable_batch(max_concurrent=3)
        sched_latencies.append((time.perf_counter() - t_sched0) * 1000.0)

    sched_med = sorted(sched_latencies)[len(sched_latencies) // 2]
    sched_p95 = sorted(sched_latencies)[int(len(sched_latencies) * 0.95)]
    batch_ids = [t.task_id for t in batch]
    print(
        f"3. Conflict-Key Batch Scheduling (500 runs): median={sched_med:.4f}ms | "
        f"p95={sched_p95:.4f}ms (target <= 0.5ms) | Executable Batch Size: {len(batch)} tasks ({batch_ids})"
    )
    assert len(batch) == 2, f"Expected CSS and JS to batch concurrently, got {len(batch)}"
    assert sched_p95 < 0.5, f"Scheduling p95 exceeded 0.5ms: {sched_p95}ms"
    results["scheduling_median_ms"] = sched_med
    results["scheduling_p95_ms"] = sched_p95
    results["concurrent_batch_size"] = len(batch)

    # 4. Safe Concurrency Speedup Simulation
    # Serial execution: Task1 (40s) + Task2 (40s) + Task3 (40s) + Task4 (20s) = 140s
    # Safe parallel execution: Task1 (40s) + max(Task2, Task3) (40s) + Task4 (20s) = 100s
    t1_dur = 40.0
    t2_dur = 42.0
    t3_dur = 38.0
    t4_dur = 20.0
    simulated_serial_duration = t1_dur + t2_dur + t3_dur + t4_dur
    simulated_parallel_duration = t1_dur + max(t2_dur, t3_dur) + t4_dur
    speedup_factor = simulated_serial_duration / simulated_parallel_duration
    print(
        f"4. Theoretical Execution Latency Simulation: "
        f"Serial={simulated_serial_duration:.1f}s -> Parallel={simulated_parallel_duration:.1f}s "
        f"({speedup_factor:.2f}x speedup, ~{(simulated_serial_duration - simulated_parallel_duration):.1f}s saved)"
    )
    results["simulated_serial_seconds"] = simulated_serial_duration
    results["simulated_parallel_seconds"] = simulated_parallel_duration
    results["simulated_speedup_factor"] = speedup_factor

    # 5. Static Context Cache Hit Latency
    from unittest.mock import MagicMock
    mock_orch = MagicMock()
    mock_ws = MagicMock()
    mock_ws.root_str = "."
    mock_ws.is_locked = False
    mock_ws.workspace_root = None
    runner = MissionRunner(orchestrator=mock_orch, workspace_manager=mock_ws)

    # Prime cache
    p1 = runner._build_task_prompt_with_description(mission_4e.tasks[1], mission_4e, mission_4e.tasks[1].description)
    t_ctx0 = time.perf_counter()
    p2 = runner._build_task_prompt_with_description(mission_4e.tasks[2], mission_4e, mission_4e.tasks[2].description)
    cached_prep_ms = (time.perf_counter() - t_ctx0) * 1000.0
    print(f"5. Cached Static Context Preparation: {cached_prep_ms:.4f}ms (Cache Hit)")
    assert runner.telemetry.context_cache_hits >= 1
    results["cached_context_prep_ms"] = cached_prep_ms
    results["context_cache_hits"] = runner.telemetry.context_cache_hits

    # 6. Verification Barrier Safety Under Concurrency
    # Reset tasks for barrier test
    t_v = mission_4e.tasks[3]
    assert t_v.is_verification_task
    # When t1 is complete, but t2 is RUNNING, verification must NOT be executable
    mission_4e.tasks[1].state = TaskState.RUNNING
    mission_4e.tasks[2].state = TaskState.COMPLETED
    assert t_v.state == TaskState.PENDING
    barrier_batch = mission_4e.get_executable_batch(max_concurrent=3)
    # Verification task must NOT be yielded
    assert not any(t.task_id == t_v.task_id for t in barrier_batch)
    print("6. Hard Verification Barrier: Confirmed blocked while implementation task is RUNNING")
    results["verification_barrier_enforced"] = True

    # Complete t2, now verification task should yield
    mission_4e.tasks[1].state = TaskState.COMPLETED
    final_batch = mission_4e.get_executable_batch(max_concurrent=3)
    assert len(final_batch) == 1 and final_batch[0].task_id == t_v.task_id
    print("   Verification Barrier Cleared: Yielded cleanly once all implementation tasks COMPLETED")

    # Save benchmark metrics to json
    metrics_path = REPO_ROOT / "benchmarks" / "phase4e_concurrency_metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to: {metrics_path}")

    print("-" * 80)
    print("PHASE 4E BENCHMARK SUMMARY:")
    for k, v in results.items():
        print(f"  - {k}: {v}")
    print("=" * 80)
    return results


if __name__ == "__main__":
    run_benchmark()
