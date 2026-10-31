"""
scripts/eval_phase4h_heldout_complexity.py
Evaluates the deterministic zero-LLM MissionComplexityClassifier against the
frozen held-out benchmark (benchmarks/phase4h/heldout_prompts.json).
Outputs:
- benchmarks/phase4h/complexity_predictions.json
- artifacts/phase4h/complexity_predictions.json
- artifacts/phase4h/classification_confusion_matrix.json
"""

import json
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.mission_planner import classify_mission_complexity, MissionComplexity
BENCHMARK_FILE = ROOT / "benchmarks" / "phase4h" / "heldout_prompts.json"
PRED_OUT_BENCH = ROOT / "benchmarks" / "phase4h" / "complexity_predictions.json"
PRED_OUT_ART = ROOT / "artifacts" / "phase4h" / "complexity_predictions.json"
CONF_MATRIX_OUT = ROOT / "artifacts" / "phase4h" / "classification_confusion_matrix.json"

TIERS = ["TRIVIAL", "SIMPLE", "MEDIUM", "COMPLEX", "LARGE"]

def main():
    with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
        cases = json.load(f)

    predictions = []
    confusion = {actual: {pred: 0 for pred in TIERS} for actual in TIERS}
    tier_stats = {tier: {"total": 0, "correct": 0} for tier in TIERS}
    latencies_us = []

    for case in cases:
        prompt = case["prompt"]
        expected = case["expected_complexity"]

        t0 = time.perf_counter_ns()
        pred = classify_mission_complexity(prompt)
        t1 = time.perf_counter_ns()
        latency_us = (t1 - t0) / 1000.0
        latencies_us.append(latency_us)

        pred_val = pred.value if hasattr(pred, "value") else str(pred)
        is_correct = (pred_val == expected)

        confusion[expected][pred_val] += 1
        tier_stats[expected]["total"] += 1
        if is_correct:
            tier_stats[expected]["correct"] += 1

        predictions.append({
            "id": case["id"],
            "family": case["family"],
            "domain": case["domain"],
            "prompt": prompt,
            "expected": expected,
            "predicted": pred_val,
            "is_correct": is_correct,
            "latency_us": round(latency_us, 2)
        })

    total = len(cases)
    total_correct = sum(1 for p in predictions if p["is_correct"])
    overall_acc = (total_correct / total) * 100.0
    avg_latency_us = sum(latencies_us) / len(latencies_us)

    print("=====================================================================")
    print("HERMES PHASE 4H — HELD-OUT COMPLEXITY CLASSIFICATION RESULTS")
    print("=====================================================================")
    print(f"Overall Accuracy: {total_correct}/{total} ({overall_acc:.1f}%)")
    print(f"Average Classification Latency: {avg_latency_us:.2f} µs (< 0.2ms zero-LLM target)")
    print("\nPer-Tier Breakdown:")
    for tier in TIERS:
        st = tier_stats[tier]
        acc = (st["correct"] / st["total"]) * 100.0 if st["total"] > 0 else 0.0
        print(f"  {tier:8s}: {st['correct']}/{st['total']} ({acc:5.1f}%)")

    print("\nConfusion Matrix (Rows: Actual, Columns: Predicted):")
    header = f"{'ACTUAL':10s} " + " ".join(f"{t:>8s}" for t in TIERS) + " | TOTAL   ACC"
    print(header)
    print("-" * len(header))
    for actual in TIERS:
        row_counts = [confusion[actual][pred] for pred in TIERS]
        tot = sum(row_counts)
        acc = (confusion[actual][actual] / tot * 100.0) if tot > 0 else 0.0
        row_str = f"{actual:10s} " + " ".join(f"{c:8d}" for c in row_counts) + f" | {tot:5d} {acc:5.1f}%"
        print(row_str)
    print("=====================================================================\n")

    # Save output artifacts
    payload = {
        "benchmark": "phase4h_heldout_evaluation",
        "total_cases": total,
        "total_correct": total_correct,
        "overall_accuracy_pct": overall_acc,
        "avg_latency_us": round(avg_latency_us, 2),
        "per_tier_accuracy": {
            tier: round((tier_stats[tier]["correct"] / tier_stats[tier]["total"]) * 100.0, 1)
            for tier in TIERS
        },
        "predictions": predictions
    }

    with open(PRED_OUT_BENCH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    with open(PRED_OUT_ART, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    with open(CONF_MATRIX_OUT, "w", encoding="utf-8") as f:
        json.dump({
            "tiers": TIERS,
            "matrix": confusion,
            "per_tier_accuracy": payload["per_tier_accuracy"],
            "overall_accuracy_pct": overall_acc
        }, f, indent=2)

if __name__ == "__main__":
    main()
