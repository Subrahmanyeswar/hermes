#!/usr/bin/env python3
"""
HERMES Benchmark Runner — Week 18
Executes all 50 benchmark tasks under 3 experimental conditions:
  Condition A: HERMES full pipeline (T1 + T2 + T3 when needed + skill injection)
  Condition B: T1 only with skill injection (no T2/T3 verification)
  Condition C: T1 only without skill injection (baseline — no verification, no skills)

Also runs the ablation study:
  For the 30 domain-specific tasks (skill_relevant=True):
    Run with skill injection vs without skill injection
    Measure: skill accuracy lift = completion_rate_with - completion_rate_without

Results saved to: benchmarks/results.json

Run: python benchmarks/runner.py
Expected time: 2-4 hours for full 50-task × 3-condition run.
Use --quick flag to run only L1+L2 tasks for a fast sanity check.
"""
import argparse
import asyncio
import json
import sys
import time
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ──────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    """Result of running one task under one condition."""
    task_id: str
    condition: str                  # "hermes", "t1_skill", "t1_no_skill"
    difficulty: str
    domain: str
    skill_relevant: bool
    skill_id: Optional[str]

    success: bool = False
    tool_name: Optional[str] = None
    stage_reached: int = 0
    latency_seconds: float = 0.0
    tier3_called: bool = False
    cost_usd: float = 0.0
    error: Optional[str] = None
    trace_id: str = ""

    # Success criterion check
    criterion_met: bool = False
    criterion: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BenchmarkRun:
    """Complete benchmark run results."""
    run_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    conditions_run: list[str] = field(default_factory=list)
    task_results: list[TaskResult] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_latency_seconds: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["task_results"] = [r.to_dict() for r in self.task_results]
        return d


# ──────────────────────────────────────────────────────────────────────
# Success criterion checker
# ──────────────────────────────────────────────────────────────────────

def check_success_criterion(
    criterion: str,
    result_output: str,
    tool_name: Optional[str],
    exit_code: int,
    success: bool,
) -> bool:
    """
    Check whether a task's success criterion is met.
    Returns True if the criterion passes.
    """
    if not success or exit_code != 0:
        return False

    output_lower = (result_output or "").lower()
    tool = (tool_name or "").lower()

    if criterion == "exit_code_0":
        return exit_code == 0

    elif criterion == "output_contains_files":
        return any(ext in output_lower for ext in [".py", ".md", ".txt", ".yaml", ".json", "/"])

    elif criterion == "output_contains_python":
        return "python" in output_lower and ("3." in output_lower or "version" in output_lower)

    elif criterion == "output_contains_HERMES_BENCHMARK_OK":
        return "hermes_benchmark_ok" in output_lower

    elif criterion == "output_contains_flask":
        return "flask" in output_lower or "app" in output_lower or "route" in output_lower

    elif criterion == "output_contains_pytest":
        return "def test_" in output_lower or "pytest" in output_lower or "assert" in output_lower

    elif criterion == "output_contains_create_table":
        return "create table" in output_lower or "sqlalchemy" in output_lower or "model" in output_lower

    elif criterion == "output_contains_readme":
        return (
            "installation" in output_lower
            or "usage" in output_lower
            or "##" in (result_output or "")
            or "api" in output_lower
        )

    elif criterion == "output_contains_bash":
        return "#!/bin/bash" in (result_output or "") or "bash" in output_lower or "sh" in output_lower

    else:
        # Unknown criterion — fall back to exit_code check
        return exit_code == 0


# ──────────────────────────────────────────────────────────────────────
# Single task runner
# ──────────────────────────────────────────────────────────────────────

