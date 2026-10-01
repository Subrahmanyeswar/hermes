# tests/test_prompt17_eval_harness.py
"""
Test Suite: Prompt 17 Evaluation Harness.
Validates multi-trial task execution, statistical aggregation,
metrics and latency noise tracking, and report.md / result.json generation.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.evaluation.functional.models import CheckLayer, FunctionalCheck
from core.evaluation.harness.metrics import LatencyNoiseTracker, ToolMetricsTracker
from core.evaluation.harness.models import (
    EvaluationCategory,
    EvaluationDifficulty,
    EvaluationTask,
)
from core.evaluation.harness.runner import EvalRunner
from core.evaluation.harness.suites import EvaluationSuiteRegistry


def test_tool_metrics_and_noise_tracking():
    """Verify tool calls, failure counts, and latency tracking."""
    tracker = ToolMetricsTracker()
    tracker.record_call("lsp_definition", success=True)
    tracker.record_call("browser_navigate", success=True)
    tracker.record_call("browser_click", success=False)
    # Redundant consecutive call
    tracker.record_call("browser_click", success=True)

    data = tracker.to_dict()
    assert data["lsp_calls"] == 1
    assert data["browser_calls"] == 3
    assert data["failed_calls"] == 1
    assert data["redundant_calls"] == 1

    noise = LatencyNoiseTracker(
        time_to_first_model=0.5,
        time_in_model=2.0,
        time_in_lsp=0.2,
        time_in_browser=1.1,
        time_in_evaluator=0.4,
        time_total=4.2,
    )
    nd = noise.to_dict()
    assert nd["time_in_model"] == 2.0
    assert nd["time_in_browser"] == 1.1


def test_suite_registry():
    """Verify default evaluation tasks are registered and filterable."""
    registry = EvaluationSuiteRegistry()
    all_tasks = registry.list_all_tasks()
    assert len(all_tasks) >= 4

    cap_tasks = registry.get_tasks_by_category(EvaluationCategory.CAPABILITY)
    assert len(cap_tasks) >= 2
    assert any(t.task_id == "cap_web_transaction_dashboard" for t in cap_tasks)

    reg_tasks = registry.get_tasks_by_category(EvaluationCategory.REGRESSION)
    assert len(reg_tasks) >= 2


@pytest.mark.asyncio
async def test_eval_runner_multi_trial_execution(tmp_path: Path):
    """Verify EvalRunner executes multiple trials, aggregates statistics, and writes reports."""
    runs_dir = tmp_path / "eval_runs"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create dummy app file
    index_file = workspace / "index.html"
    index_file.write_text("<html><head><title>App</title></head><body><h1>Dashboard</h1></body></html>", encoding="utf-8")

    task = EvaluationTask(
        task_id="test_task_multi_trial",
        name="Multi Trial Test",
        category=EvaluationCategory.CAPABILITY,
        difficulty=EvaluationDifficulty.SIMPLE,
        prompt="Verify dashboard exists",
        functional_checks=[
            FunctionalCheck(
                check_id="chk_file",
                name="Check file exists",
                layer=CheckLayer.STATIC,
                expected="index.html",
            )
        ],
        trial_count=3,
    )

    runner = EvalRunner(base_runs_dir=runs_dir, prefer_cdp=False)
    agg_res = await runner.run_task(task, workspace_dir=workspace)

    assert agg_res.task_id == "test_task_multi_trial"
    assert agg_res.trial_count == 3
    assert agg_res.pass_count == 3
    assert agg_res.fail_count == 0
    assert agg_res.pass_rate == 1.0
    assert not agg_res.is_flaky
    assert agg_res.overall_status == "PASS"

    # Verify reports generated on disk
    task_dir = runs_dir / "test_task_multi_trial"
    assert (task_dir / "result.json").exists()
    assert (task_dir / "report.md").exists()

    result_json = json.loads((task_dir / "result.json").read_text(encoding="utf-8"))
    assert result_json["pass_rate"] == 1.0
    assert len(result_json["trials"]) == 3

    report_md = (task_dir / "report.md").read_text(encoding="utf-8")
    assert "# Evaluation Report:" in report_md
    assert "100.0%" in report_md
