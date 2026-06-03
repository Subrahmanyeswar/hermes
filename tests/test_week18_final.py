#!/usr/bin/env python3
"""
HERMES — Week 18 Final Validation
50-task benchmark + ablation study infrastructure complete.

Run: python tests/test_week18_final.py
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_1_tasks_json_valid():
    """benchmarks/tasks.json must be valid with exactly 50 tasks."""
    tasks_path = Path("benchmarks/tasks.json")
    if not tasks_path.exists():
        print("  ✗ benchmarks/tasks.json not found")
        return False

    with open(tasks_path) as f:
        data = json.load(f)

    tasks = data.get("tasks", [])
    if len(tasks) != 50:
        print(f"  ✗ Expected 50 tasks, got {len(tasks)}")
        return False

    from collections import Counter
    by_diff = Counter(t["difficulty"] for t in tasks)
    expected = {"L1_trivial": 10, "L2_simple": 10, "L3_medium": 15, "L4_complex": 10, "L5_hard": 5}
    for diff, count in expected.items():
        if by_diff[diff] != count:
            print(f"  ✗ {diff}: expected {count}, got {by_diff[diff]}")
            return False

    skill_relevant = sum(1 for t in tasks if t["skill_relevant"])
    if skill_relevant != 30:
        print(f"  ✗ Expected 30 skill-relevant tasks, got {skill_relevant}")
        return False

    required_fields = ["id", "difficulty", "domain", "skill_relevant", "prompt", "expected_tool", "success_criterion"]
    for task in tasks:
        missing = [f for f in required_fields if f not in task]
        if missing:
            print(f"  ✗ Task {task.get('id')} missing fields: {missing}")
            return False

    print(f"  ✓ tasks.json valid | 50 tasks | {skill_relevant} skill-relevant | correct difficulty distribution")
    return True


def test_2_runner_imports_cleanly():
    """benchmarks/runner.py must import without error."""
    try:
        from benchmarks.runner import (
            BenchmarkRunner, TaskResult, BenchmarkRun,
            compute_metrics, check_success_criterion,
            run_task_hermes, run_task_t1_only,
        )
        print("  ✓ runner.py imports cleanly with all required symbols")
        return True
    except ImportError as e:
        print(f"  ✗ Import error: {e}")
        return False


def test_3_criterion_checker_correct():
    """check_success_criterion must return correct results for all criteria."""
    from benchmarks.runner import check_success_criterion

    test_cases = [
        ("exit_code_0",                "any output",          "write_file", 0, True,  True),
        ("exit_code_0",                "any output",          "write_file", 1, False, False),
        ("output_contains_flask",      "from flask import",   "write_file", 0, True,  True),
        ("output_contains_flask",      "no match here",       "write_file", 0, True,  False),
        ("output_contains_pytest",     "def test_something",  "write_file", 0, True,  True),
        ("output_contains_create_table","CREATE TABLE users",  "write_file", 0, True,  True),
        ("output_contains_bash",       "#!/bin/bash",         "write_file", 0, True,  True),
        ("output_contains_readme",     "## Installation",     "write_file", 0, True,  True),
        ("output_contains_python",     "Python 3.12.0",       "bash_exec",  0, True,  True),
    ]

    failures = []
    for criterion, output, tool, exit_code, success, expected in test_cases:
        result = check_success_criterion(criterion, output, tool, exit_code, success)
        if result != expected:
            failures.append(f"{criterion}: expected {expected}, got {result}")

    if failures:
        for f in failures:
            print(f"  ✗ {f}")
        return False

    print(f"  ✓ check_success_criterion correct for all {len(test_cases)} test cases")
    return True


def test_4_compute_metrics_works_on_synthetic_data():
    """compute_metrics must handle synthetic task results correctly."""
    from benchmarks.runner import compute_metrics

    synthetic_run = {
        "run_id": "test_synthetic",
        "started_at": "2026-08-22T10:00:00",
        "completed_at": "2026-08-22T11:00:00",
        "conditions_run": ["hermes", "t1_skill", "t1_no_skill"],
        "total_cost_usd": 0.42,
        "total_latency_seconds": 3600.0,
        "task_results": []
    }

    task_ids = [f"L{level}-0{i+1}" for level in [1, 2, 3] for i in range(4)][:10]
    for task_id in task_ids:
        difficulty = "L1_trivial" if "1" in task_id else "L2_simple" if "2" in task_id else "L3_medium"
        for condition in ["hermes", "t1_skill", "t1_no_skill"]:
            skill_relevant = "3" in task_id
            criterion_met = True if condition in ("hermes", "t1_skill") else (not skill_relevant)
            synthetic_run["task_results"].append({
                "task_id": task_id,
                "condition": condition,
                "difficulty": difficulty,
                "domain": "flask" if skill_relevant else "file_ops",
                "skill_relevant": skill_relevant,
                "skill_id": "flask-rest-api" if skill_relevant else None,
                "success": criterion_met,
                "tool_name": "write_file",
                "stage_reached": 12 if criterion_met else 4,
                "latency_seconds": 3.5,
                "tier3_called": condition == "hermes" and not criterion_met,
                "cost_usd": 0.014 if condition == "hermes" and not criterion_met else 0.0,
                "error": None if criterion_met else "T1 parse failure",
                "trace_id": "test1234",
                "criterion_met": criterion_met,
                "criterion": "output_contains_flask",
            })

    metrics = compute_metrics(synthetic_run)
    required_metrics = [
        "m1_task_completion_rate",
        "m2_tier3_escalation",
        "m3_skill_accuracy_lift",
        "m4_latency_by_difficulty",
        "m5_api_cost",
        "m6_agreement_rate",
        "hypothesis_validation",
    ]
    missing = [m for m in required_metrics if m not in metrics]
    if missing:
        print(f"  ✗ Missing metrics: {missing}")
        return False

    m3 = metrics["m3_skill_accuracy_lift"]
    if m3.get("skill_accuracy_lift") is None:
        print("  ✗ Skill accuracy lift not computed")
        return False

    print(f"  ✓ compute_metrics produces all 7 required metrics from synthetic data")
    print(f"    M3 skill lift: +{m3.get('skill_accuracy_lift', 0)*100:.1f}pp")
    return True


async def test_5_quick_benchmark_runs_end_to_end():
    """
    Run the benchmark in quick mode (L1+L2 tasks only) to verify
    the infrastructure works before the full 50-task run.
    Requires Ollama.
    """
    from models.ollama_client import OllamaClient

    client = OllamaClient()
    if not await client.is_running():
        print("  ⚠ Ollama not running — skipping quick benchmark test")
        print("  ⚠ Start Ollama and re-run to verify benchmark infrastructure")
        return True

    print("  Running quick benchmark (L1+L2 tasks, t1_no_skill only, ~5 minutes)...")

    quick_results = Path("benchmarks/quick_test_results.json")

    result = subprocess.run(
        [sys.executable, "benchmarks/runner.py",
         "--quick",
         "--conditions", "t1_no_skill",
         "--results-file", str(quick_results)],
        capture_output=True, text=True, timeout=600
    )

    if result.returncode != 0:
        print(f"  ✗ Quick benchmark failed with exit code {result.returncode}")
        print(f"  Last output: {result.stdout[-500:]}")
        if result.stderr:
            print(f"  Stderr: {result.stderr[-300:]}")
        return False

    if not quick_results.exists():
        print("  ✗ Quick benchmark did not create results file")
        return False

    with open(quick_results) as f:
        data = json.load(f)

    task_count = len(data.get("task_results", []))
    if task_count < 10:
        print(f"  ✗ Expected at least 10 results, got {task_count}")
        return False

    completed = sum(1 for r in data["task_results"] if r.get("criterion_met"))
    total = len(data["task_results"])
    rate = completed / total if total else 0

    print(f"  ✓ Quick benchmark complete | {completed}/{total} tasks passed ({rate*100:.0f}%)")
    print(f"  ✓ Results saved to: {quick_results}")
    return True


def test_6_paper_tables_can_be_generated():
    """compute_metrics --paper-table must generate CSV files."""
    results_path = Path("benchmarks/results.json")
    if not results_path.exists():
        results_path = Path("benchmarks/quick_test_results.json")

    if not results_path.exists():
        print("  ⚠ No results file found — skipping paper table test")
        print("  ⚠ Run benchmark first: python benchmarks/runner.py --quick")
        return True

    result = subprocess.run(
        [sys.executable, "benchmarks/compute_metrics.py",
         "--results-file", str(results_path),
         "--paper-table"],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        print(f"  ✗ compute_metrics failed: {result.stderr[:200]}")
        return False

    table_files = [
        Path("benchmarks/paper_table1_completion.csv"),
        Path("benchmarks/paper_table2_ablation.csv"),
        Path("benchmarks/paper_table3_cost.csv"),
    ]
    missing = [f for f in table_files if not f.exists()]
    if missing:
        print(f"  ✗ Missing paper tables: {[str(f) for f in missing]}")
        return False

    print(f"  ✓ All 3 paper CSV tables generated")
    return True


def test_7_ablation_structure_is_correct():
    """30 skill-relevant tasks must cover all required skill domains."""
    with open("benchmarks/tasks.json") as f:
        data = json.load(f)

    skill_tasks = [t for t in data["tasks"] if t["skill_relevant"]]
    domains_covered = set(t.get("skill_id", t["domain"]) for t in skill_tasks)

    required_skills = {
        "flask-rest-api", "pytest-generation", "database-design",
        "debugging", "git-workflow", "auto-docs", "refactoring",
        "bash-scripting", "security-audit", "code-review",
    }
    missing_skills = required_skills - domains_covered
    if missing_skills:
        print(f"  ✗ Missing skill domains in ablation tasks: {missing_skills}")
        return False

    print(f"  ✓ Ablation study covers {len(domains_covered)} skill domains with {len(skill_tasks)} tasks")
    return True


async def main():
    print("=" * 65)
    print("HERMES — Week 18 Final Validation")
    print("50-Task Benchmark + Ablation Study")
    print("=" * 65)

    tests = [
        ("tasks.json: 50 tasks, correct distribution",   lambda: test_1_tasks_json_valid()),
        ("runner.py imports cleanly",                    lambda: test_2_runner_imports_cleanly()),
        ("check_success_criterion correct",              lambda: test_3_criterion_checker_correct()),
        ("compute_metrics on synthetic data",            lambda: test_4_compute_metrics_works_on_synthetic_data()),
        ("Quick benchmark runs end-to-end",              lambda: asyncio.ensure_future(test_5_quick_benchmark_runs_end_to_end())),
        ("Paper tables generated from results",          lambda: test_6_paper_tables_can_be_generated()),
        ("Ablation covers all required skill domains",   lambda: test_7_ablation_structure_is_correct()),
    ]

    passed_all = True
    for name, fn in tests:
        print(f"\n[TEST] {name}")
        try:
            result = fn()
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                passed = await result
            else:
                passed = result
            if not passed:
                passed_all = False
        except Exception as e:
            import traceback
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            passed_all = False

    print("\n" + "=" * 65)
    if passed_all:
        print("WEEK 18 COMPLETE: Benchmark infrastructure operational.")
        print()
        print("Next steps:")
        print()
        print("1. Run the FULL benchmark (takes 2-4 hours):")
        print("   python benchmarks/runner.py")
        print()
        print("2. Compute all metrics and generate paper tables:")
        print("   python benchmarks/compute_metrics.py --paper-table")
        print()
        print("3. Metrics will be in:")
        print("   benchmarks/metrics.json          — Full metrics")
        print("   benchmarks/paper_table1_completion.csv")
        print("   benchmarks/paper_table2_ablation.csv")
        print("   benchmarks/paper_table3_cost.csv")
        print()
        print("Ready for Week 19 (Graphs, paper draft, metrics analysis).")
    else:
        print("WEEK 18 INCOMPLETE — fix failures before running the full benchmark.")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
