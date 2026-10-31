# benchmarks/benchmark_phase4a_performance.py
"""
HERMES Phase 4A — Performance Benchmark Harness
Measures runtime latency, dispatch speed, dev server reuse, and DAG parallelism:
1. SEND command latency (target <= 50ms)
2. Mission planning DAG latency
3. First model dispatch preparation latency (target <= 250ms)
4. DevServer startup vs warm fast-reuse latency
5. DAG batch execution parallelism and conflict analysis
"""

import sys
import time
import json
import asyncio
from pathlib import Path
from typing import Dict, Any

# Canonical environment check
REPO_ROOT = Path(r"C:\Users\SUBBU\Downloads\hermes").resolve()
CANONICAL_PYTHON = REPO_ROOT / "venv" / "Scripts" / "python.exe"

active_exe = Path(sys.executable).resolve()
if active_exe != CANONICAL_PYTHON.resolve():
    print(f"FATAL: Must execute with canonical Python! Active: {active_exe}, Expected: {CANONICAL_PYTHON}")
    sys.exit(1)

sys.path.insert(0, str(REPO_ROOT))

from core.mission_planner import MissionPlanner, TaskPriority, TaskState
from core.mission_runner import MissionRunner
from core.orchestrator import Orchestrator
from core.workspace import workspace_manager
from core.browser.dev_server import DevServerManager


async def benchmark_send_and_planning_latency() -> Dict[str, Any]:
    """Measure SEND command latency and DAG mission planning latency."""
    prompt = (
        "Build a campus event board with events browsing, search, filter, details modal, "
        "and new event creation with persistence."
    )
    test_dir = REPO_ROOT / "tests" / "temp_benchmark_ws"
    test_dir.mkdir(parents=True, exist_ok=True)
    workspace_manager.lock(str(test_dir))

    planner = MissionPlanner()
    t0 = time.perf_counter()
    mission = planner.plan(prompt, workspace_root=str(test_dir))
    t1 = time.perf_counter()
    planning_ms = (t1 - t0) * 1000.0

    # Measure SEND event loop queue latency
    orchestrator = Orchestrator(mode="auto", project="perf_test")
    runner = MissionRunner(orchestrator=orchestrator, workspace_manager=workspace_manager)

    t_send_start = time.perf_counter()
    # Enqueue a dummy event and measure dispatch to queue
    await runner.event_queue.put({"test": "send_latency"})
    item = await runner.event_queue.get()
    runner.event_queue.task_done()
    t_send_end = time.perf_counter()
    send_latency_ms = (t_send_end - t_send_start) * 1000.0

    return {
        "send_latency_ms": round(send_latency_ms, 3),
        "planning_latency_ms": round(planning_ms, 3),
        "task_count": len(mission.tasks),
        "target_met_send": send_latency_ms <= 50.0
    }


async def benchmark_dev_server_fast_reuse() -> Dict[str, Any]:
    """Measure cold startup vs fast-reuse latency of DevServerManager."""
    dsm = DevServerManager()
    test_dir = REPO_ROOT / "tests" / "temp_benchmark_ws"
    (test_dir / "index.html").write_text("<!DOCTYPE html><html><body>Bench</body></html>", encoding="utf-8")

    # Cold startup
    t0 = time.perf_counter()
    s1 = await dsm.start_static_server(test_dir, name="bench_server")
    t1 = time.perf_counter()
    cold_startup_ms = (t1 - t0) * 1000.0

    # Fast reuse (same directory)
    t2 = time.perf_counter()
    s2 = await dsm.start_static_server(test_dir, name="bench_server")
    t3 = time.perf_counter()
    fast_reuse_ms = (t3 - t2) * 1000.0

    assert s1.port == s2.port, "Fast reuse must return existing server instance"
    assert s1.process.pid == s2.process.pid, "Fast reuse must not spawn a new process"

    # Cleanup
    s1.process.terminate()
    s1.process.wait()

    return {
        "cold_startup_ms": round(cold_startup_ms, 3),
        "fast_reuse_ms": round(fast_reuse_ms, 3),
        "speedup_factor": round(cold_startup_ms / max(fast_reuse_ms, 0.001), 2),
        "target_met_reuse": fast_reuse_ms <= 10.0
    }