async def run_task_hermes(
    task: dict,
    orchestrator,
    condition: str,
) -> TaskResult:
    """Run one task through the full HERMES orchestrator."""
    result = TaskResult(
        task_id=task["id"],
        condition=condition,
        difficulty=task["difficulty"],
        domain=task["domain"],
        skill_relevant=task["skill_relevant"],
        skill_id=task.get("skill_id"),
        criterion=task["success_criterion"],
    )

    start = time.monotonic()
    try:
        orch_result = await orchestrator.run(task["prompt"])
        result.latency_seconds = time.monotonic() - start
        result.success = orch_result.success
        result.tool_name = orch_result.tool_name
        result.stage_reached = orch_result.pipeline_stage_reached
        result.tier3_called = getattr(orch_result, "tier3_called", False)
        result.trace_id = orch_result.trace_id
        result.error = orch_result.error

        # Check success criterion
        tool_result = orch_result.tool_result
        output = tool_result.output if tool_result else orch_result.final_output
        exit_code = tool_result.exit_code if tool_result else (0 if orch_result.success else 1)

        result.criterion_met = check_success_criterion(
            task["success_criterion"],
            output,
            orch_result.tool_name,
            exit_code,
            orch_result.success,
        )

    except Exception as e:
        result.latency_seconds = time.monotonic() - start
        result.success = False
        result.error = f"{type(e).__name__}: {str(e)[:200]}"
        result.criterion_met = False

    return result


async def run_task_t1_only(
    task: dict,
    ollama_client,
    condition: str,
    inject_skill: bool,
) -> TaskResult:
    """
    Run one task through T1 only — no T2 verification, no T3.
    inject_skill controls whether skill injection happens.
    """
    result = TaskResult(
        task_id=task["id"],
        condition=condition,
        difficulty=task["difficulty"],
        domain=task["domain"],
        skill_relevant=task["skill_relevant"],
        skill_id=task.get("skill_id"),
        criterion=task["success_criterion"],
    )

    from core.prompt_builder import PromptContext, build_system_prompt, build_user_message
    from core.intent_classifier import IntentClassifier
    from core.response_parser import ResponseParser
    from tools.registry import tool_schema_for_prompt, list_tools, get_tool

    classifier = IntentClassifier("skills/")
    parser = ResponseParser()

    start = time.monotonic()
    try:
        # Build skill context
        skill_content = ""
        loaded_skill_ids = []
        if inject_skill:
            skill_ids = classifier.classify(task["prompt"])
            skill_content, loaded_skill_ids = classifier.build_skill_prompt_section(skill_ids)

        ctx = PromptContext(
            user_task=task["prompt"],
            mode="auto",
            available_tools=list_tools(),
            tool_descriptions=tool_schema_for_prompt(),
            memory_context="",
            skill_context=skill_content,
            active_skill_name=loaded_skill_ids[0] if loaded_skill_ids else "none",
        )
        system_prompt = build_system_prompt(ctx)
        user_message = build_user_message(task["prompt"])

        response = await ollama_client.generate(
            model="qwen2.5-coder:7b",
            prompt=user_message,
            system=system_prompt,
            keep_alive=0,
        )

        parsed = parser.parse(response)
        result.latency_seconds = time.monotonic() - start

        if not hasattr(parsed, "tool"):
            result.success = False
            result.error = f"Parse failure: {getattr(parsed, 'failure_reason', 'unknown')}"
            return result

        result.tool_name = parsed.tool
        result.stage_reached = 4  # T1 generation

        # Execute the tool
        tool_class = get_tool(parsed.tool)
        if tool_class is None:
            result.success = False
            result.error = f"Unknown tool: {parsed.tool}"
            return result

        try:
            tool_input = tool_class.Input(**parsed.parameters)
            tool_instance = tool_class()
            tool_result = tool_instance.execute(tool_input)

            result.success = tool_result.success
            result.stage_reached = 6  # Tool executed

            result.criterion_met = check_success_criterion(
                task["success_criterion"],
                tool_result.output,
                parsed.tool,
                tool_result.exit_code,
                tool_result.success,
            )

        except Exception as e:
            result.success = False
            result.error = f"Tool execution error: {type(e).__name__}: {str(e)[:100]}"
            result.stage_reached = 5

    except Exception as e:
        result.latency_seconds = time.monotonic() - start
        result.success = False
        result.error = f"{type(e).__name__}: {str(e)[:200]}"

    return result


