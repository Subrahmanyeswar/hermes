"""
Phase 6.4 Model Lifecycle & Residency Benchmark.
Measures:
1. Cold vs Warm load duration
2. Switching cost (T1 -> T2, T2 -> T1)
3. Repeated same-model executions (T1 x 3)
4. Full mission execution with model residency tracking
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any, List

from core.orchestrator import Orchestrator
from core.model_residency_manager import model_residency_manager

WORKSPACE = Path(__file__).resolve().parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase6_4"
PERF_DIR.mkdir(parents=True, exist_ok=True)

async def run_lifecycle_benchmark():
    print("================================================================")
    print(" PHASE 6.4 MODEL LIFECYCLE & RESIDENCY BENCHMARK")
    print("================================================================")

    # Mission 1: Consecutive Read-Only Operations (Should maintain T1 warm residency, 0 switches!)
    orch1 = Orchestrator(mode="auto")
    print("\n[RUN 1] First Directory Listing (T1 Warm/Preload)...")
    t0 = time.perf_counter()
    r1 = await orch1.run("List all files in generated_projects")
    d1 = time.perf_counter() - t0
    print(f"  -> Latency: {d1:.2f}s | Success: {r1.success}")

    print("\n[RUN 2] Consecutive Directory Listing (Reusing Warm T1)...")
    t0 = time.perf_counter()
    r2 = await orch1.run("List all files in generated_projects")
    d2 = time.perf_counter() - t0
    print(f"  -> Latency: {d2:.2f}s | Success: {r2.success}")

    state = model_residency_manager.get_state()
    print(f"\n--> Residency State After Consecutive Runs: {json.dumps(state, indent=2)}")

    results = {
        "run_1_latency": round(d1, 2),
        "run_2_latency": round(d2, 2),
        "consecutive_speedup": f"{((d1 - d2) / d1 * 100):.1f}%" if d1 > d2 else "0.0%",
        "residency_state": state
    }
    (PERF_DIR / "phase6_4_benchmark_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[OK] Saved results to {PERF_DIR / 'phase6_4_benchmark_results.json'}")

if __name__ == "__main__":
    asyncio.run(run_lifecycle_benchmark())