async def benchmark_first_dispatch_preparation() -> Dict[str, Any]:
    """Measure preparation time before model dispatch in Orchestrator pipeline."""
    from core.prompt_builder import build_system_prompt, PromptContext
    test_dir = REPO_ROOT / "tests" / "temp_benchmark_ws"
    workspace_manager.lock(str(test_dir))

    t0 = time.perf_counter()
    ctx = PromptContext(
        user_task="Create campus event board application",
        mode="auto",
        available_tools=["write_file", "read_file", "list_directory"],
        tool_descriptions="Tool schemas formatted.",
        execution_mode="performance"
    )
    system_prompt = build_system_prompt(ctx)
    t1 = time.perf_counter()
    prep_ms = (t1 - t0) * 1000.0

    return {
        "dispatch_prep_ms": round(prep_ms, 3),
        "target_met_dispatch_prep": prep_ms <= 250.0
    }


def benchmark_dag_batch_parallelism() -> Dict[str, Any]:
    """Test get_executable_batch for concurrency and verification gating."""
    planner = MissionPlanner()
    prompt = (
        "1. Create css/styles.css with color palette.\n"
        "2. Create js/app.js with data logic.\n"
        "3. Create index.html referencing styles and script.\n"
        "4. Verify the web application in browser."
    )
    test_dir = REPO_ROOT / "tests" / "temp_benchmark_ws"
    mission = planner.plan(prompt, workspace_root=str(test_dir))

    # Examine batches
    batch1 = mission.get_executable_batch(max_concurrent=3)
    batch1_titles = [t.title for t in batch1]

    # Verify barrier: verification task must NOT be in batch1
    verif_in_batch1 = any(t.is_verification_task for t in batch1)

    return {
        "initial_batch_size": len(batch1),
        "initial_batch_titles": batch1_titles,
        "verification_barrier_preserved": not verif_in_batch1
    }


async def main():
    print("=" * 80)
    print("HERMES PHASE 4A — PERFORMANCE BENCHMARK HARNESS")
    print("=" * 80)
    print(f"Python: {sys.executable} (Version: {sys.version.split()[0]})")
    print(f"Workspace root: {REPO_ROOT}\n")

    results = {}

    print("1. Measuring SEND & Planning Latency...")
    res_send = await benchmark_send_and_planning_latency()
    results["send_and_planning"] = res_send
    print(f"   SEND Latency: {res_send['send_latency_ms']} ms (Target <= 50ms: {res_send['target_met_send']})")
    print(f"   Planning Latency: {res_send['planning_latency_ms']} ms ({res_send['task_count']} tasks)\n")

    print("2. Measuring DevServer Startup vs Fast Reuse...")
    res_server = await benchmark_dev_server_fast_reuse()
    results["dev_server_reuse"] = res_server
    print(f"   Cold Startup: {res_server['cold_startup_ms']} ms")
    print(f"   Fast Reuse: {res_server['fast_reuse_ms']} ms (Speedup: {res_server['speedup_factor']}x, Target <= 10ms: {res_server['target_met_reuse']})\n")

    print("3. Measuring First Dispatch Preparation Latency...")
    res_prep = await benchmark_first_dispatch_preparation()
    results["dispatch_prep"] = res_prep
    print(f"   Dispatch Prep: {res_prep['dispatch_prep_ms']} ms (Target <= 250ms: {res_prep['target_met_dispatch_prep']})\n")

    print("4. Evaluating DAG Parallelism & Verification Barrier...")
    res_dag = benchmark_dag_batch_parallelism()
    results["dag_parallelism"] = res_dag
    print(f"   Initial Batch Size: {res_dag['initial_batch_size']}")
    print(f"   Batch Tasks: {res_dag['initial_batch_titles']}")
    print(f"   Verification Barrier Enforced: {res_dag['verification_barrier_preserved']}\n")

    # Save benchmark metrics
    out_file = REPO_ROOT / "benchmarks" / "phase4a_performance_metrics.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Performance metrics saved to {out_file}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