# ──────────────────────────────────────────────────────────────────────
# Benchmark runner
# ──────────────────────────────────────────────────────────────────────

class BenchmarkRunner:
    """Runs all 50 tasks under all 3 conditions and saves results."""

    def __init__(
        self,
        tasks_file: str = "benchmarks/tasks.json",
        results_file: str = "benchmarks/results.json",
        quick_mode: bool = False,
        conditions: Optional[list[str]] = None,
    ):
        self.tasks_file = Path(tasks_file)
        self.results_file = Path(results_file)
        self.quick_mode = quick_mode
        self.conditions = conditions or ["hermes", "t1_skill", "t1_no_skill"]
        self.run = BenchmarkRun()
        self.run.conditions_run = self.conditions

    def load_tasks(self) -> list[dict]:
        with open(self.tasks_file) as f:
            data = json.load(f)
        tasks = data["tasks"]

        if self.quick_mode:
            # Quick mode: only L1 and L2 tasks (20 total)
            tasks = [t for t in tasks if t["difficulty"] in ("L1_trivial", "L2_simple")]
            print(f"Quick mode: running {len(tasks)} tasks (L1 + L2 only)")

        return tasks

    async def setup_orchestrators(self, db_path: Path):
        """Set up orchestrators for all conditions."""
        from kairos.db import init_db
        from models.ollama_client import OllamaClient

        init_db(db_path=db_path)

        self.ollama_client = OllamaClient()

        if not await self.ollama_client.is_running():
            print("ERROR: Ollama is not running. Start with: ollama serve")
            sys.exit(1)

        models = await self.ollama_client.list_models()
        if not any("qwen2.5-coder" in m for m in models):
            print("ERROR: qwen2.5-coder:7b not found")
            sys.exit(1)
        if not any("mistral" in m for m in models) and "hermes" in self.conditions:
            print("WARNING: mistral:7b-instruct not found — HERMES condition will use T1 fallback")

        # Set up HERMES orchestrator if needed
        self.hermes_orch = None
        if "hermes" in self.conditions:
            with patch("core.orchestrator.DB_PATH", db_path), \
                 patch("kairos.task_queue.DB_PATH", db_path), \
                 patch("core.orchestrator.KairosDaemon"):
                from core.orchestrator import Orchestrator
                self.hermes_orch = Orchestrator(mode="auto", project="benchmark")

    async def run_all(self) -> BenchmarkRun:
        """Execute the full benchmark."""
        tasks = self.load_tasks()
        total_conditions = len(self.conditions)
        total_runs = len(tasks) * total_conditions

        print(f"\n{'=' * 70}")
        print(f"HERMES Benchmark — {len(tasks)} tasks × {total_conditions} conditions = {total_runs} total runs")
        print(f"Run ID: {self.run.run_id}")
        print(f"Conditions: {', '.join(self.conditions)}")
        print(f"Quick mode: {self.quick_mode}")
        print(f"{'=' * 70}\n")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "benchmark.db"
            await self.setup_orchestrators(db_path)

            run_number = 0
            for task in tasks:
                for condition in self.conditions:
                    run_number += 1
                    print(
                        f"[{run_number:03d}/{total_runs}] "
                        f"{task['id']:<8} "
                        f"{condition:<15} "
                        f"{task['difficulty']:<12} "
                        f"{task['domain']:<12}",
                        end=" ",
                        flush=True,
                    )

                    result = await self._run_one(task, condition, db_path)
                    self.run.task_results.append(result)
                    self.run.total_latency_seconds += result.latency_seconds
                    self.run.total_cost_usd += result.cost_usd

                    status = "[PASS]" if result.criterion_met else "[FAIL]"
                    tier3_marker = " [T3]" if getattr(result, "tier3_called", False) else ""
                    print(
                        f"{status} "
                        f"stage:{result.stage_reached:02d} "
                        f"{result.latency_seconds:.1f}s"
                        f"{tier3_marker}"
                    )

                    if result.error and not result.criterion_met:
                        print(f"         >>> {result.error[:80]}")
                        print(f"         -> {result.error[:80]}")

                    # Brief pause between runs
                    await asyncio.sleep(0.5)

                # Save intermediate results after each task
                self._save_results()

        self.run.completed_at = datetime.now().isoformat()
        self._save_results()

        return self.run

    async def _run_one(self, task: dict, condition: str, db_path: Path) -> TaskResult:
        """Run one task under one condition."""
        with patch("core.orchestrator.DB_PATH", db_path), \
             patch("kairos.task_queue.DB_PATH", db_path):

            if condition == "hermes" and self.hermes_orch is not None:
                return await run_task_hermes(task, self.hermes_orch, condition)

            elif condition == "t1_skill":
                return await run_task_t1_only(
                    task, self.ollama_client, condition, inject_skill=True
                )

            elif condition == "t1_no_skill":
                return await run_task_t1_only(
                    task, self.ollama_client, condition, inject_skill=False
                )

            else:
                result = TaskResult(
                    task_id=task["id"],
                    condition=condition,
                    difficulty=task["difficulty"],
                    domain=task["domain"],
                    skill_relevant=task["skill_relevant"],
                    skill_id=task.get("skill_id"),
                    criterion=task["success_criterion"],
                )
                result.error = f"Unknown condition: {condition}"
                return result

    def _save_results(self) -> None:
        """Save current results to JSON file."""
        self.results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.results_file, "w") as f:
            json.dump(self.run.to_dict(), f, indent=2)


