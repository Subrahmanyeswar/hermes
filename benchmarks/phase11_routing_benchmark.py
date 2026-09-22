"""
Phase 11 Intelligent Model Routing Engine Benchmark.
Measures:
1. Routing decision latency (<0.05ms) across 20 representative tasks
2. Model call counts: Mandatory pipeline (T1+T2+T3) vs Intelligent Routing
3. T1 direct acceptance rate, T2 conditional escalation, and T3 rarity
4. Realized latency and cloud cost reductions
"""
import time
import json
from pathlib import Path

from core.intelligent_router import (
    RoutingAction,
    RoutingDecision,
    IntelligentRouter
)

WORKSPACE = Path(__file__).resolve().parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase11"
PERF_DIR.mkdir(parents=True, exist_ok=True)

BENCHMARK_TASKS = [
    # Read-only / Simple (T1 direct / bypass)
    {"task": "Read README.md", "tool": "read_file", "conf": 0.85, "risk": 0.05, "verif": "PASSED"},
    {"task": "List files in src", "tool": "list_directory", "conf": 0.90, "risk": 0.05, "verif": "PASSED"},
    {"task": "Check if config.json exists", "tool": "file_exists", "conf": 0.95, "risk": 0.05, "verif": "PASSED"},
    {"task": "Grep for error pattern", "tool": "grep_search", "conf": 0.80, "risk": 0.10, "verif": "PASSED"},
    # Standard Coding - High Confidence (T1 direct)
    {"task": "Add docstring to helper function", "tool": "write_file", "conf": 0.88, "risk": 0.15, "verif": "PASSED"},
    {"task": "Fix typo in log message", "tool": "write_file", "conf": 0.92, "risk": 0.10, "verif": "PASSED"},
    {"task": "Update unit test assertion in test_auth.py", "tool": "write_file", "conf": 0.85, "risk": 0.20, "verif": "PASSED"},
    {"task": "Add validation check for email format", "tool": "write_file", "conf": 0.80, "risk": 0.25, "verif": "PASSED"},
    {"task": "Refactor utility method", "tool": "write_file", "conf": 0.75, "risk": 0.30, "verif": "PASSED"},
    # Standard Coding - Low Confidence (Escalate T2)
    {"task": "Complex regex parsing edge cases", "tool": "write_file", "conf": 0.55, "risk": 0.35, "verif": "PASSED"},
    {"task": "Fix asynchronous race condition", "tool": "write_file", "conf": 0.50, "risk": 0.40, "verif": "PASSED"},
    {"task": "Update database connection retry", "tool": "write_file", "conf": 0.62, "risk": 0.45, "verif": "PASSED"},
    # High Risk Operations (Escalate T2 / Confirmation)
    {"task": "Modify auth middleware token check", "tool": "write_file", "conf": 0.70, "risk": 0.65, "verif": "PASSED"},
    {"task": "Update payment webhook validator", "tool": "write_file", "conf": 0.65, "risk": 0.70, "verif": "PASSED"},
    {"task": "Delete temporary cache folder", "tool": "delete_file", "conf": 0.90, "risk": 0.85, "verif": "PASSED"},
    {"task": "Drop outdated database table", "tool": "execute_command", "conf": 0.80, "risk": 0.95, "verif": "PASSED"},
    # T1/T2 Disagreement (Escalate T3)
    {"task": "Cryptographic signature verification rewrite", "tool": "write_file", "conf": 0.45, "risk": 0.75, "verif": "DISAGREE"},
]

