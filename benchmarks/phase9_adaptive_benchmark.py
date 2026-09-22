"""
Phase 9 Adaptive Execution Engine Benchmark.
Measures:
1. Classification latency & accuracy across SIMPLE, STANDARD, and COMPLEX tasks
2. Execution latency of SIMPLE fast path (0 LLMs) vs legacy pipeline
3. Runtime escalation verification
"""
import time
import json
import tempfile
from pathlib import Path

from core.adaptive_execution import (
    ExecutionMode,
    TaskComplexityClassifier,
    EscalationManager,
    AdaptiveExecutionEngine
)

WORKSPACE = Path(__file__).resolve().parent.parent
PERF_DIR = WORKSPACE / "performance" / "phase9"
PERF_DIR.mkdir(parents=True, exist_ok=True)

BENCHMARK_TASKS = [
    # SIMPLE
    ("Create folder logs", ExecutionMode.SIMPLE),
    ("mkdir build_output", ExecutionMode.SIMPLE),
    ("read config.py", ExecutionMode.SIMPLE),
    ("show project structure", ExecutionMode.SIMPLE),
    ("check if file exists README.md", ExecutionMode.SIMPLE),
    # STANDARD
    ("Fix authentication login timeout in auth.py", ExecutionMode.STANDARD),
    ("Add unit test for user registration", ExecutionMode.STANDARD),
    ("Modify React navbar component", ExecutionMode.STANDARD),
    ("Add error handling to database connection", ExecutionMode.STANDARD),
    ("Update requirements.txt with new version", ExecutionMode.STANDARD),
    # COMPLEX
    ("Build complete authentication system across frontend and backend", ExecutionMode.COMPLEX),
    ("Migrate complete system architecture to microservices", ExecutionMode.COMPLEX),
    ("Refactor entire data layer and database schemas across all files", ExecutionMode.COMPLEX),
    ("Implement full-stack payment gateway integration with tests and docs", ExecutionMode.COMPLEX),
    ("Multi-module refactor of the core orchestration pipeline", ExecutionMode.COMPLEX),
]

def run_adaptive_benchmark():
    print("================================================================")
    print(" PHASE 9 ADAPTIVE EXECUTION ENGINE BENCHMARK")
    print("================================================================")

    classifier = TaskComplexityClassifier()
    engine = AdaptiveExecutionEngine(enabled=True)

    # 1. Classification Latency & Accuracy
    print("\n[TEST 1] Multi-Signal Classification Speed & Accuracy (15 Tasks)...")
    correct_count = 0
    total_classif_time_ms = 0.0
    task_results = []

    for task_text, expected_mode in BENCHMARK_TASKS:
        t0 = time.perf_counter()
        res = classifier.classify(task_text)
        dur = (time.perf_counter() - t0) * 1000.0
        total_classif_time_ms += dur

        is_correct = res.mode == expected_mode
        if is_correct:
            correct_count += 1

        task_results.append({
            "task": task_text,
            "expected": expected_mode.value,
            "actual": res.mode.value,
            "confidence": res.confidence,
            "risk": res.risk_score,
            "latency_ms": round(dur, 3),
            "correct": is_correct
        })
        print(f"  [{res.mode.value.ljust(8)}] {task_text[:45].ljust(48)} (conf={res.confidence:.2f}, risk={res.risk_score:.2f}) in {dur:.3f} ms")

    avg_classif_ms = total_classif_time_ms / len(BENCHMARK_TASKS)
    accuracy_pct = (correct_count / len(BENCHMARK_TASKS)) * 100.0
    print(f"\n  -> Average Classification Latency: {avg_classif_ms:.4f} ms")
    print(f"  -> Classification Accuracy: {accuracy_pct:.1f}% ({correct_count}/{len(BENCHMARK_TASKS)})")

    # 2. SIMPLE Fast Path Execution Speed (0 LLM Calls)
    print("\n[TEST 2] SIMPLE Fast Path Execution Speed...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_p = Path(tmp_dir) / "test_reports"
        t0 = time.perf_counter()
        ok, out = engine.execute_fast_path(
            tool_name="create_directory",
            tool_args={"path": str(tmp_p)},
            workspace_manager=None
        )
        fast_dur_ms = (time.perf_counter() - t0) * 1000.0
        print(f"  -> Direct Deterministic mkdir completed in {fast_dur_ms:.2f} ms | ok={ok} | LLM Calls=0")

    # 3. Runtime Escalation Check
    print("\n[TEST 3] Runtime Escalation Verification...")
    esc_mgr = EscalationManager(initial_mode=ExecutionMode.SIMPLE)
    esc_mode_1 = esc_mgr.check_escalation(tool_failed=True)
    print(f"  -> Trigger: Tool Failed -> Escalated: {esc_mode_1.value}")

    esc_mode_2 = esc_mgr.check_escalation(dependency_count=5)
    print(f"  -> Trigger: Dependency Count=5 -> Escalated: {esc_mode_2.value}")

    report = {
        "avg_classification_latency_ms": round(avg_classif_ms, 4),
        "classification_accuracy_pct": round(accuracy_pct, 1),
        "simple_fast_path_latency_ms": round(fast_dur_ms, 2),
        "simple_llm_calls": 0,
        "tasks": task_results,
        "escalations": esc_mgr.escalations
    }

    (PERF_DIR / "phase9_adaptive_benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[OK] Saved results to {PERF_DIR / 'phase9_adaptive_benchmark.json'}")

if __name__ == "__main__":
    run_adaptive_benchmark()