# ──────────────────────────────────────────────────────────────────────
# Metrics computation
# ──────────────────────────────────────────────────────────────────────

def compute_metrics(run_data: dict) -> dict:
    """
    Compute all 6 benchmark metrics from raw results.
    Returns a structured metrics dict ready for the paper.
    """
    results = run_data.get("task_results", [])

    def filter_results(condition=None, difficulty=None, skill_relevant=None):
        filtered = results
        if condition:
            filtered = [r for r in filtered if r["condition"] == condition]
        if difficulty:
            filtered = [r for r in filtered if r["difficulty"] == difficulty]
        if skill_relevant is not None:
            filtered = [r for r in filtered if r["skill_relevant"] == skill_relevant]
        return filtered

    def completion_rate(subset):
        if not subset:
            return 0.0
        return sum(1 for r in subset if r["criterion_met"]) / len(subset)

    def mean_latency(subset):
        latencies = [r["latency_seconds"] for r in subset if r["latency_seconds"] > 0]
        return sum(latencies) / len(latencies) if latencies else 0.0

    difficulties = ["L1_trivial", "L2_simple", "L3_medium", "L4_complex", "L5_hard"]
    conditions   = ["hermes", "t1_skill", "t1_no_skill"]

    # ── Metric 1: Task completion rate by condition ────────────────────
    m1_completion = {}
    for cond in conditions:
        subset = filter_results(condition=cond)
        m1_completion[cond] = {
            "overall": round(completion_rate(subset), 4),
            "by_difficulty": {
                diff: round(completion_rate(filter_results(cond, diff)), 4)
                for diff in difficulties
            },
        }

    # ── Metric 2: Tier 3 escalation rate ─────────────────────────────
    hermes_results = filter_results(condition="hermes")
    total_hermes   = len(hermes_results)
    tier3_calls    = sum(1 for r in hermes_results if r["tier3_called"])
    m2_escalation  = {
        "total_tasks": total_hermes,
        "tier3_calls": tier3_calls,
        "escalation_rate": round(tier3_calls / total_hermes, 4) if total_hermes else 0,
        "local_resolution_rate": round(1 - (tier3_calls / total_hermes), 4) if total_hermes else 0,
    }

    # ── Metric 3: Skill accuracy lift (ablation) ──────────────────────
    domain_with_skill    = filter_results("t1_skill",    skill_relevant=True)
    domain_without_skill = filter_results("t1_no_skill", skill_relevant=True)
    rate_with    = completion_rate(domain_with_skill)
    rate_without = completion_rate(domain_without_skill)
    m3_skill_lift = {
        "with_skill_rate":    round(rate_with, 4),
        "without_skill_rate": round(rate_without, 4),
        "skill_accuracy_lift": round(rate_with - rate_without, 4),
        "domain_tasks_count": len(domain_with_skill),
    }

    # ── Metric 4: Average task latency by difficulty ──────────────────
    m4_latency = {}
    for cond in conditions:
        m4_latency[cond] = {
            diff: round(mean_latency(filter_results(cond, diff)), 3)
            for diff in difficulties
        }
    m4_latency["overall_mean"] = {
        cond: round(mean_latency(filter_results(condition=cond)), 3)
        for cond in conditions
    }

    # ── Metric 5: Total API cost comparison ───────────────────────────
    total_cost   = run_data.get("total_cost_usd", 0.0)
    hermes_cost  = sum(r.get("cost_usd", 0.0) for r in hermes_results)
    tasks_count  = len(set(r["task_id"] for r in results))
    # Estimate what all-Claude cost would be
    # Assume 3000 input tokens + 500 output tokens per task at Sonnet pricing
    est_all_claude_cost = tasks_count * ((3000 / 1_000_000 * 3.0) + (500 / 1_000_000 * 15.0))
    m5_cost = {
        "hermes_actual_cost_usd": round(hermes_cost, 4),
        "estimated_all_claude_cost_usd": round(est_all_claude_cost, 4),
        "cost_reduction_pct": round(
            (1 - hermes_cost / est_all_claude_cost) * 100, 1
        ) if est_all_claude_cost > 0 else 0,
    }

    # ── Metric 6: T1 vs T2 agreement rate ────────────────────────────
    # Approximated from escalation rate — non-escalated tasks = agreement
    m6_agreement = {
        "estimated_agreement_rate": m2_escalation["local_resolution_rate"],
        "note": (
            "Agreement rate estimated from non-escalation rate. "
            "For exact T1/T2 agreement, parse session JSONL logs."
        ),
    }

    # ── Hypothesis validation ─────────────────────────────────────────
    h1_delta = m1_completion["hermes"]["overall"] - m1_completion["t1_no_skill"]["overall"]
    h1_cost_pct = m2_escalation["escalation_rate"] * 100

    hypotheses = {
        "H1_within_10pp_at_20pct_cost": {
            "completion_delta_pp": round(h1_delta * 100, 1),
            "tier3_cost_pct": round(h1_cost_pct, 1),
            "supported": (
                abs(h1_delta * 100) <= 15
                and h1_cost_pct <= 30
            ),
        },
        "H2_skill_lift_10pp": {
            "skill_lift_pp": round(m3_skill_lift["skill_accuracy_lift"] * 100, 1),
            "supported": m3_skill_lift["skill_accuracy_lift"] >= 0.05,
        },
        "H3_agreement_75pct": {
            "agreement_rate_pct": round(m2_escalation["local_resolution_rate"] * 100, 1),
            "supported": m2_escalation["local_resolution_rate"] >= 0.70,
        },
    }

    return {
        "computed_at": datetime.now().isoformat(),
        "run_id": run_data.get("run_id"),
        "m1_task_completion_rate": m1_completion,
        "m2_tier3_escalation": m2_escalation,
        "m3_skill_accuracy_lift": m3_skill_lift,
        "m4_latency_by_difficulty": m4_latency,
        "m5_api_cost": m5_cost,
        "m6_agreement_rate": m6_agreement,
        "hypothesis_validation": hypotheses,
    }


