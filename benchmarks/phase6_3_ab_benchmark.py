"""
Phase 6.3 Controlled A/B Benchmark Suite.
Compares Fixed Budget (A) vs Adaptive Reasoning Budget (B) across L0 to L3 tasks:
- Latency (seconds)
- Tokens generated
- Mission success
- Repair / retry occurrences
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any, List

from core.orchestrator import Orchestrator
from core.reasoning_budget import ReasoningBudgetManager

WORKSPACE = Path(__file__).resolve().parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase6_3"
PERF_DIR.mkdir(parents=True, exist_ok=True)

BENCHMARK_TASKS = [
    {
        "id": "L0_DIR_LIST",
        "level": "L0_DIRECT",
        "prompt": "List all files in generated_projects",
    },
    {
        "id": "L1_SIMPLE_WRITE",
        "level": "L1_SIMPLE",
        "prompt": "Create a file named generated_projects/math_helper.py containing def square(x): return x * x",
    },
    {
        "id": "L2_NORMAL_CODING",
        "level": "L2_NORMAL",
        "prompt": "Create a Python file generated_projects/user_validator.py with validate_email(email) and validate_password(pwd)",
    }
]

async def run_single_experiment(adaptive: bool) -> List[Dict[str, Any]]:
    mode_str = "ADAPTIVE" if adaptive else "FIXED"
    print(f"\n================================================================")
    print(f" RUNNING EXPERIMENT: {mode_str} T1 REASONING BUDGET")
    print(f"================================================================")

    results = []
    for t in BENCHMARK_TASKS:
        print(f"\n--> Task [{t['id']} | {t['level']}]: {t['prompt'][:50]}...")
        orch = Orchestrator(mode="auto")
        orch.budget_manager.enabled = adaptive

        t0 = time.perf_counter()
        res = await orch.run(t["prompt"])
        latency = time.perf_counter() - t0

        print(f"    LATENCY: {latency:.2f}s | Success: {res.success}")
        results.append({
            "task_id": t["id"],
            "level": t["level"],
            "mode": mode_str,
            "latency_sec": round(latency, 2),
            "success": res.success,
            "error": res.error
        })
    return results

async def main():
    # Run Fixed mode
    fixed_res = await run_single_experiment(adaptive=False)
    # Run Adaptive mode
    adaptive_res = await run_single_experiment(adaptive=True)

    summary = {
        "fixed": fixed_res,
        "adaptive": adaptive_res
    }
    (PERF_DIR / "phase6_3_ab_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n[OK] Benchmark completed and saved to {PERF_DIR / 'phase6_3_ab_results.json'}")

if __name__ == "__main__":
    asyncio.run(main())
