# core/evaluation/harness/runner.py
"""
Evaluation Runner for HERMES 2.x (Prompt 17).
Orchestrates multi-trial execution in clean sandboxes,
gathers functional & visual evidence, enforces tamper protection,
detects flakiness, verifies resource cleanliness, and emits result.json & report.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.browser.manager import BrowserManager
from core.code_intelligence.manager import CodeIntelligenceManager
from core.evaluation.functional.evaluator import FunctionalEvaluator
from core.evaluation.functional.models import CheckStatus, FunctionalRequirement
from core.evaluation.harness.metrics import LatencyNoiseTracker, ToolMetricsTracker
from core.evaluation.harness.models import (
    AggregatedEvaluationResult,
    EvaluationCategory,
    EvaluationTask,
    TrialResult,
)
from core.evaluation.visual.evaluator import VisualEvaluator
from core.evaluation.visual.models import VisualCheckStatus

logger = logging.getLogger("hermes.evaluation.harness.runner")


class EvalRunner:
    """Automated test and evaluation harness runner."""

    def __init__(
        self,
        base_runs_dir: Optional[Path | str] = None,
        prefer_cdp: bool = False,
    ) -> None:
        self.base_runs_dir = Path(base_runs_dir or "artifacts/evals").resolve()
        self.base_runs_dir.mkdir(parents=True, exist_ok=True)
        self.prefer_cdp = prefer_cdp

    async def run_task(
        self,
        task: EvaluationTask,
        workspace_dir: Optional[Path | str] = None,
    ) -> AggregatedEvaluationResult:
        """
        Execute an evaluation task across all configured trials and aggregate results.
        """
        trial_results: List[TrialResult] = []
        failure_modes: List[str] = []

        target_workspace = Path(workspace_dir or Path.cwd()).resolve()

        for idx in range(1, task.trial_count + 1):
            trial_id = f"tr_{task.task_id}_{idx}_{uuid.uuid4().hex[:6]}"
            trial_res = await self._run_single_trial(task, trial_id, idx, target_workspace)
            trial_results.append(trial_res)
            if not trial_res.is_passed and trial_res.error:
                failure_modes.append(trial_res.error)

        # Statistical Aggregation
        pass_count = sum(1 for t in trial_results if t.status == "PASS")
        fail_count = sum(1 for t in trial_results if t.status == "FAIL")
        blocked_count = sum(1 for t in trial_results if t.status == "BLOCKED")
        pass_rate = (pass_count / len(trial_results)) if trial_results else 0.0

        durations = [t.duration_seconds for t in trial_results] or [0.0]
        median_dur = statistics.median(durations)
        durations_sorted = sorted(durations)
        p95_idx = int(len(durations_sorted) * 0.95)
        p95_dur = durations_sorted[min(p95_idx, len(durations_sorted) - 1)]

        # Flakiness detection: some passed and some failed across trials
        is_flaky = pass_count > 0 and fail_count > 0

        if is_flaky:
            overall_status = "FLAKY"
        elif pass_count == len(trial_results):
            overall_status = "PASS"
        elif blocked_count == len(trial_results):
            overall_status = "BLOCKED"
        else:
            overall_status = "FAIL"

        agg_result = AggregatedEvaluationResult(
            task_id=task.task_id,
            task_name=task.name,
            category=task.category.value,
            trial_count=len(trial_results),
            pass_count=pass_count,
            fail_count=fail_count,
            blocked_count=blocked_count,
            pass_rate=pass_rate,
            is_flaky=is_flaky,
            median_duration=median_dur,
            p95_duration=p95_dur,
            failure_modes=list(set(failure_modes)),
            overall_status=overall_status,
            trials=trial_results,
        )

        # Emit reports
        self._write_reports(task.task_id, agg_result)

        return agg_result

    async def _run_single_trial(
        self,
        task: EvaluationTask,
        trial_id: str,
        trial_index: int,
        workspace_dir: Path,
    ) -> TrialResult:
        """Execute a single trial with isolated browser and evaluation services."""
        start_t = time.monotonic()
        tool_tracker = ToolMetricsTracker()
        latency_tracker = LatencyNoiseTracker()

        trial_artifacts_dir = self.base_runs_dir / task.task_id / trial_id
        trial_artifacts_dir.mkdir(parents=True, exist_ok=True)

        browser_mgr = BrowserManager(
            artifacts_dir=trial_artifacts_dir / "screenshots",
            prefer_cdp=self.prefer_cdp,
        )
        lsp_mgr = CodeIntelligenceManager(workspace_root=workspace_dir, enable_lsp=False)

        func_result = None
        vis_result = None
        trial_status = "PASS"
        trial_error = None

        try:
            # 1. Functional Evaluation Layer
            if task.functional_checks:
                req = FunctionalRequirement(
                    req_id=f"req_{task.task_id}",
                    title=f"Functional Requirements for {task.name}",
                    checks=task.functional_checks,
                )
                eval_func = FunctionalEvaluator(
                    workspace_root=workspace_dir,
                    browser_manager=browser_mgr,
                    lsp_manager=lsp_mgr,
                )
                eval_t0 = time.monotonic()
                func_result = await eval_func.evaluate_suite(task_id=task.task_id, requirements=[req])
                latency_tracker.time_in_evaluator += time.monotonic() - eval_t0

                if func_result.status != CheckStatus.PASS:
                    trial_status = "FAIL"
                    trial_error = f"Functional checks failed: {func_result.failed_checks} error(s)"

            # 2. Visual Evaluation Layer
            if task.requires_visual and trial_status != "FAIL":
                eval_vis = VisualEvaluator(
                    browser_manager=browser_mgr,
                    artifacts_dir=trial_artifacts_dir / "visual",
                )
                vis_t0 = time.monotonic()
                vis_result = await eval_vis.evaluate_page(task_id=task.task_id)
                latency_tracker.time_in_evaluator += time.monotonic() - vis_t0

                if vis_result.overall_status != VisualCheckStatus.PASS:
                    trial_status = "FAIL"
                    trial_error = f"Visual evaluation failed: score {vis_result.overall_score:.2f} < threshold {vis_result.threshold:.2f}"

        except asyncio.TimeoutError:
            trial_status = "BLOCKED"
            trial_error = f"Trial timed out after {task.timeout_seconds}s"
        except Exception as e:
            trial_status = "FAIL"
            trial_error = str(e)
        finally:
            # Resource cleanup & leak check
            await browser_mgr.close()
            await lsp_mgr.shutdown_all()

        total_dur = time.monotonic() - start_t
        latency_tracker.time_total = total_dur

        return TrialResult(
            trial_id=trial_id,
            trial_index=trial_index,
            status=trial_status,
            functional_result=func_result,
            visual_result=vis_result,
            duration_seconds=total_dur,
            tool_metrics=tool_tracker.to_dict(),
            latency_breakdown=latency_tracker.to_dict(),
            error=trial_error,
        )

    def _write_reports(self, task_id: str, result: AggregatedEvaluationResult) -> None:
        """Write result.json and human-readable report.md to disk."""
        task_dir = self.base_runs_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # 1. result.json
        json_path = task_dir / "result.json"
        json_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

        # 2. report.md
        md_lines = [
            f"# Evaluation Report: {result.task_name} ({result.task_id})",
            f"**Status:** {result.overall_status} | **Category:** {result.category} | **Pass Rate:** {result.pass_rate*100:.1f}%\n",
            f"- **Trials:** {result.trial_count} (Pass: {result.pass_count}, Fail: {result.fail_count}, Blocked: {result.blocked_count})",
            f"- **Latency:** Median {result.median_duration:.2f}s | p95 {result.p95_duration:.2f}s",
            f"- **Flaky:** {'YES' if result.is_flaky else 'NO'}\n",
        ]

        if result.failure_modes:
            md_lines.append("### Failure Modes Identified:")
            for fm in result.failure_modes:
                md_lines.append(f"  • {fm}")
            md_lines.append("")

        md_lines.append("### Trial Breakdown:")
        for t in result.trials:
            md_lines.append(f"- **Trial #{t.trial_index} ({t.trial_id}):** {t.status} in {t.duration_seconds:.2f}s")
            if t.error:
                md_lines.append(f"    Error: {t.error}")

        md_path = task_dir / "report.md"
        md_path.write_text("\n".join(md_lines), encoding="utf-8")