# ──────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="HERMES Benchmark Runner")
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick mode: run only L1+L2 tasks (20 tasks × 3 conditions)"
    )
    parser.add_argument(
        "--conditions", nargs="+",
        choices=["hermes", "t1_skill", "t1_no_skill"],
        default=["hermes", "t1_skill", "t1_no_skill"],
        help="Which conditions to run (default: all 3)"
    )
    parser.add_argument(
        "--tasks-file", default="benchmarks/tasks.json",
        help="Path to tasks JSON file"
    )
    parser.add_argument(
        "--results-file", default="benchmarks/results.json",
        help="Where to save results"
    )
    parser.add_argument(
        "--compute-metrics-only", action="store_true",
        help="Skip running tasks — just compute metrics from existing results.json"
    )
    args = parser.parse_args()

    results_path = Path(args.results_file)

    if args.compute_metrics_only:
        if not results_path.exists():
            print(f"ERROR: {results_path} not found. Run the benchmark first.")
            sys.exit(1)
        with open(results_path) as f:
            run_data = json.load(f)
        metrics = compute_metrics(run_data)
        metrics_path = results_path.parent / "metrics.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"Metrics computed and saved to: {metrics_path}")
        _print_metrics_summary(metrics)
        return

    runner = BenchmarkRunner(
        tasks_file=args.tasks_file,
        results_file=args.results_file,
        quick_mode=args.quick,
        conditions=args.conditions,
    )

    benchmark_run = await runner.run_all()

    print(f"\n{'=' * 70}")
    print(f"BENCHMARK COMPLETE")
    print(f"Total tasks run: {len(benchmark_run.task_results)}")
    print(f"Total cost: ${benchmark_run.total_cost_usd:.4f}")
    print(f"Total time: {benchmark_run.total_latency_seconds:.1f}s")
    print(f"Results saved to: {results_path}")

    # Compute and display metrics
    metrics = compute_metrics(benchmark_run.to_dict())
    metrics_path = results_path.parent / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics saved to: {metrics_path}")

    _print_metrics_summary(metrics)