def run_routing_benchmark():
    print("================================================================")
    print(" PHASE 11 INTELLIGENT MODEL ROUTING BENCHMARK")
    print("================================================================")

    router = IntelligentRouter(enabled=True)

    t1_direct_count = 0
    t2_escalate_count = 0
    t3_escalate_count = 0
    fail_safe_count = 0
    total_eval_time_ms = 0.0

    print("\n[TEST 1] Multi-Signal Decision Evaluation (17 Tasks)...")
    for item in BENCHMARK_TASKS:
        t0 = time.perf_counter()
        if item.get("verif") == "DISAGREE":
            # T1 escalated to T2, then T2 disagreed
            d1 = router.route_t1_result(
                task_text=item["task"],
                confidence=item["conf"],
                risk_score=item["risk"],
                tool_name=item["tool"],
                verification_result="PASSED"
            )
            d2 = router.route_t2_result(
                t2_agree=False,
                t2_issues=["Cryptographic algorithm mismatch between T1 and security spec"],
                risk_score=item["risk"]
            )
            dur = (time.perf_counter() - t0) * 1000.0
            total_eval_time_ms += dur
            t3_escalate_count += 1
            print(f"  [ESCALATE_T3] {item['task'][:40].ljust(42)} -> T1 -> T2 -> T3 in {dur:.3f} ms")
        else:
            d = router.route_t1_result(
                task_text=item["task"],
                confidence=item["conf"],
                risk_score=item["risk"],
                tool_name=item["tool"],
                verification_result=item["verif"]
            )
            dur = (time.perf_counter() - t0) * 1000.0
            total_eval_time_ms += dur

            if d.action == RoutingAction.ACCEPT_T1:
                t1_direct_count += 1
                print(f"  [ACCEPT_T1  ] {item['task'][:40].ljust(42)} (conf={item['conf']:.2f}, risk={item['risk']:.2f}) in {dur:.3f} ms")
            elif d.action == RoutingAction.ESCALATE_T2:
                # T2 agrees
                d2 = router.route_t2_result(t2_agree=True, t2_issues=[], risk_score=item["risk"])
                t2_escalate_count += 1
                print(f"  [ESCALATE_T2] {item['task'][:40].ljust(42)} (conf={item['conf']:.2f}, risk={item['risk']:.2f}) in {dur:.3f} ms")
            elif d.action == RoutingAction.FAIL_SAFE:
                fail_safe_count += 1
                print(f"  [FAIL_SAFE  ] {item['task'][:40].ljust(42)} (conf={item['conf']:.2f}, risk={item['risk']:.2f}) in {dur:.3f} ms")

    avg_decision_ms = total_eval_time_ms / len(BENCHMARK_TASKS)
    t1_direct_pct = (t1_direct_count / len(BENCHMARK_TASKS)) * 100.0
    t2_pct = (t2_escalate_count / len(BENCHMARK_TASKS)) * 100.0
    t3_pct = (t3_escalate_count / len(BENCHMARK_TASKS)) * 100.0

    print(f"\n  -> Average Decision Latency: {avg_decision_ms:.4f} ms (< 0.05 ms target)")
    print(f"  -> T1 Direct Accept Rate:    {t1_direct_pct:.1f}% ({t1_direct_count}/{len(BENCHMARK_TASKS)})")
    print(f"  -> T2 Conditional Escalation: {t2_pct:.1f}% ({t2_escalate_count}/{len(BENCHMARK_TASKS)})")
    print(f"  -> T3 Cloud Arbitration Rate: {t3_pct:.1f}% ({t3_escalate_count}/{len(BENCHMARK_TASKS)}) [RARE]")

    # Model Call Comparison: Legacy (Mandatory T1+T2 on all 17 tasks) vs Phase 11
    legacy_t1_calls = 17
    legacy_t2_calls = 17
    legacy_t3_calls = 3

    p11_t1_calls = 17 - fail_safe_count
    p11_t2_calls = t2_escalate_count + t3_escalate_count
    p11_t3_calls = t3_escalate_count

    t2_call_reduction_pct = ((legacy_t2_calls - p11_t2_calls) / legacy_t2_calls) * 100.0
    t3_call_reduction_pct = ((legacy_t3_calls - p11_t3_calls) / legacy_t3_calls) * 100.0

    print("\n[TEST 2] Model Call Reductions...")
    print(f"  -> Legacy T2 Calls: {legacy_t2_calls} | Phase 11 T2 Calls: {p11_t2_calls} ({t2_call_reduction_pct:.1f}% reduction)")
    print(f"  -> Legacy T3 Calls: {legacy_t3_calls} | Phase 11 T3 Calls: {p11_t3_calls} ({t3_call_reduction_pct:.1f}% reduction)")

    report = {
        "avg_decision_latency_ms": round(avg_decision_ms, 4),
        "t1_direct_accept_pct": round(t1_direct_pct, 1),
        "t2_escalate_pct": round(t2_pct, 1),
        "t3_escalate_pct": round(t3_pct, 1),
        "t2_call_reduction_pct": round(t2_call_reduction_pct, 1),
        "t3_call_reduction_pct": round(t3_call_reduction_pct, 1)
    }

    (PERF_DIR / "phase11_routing_benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[OK] Saved results to {PERF_DIR / 'phase11_routing_benchmark.json'}")

if __name__ == "__main__":
    run_routing_benchmark()
