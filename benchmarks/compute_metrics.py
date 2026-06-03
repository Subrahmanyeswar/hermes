#!/usr/bin/env python3
"""
HERMES Benchmark Metrics Computation — Week 18
Reads benchmarks/results.json and computes all 6 metrics.
Can be run independently after the benchmark runner completes.

Run: python benchmarks/compute_metrics.py
     python benchmarks/compute_metrics.py --results-file benchmarks/results.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(description="Compute HERMES benchmark metrics")
    parser.add_argument(
        "--results-file", default="benchmarks/results.json",
        help="Path to benchmark results JSON"
    )
    parser.add_argument(
        "--output-file", default="benchmarks/metrics.json",
        help="Where to save computed metrics"
    )
    parser.add_argument(
        "--paper-table", action="store_true",
        help="Also generate the paper results table as CSV"
    )
    args = parser.parse_args()

    results_path = Path(args.results_file)
    if not results_path.exists():
        print(f"ERROR: {results_path} not found.")
        print("Run the benchmark first: python benchmarks/runner.py --quick")
        sys.exit(1)

    print(f"Loading results from: {results_path}")
    with open(results_path) as f:
        run_data = json.load(f)

    task_count = len(run_data.get("task_results", []))
    print(f"Task results loaded: {task_count}")

    if task_count == 0:
        print("No task results found. Run the benchmark first.")
        sys.exit(1)

    from benchmarks.runner import compute_metrics
    metrics = compute_metrics(run_data)

    # Save metrics
    output_path = Path(args.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics saved to: {output_path}")

    # Print full summary
    _print_full_summary(metrics, run_data)

    # Optional: generate paper table
    if args.paper_table:
        _generate_paper_table(metrics, run_data)


def _print_full_summary(metrics: dict, run_data: dict) -> None:
    """Print comprehensive metrics for paper writing."""
    print("\n" + "=" * 70)
    print("HERMES BENCHMARK RESULTS")
    print("=" * 70)

    # Header info
    print(f"\nRun ID:     {run_data.get('run_id', 'unknown')}")
    print(f"Started:    {run_data.get('started_at', 'unknown')[:19]}")
    print(f"Completed:  {(run_data.get('completed_at') or 'in progress')[:19]}")
    print(f"Total cost: ${run_data.get('total_cost_usd', 0):.4f}")
    print(f"Total time: {run_data.get('total_latency_seconds', 0):.1f}s")

    # M1: Completion rates
    m1 = metrics.get("m1_task_completion_rate", {})
    print(f"\n{'─' * 70}")
    print("M1 — TASK COMPLETION RATE")
    print(f"{'─' * 70}")
    print(f"{'Condition':<25} {'Overall':>8} {'L1':>6} {'L2':>6} {'L3':>6} {'L4':>6} {'L5':>6}")
    print(f"{'─' * 70}")

    condition_labels = {
        "hermes":      "HERMES (T1+T2+T3)",
        "t1_skill":    "T1 + Skill",
        "t1_no_skill": "T1 Only (baseline)",
    }
    diffs = ["L1_trivial", "L2_simple", "L3_medium", "L4_complex", "L5_hard"]

    for cond, label in condition_labels.items():
        data = m1.get(cond, {})
        overall = data.get("overall", 0) * 100
        by_diff = data.get("by_difficulty", {})
        diff_values = [f"{by_diff.get(d, 0)*100:.0f}%" for d in diffs]
        print(f"{label:<25} {overall:>7.1f}%  {'  '.join(diff_values)}")

    # M2: Escalation
    m2 = metrics.get("m2_tier3_escalation", {})
    print(f"\n{'─' * 70}")
    print("M2 — TIER 3 ESCALATION RATE")
    print(f"{'─' * 70}")
    print(f"  Total HERMES tasks:       {m2.get('total_tasks', 0)}")
    print(f"  Tier 3 calls:             {m2.get('tier3_calls', 0)}")
    print(f"  Escalation rate:          {m2.get('escalation_rate', 0)*100:.1f}%")
    print(f"  Local resolution rate:    {m2.get('local_resolution_rate', 0)*100:.1f}%")
    print(f"  → {m2.get('local_resolution_rate', 0)*100:.1f}% of tasks ran FREE (no API cost)")

    # M3: Skill lift
    m3 = metrics.get("m3_skill_accuracy_lift", {})
    print(f"\n{'─' * 70}")
    print("M3 — SKILL ACCURACY LIFT (ABLATION STUDY)")
    print(f"{'─' * 70}")
    print(f"  Domain tasks tested:      {m3.get('domain_tasks_count', 0)}")
    print(f"  Completion WITH skill:    {m3.get('with_skill_rate', 0)*100:.1f}%")
    print(f"  Completion WITHOUT skill: {m3.get('without_skill_rate', 0)*100:.1f}%")
    lift = m3.get('skill_accuracy_lift', 0) * 100
    sign = "+" if lift >= 0 else ""
    print(f"  Skill accuracy lift:      {sign}{lift:.1f} percentage points")
    if lift >= 10:
        print(f"  → H2 SUPPORTED: ≥10pp lift from skill injection")
    else:
        print(f"  → H2 PARTIAL: {lift:.1f}pp lift (below 10pp target)")

    # M4: Latency
    m4 = metrics.get("m4_latency_by_difficulty", {})
    print(f"\n{'─' * 70}")
    print("M4 — AVERAGE TASK LATENCY BY DIFFICULTY")
    print(f"{'─' * 70}")
    print(f"{'Condition':<25} {'L1':>6} {'L2':>6} {'L3':>6} {'L4':>6} {'L5':>6} {'Mean':>6}")
    overall = m4.get("overall_mean", {})
    for cond, label in condition_labels.items():
        data = m4.get(cond, {})
        vals = [f"{data.get(d, 0):.1f}s" for d in diffs]
        mean = overall.get(cond, 0)
        print(f"{label:<25} {'  '.join(vals)}  {mean:.1f}s")

    # M5: Cost
    m5 = metrics.get("m5_api_cost", {})
    print(f"\n{'─' * 70}")
    print("M5 — API COST COMPARISON")
    print(f"{'─' * 70}")
    print(f"  HERMES actual cost:       ${m5.get('hermes_actual_cost_usd', 0):.4f}")
    print(f"  Estimated all-Claude:     ${m5.get('estimated_all_claude_cost_usd', 0):.4f}")
    print(f"  Cost reduction:           {m5.get('cost_reduction_pct', 0):.1f}%")

    # M6: Agreement
    m6 = metrics.get("m6_agreement_rate", {})
    print(f"\n{'─' * 70}")
    print("M6 — T1 VS T2 AGREEMENT RATE")
    print(f"{'─' * 70}")
    print(f"  Estimated agreement rate: {m6.get('estimated_agreement_rate', 0)*100:.1f}%")
    print(f"  Note: {m6.get('note', '')}")

    # Hypothesis validation
    hyps = metrics.get("hypothesis_validation", {})
    print(f"\n{'─' * 70}")
    print("HYPOTHESIS VALIDATION")
    print(f"{'─' * 70}")
    for hyp_id, hyp_data in hyps.items():
        supported = hyp_data.get("supported", False)
        status = "✓ SUPPORTED" if supported else "✗ NOT SUPPORTED"
        print(f"\n  {hyp_id}: {status}")
        for key, val in hyp_data.items():
            if key not in ("supported",):
                print(f"    {key}: {val}")

    print(f"\n{'=' * 70}")


def _generate_paper_table(metrics: dict, run_data: dict) -> None:
    """Generate CSV tables for the research paper."""
    import csv

    # Table 1: Completion rates
    table1_path = Path("benchmarks/paper_table1_completion.csv")
    m1 = metrics.get("m1_task_completion_rate", {})
    diffs = ["L1_trivial", "L2_simple", "L3_medium", "L4_complex", "L5_hard", "overall"]

    with open(table1_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Condition"] + diffs)
        for cond in ["hermes", "t1_skill", "t1_no_skill"]:
            data = m1.get(cond, {})
            by_diff = data.get("by_difficulty", {})
            row = [cond] + [
                f"{by_diff.get(d, data.get('overall', 0))*100:.1f}"
                if d != "overall"
                else f"{data.get('overall', 0)*100:.1f}"
                for d in diffs
            ]
            writer.writerow(row)
    print(f"\nPaper Table 1 saved: {table1_path}")

    # Table 2: Ablation study
    table2_path = Path("benchmarks/paper_table2_ablation.csv")
    m3 = metrics.get("m3_skill_accuracy_lift", {})

    with open(table2_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Metric", "Value"])
        writer.writerow(["with_skill_rate", f"{m3.get('with_skill_rate', 0)*100:.1f}%"])
        writer.writerow(["without_skill_rate", f"{m3.get('without_skill_rate', 0)*100:.1f}%"])
        writer.writerow(["skill_accuracy_lift_pp", f"{m3.get('skill_accuracy_lift', 0)*100:.1f}"])
        writer.writerow(["domain_tasks", m3.get("domain_tasks_count", 0)])
    print(f"Paper Table 2 saved: {table2_path}")

    # Table 3: Cost and escalation
    table3_path = Path("benchmarks/paper_table3_cost.csv")
    m2 = metrics.get("m2_tier3_escalation", {})
    m5 = metrics.get("m5_api_cost", {})

    with open(table3_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Metric", "Value"])
        writer.writerow(["escalation_rate_pct", f"{m2.get('escalation_rate', 0)*100:.1f}"])
        writer.writerow(["local_resolution_pct", f"{m2.get('local_resolution_rate', 0)*100:.1f}"])
        writer.writerow(["hermes_cost_usd", f"{m5.get('hermes_actual_cost_usd', 0):.4f}"])
        writer.writerow(["estimated_all_claude_usd", f"{m5.get('estimated_all_claude_cost_usd', 0):.4f}"])
        writer.writerow(["cost_reduction_pct", f"{m5.get('cost_reduction_pct', 0):.1f}"])
    print(f"Paper Table 3 saved: {table3_path}")


if __name__ == "__main__":
    main()