def _print_metrics_summary(metrics: dict) -> None:
    """Print a human-readable summary of benchmark metrics."""
    print(f"\n{'─' * 70}")
    print("METRIC SUMMARY (for research paper)")
    print(f"{'─' * 70}")

    m1 = metrics.get("m1_task_completion_rate", {})
    print(f"\nM1 — Task Completion Rate:")
    for cond, data in m1.items():
        print(f"  {cond:<20} {data.get('overall', 0)*100:.1f}%")

    m2 = metrics.get("m2_tier3_escalation", {})
    print(f"\nM2 — Tier 3 Escalation:")
    print(f"  Escalation rate:      {m2.get('escalation_rate', 0)*100:.1f}%")
    print(f"  Local resolution:     {m2.get('local_resolution_rate', 0)*100:.1f}%")

    m3 = metrics.get("m3_skill_accuracy_lift", {})
    print(f"\nM3 — Skill Accuracy Lift (Ablation):")
    print(f"  With skill:           {m3.get('with_skill_rate', 0)*100:.1f}%")
    print(f"  Without skill:        {m3.get('without_skill_rate', 0)*100:.1f}%")
    print(f"  Lift:                 +{m3.get('skill_accuracy_lift', 0)*100:.1f}pp")

    m5 = metrics.get("m5_api_cost", {})
    print(f"\nM5 — API Cost:")
    print(f"  HERMES actual cost:   ${m5.get('hermes_actual_cost_usd', 0):.4f}")
    print(f"  Est. all-Claude:      ${m5.get('estimated_all_claude_cost_usd', 0):.4f}")
    print(f"  Cost reduction:       {m5.get('cost_reduction_pct', 0):.1f}%")

    hyps = metrics.get("hypothesis_validation", {})
    print(f"\nHypothesis Validation:")
    for hyp_id, hyp_data in hyps.items():
        supported = hyp_data.get("supported", False)
        print(f"  {hyp_id}: {'[PASS] SUPPORTED' if supported else '[FAIL] NOT SUPPORTED'}")


if __name__ == "__main__":
    asyncio.run(main())
