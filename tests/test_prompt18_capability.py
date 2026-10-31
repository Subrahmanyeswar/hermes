# tests/test_prompt18_capability.py
"""
Prompt 18: Capability Evaluation, Solvability Gate, Multi-Trial Aggregation,
Outcome-Based Grading, and Negative Capability Verification.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
import pytest

from core.evaluation.functional.models import (
    CheckLayer,
    CheckStatus,
    FunctionalCheck,
    FunctionalRequirement,
)
from core.evaluation.harness.models import (
    EvaluationCategory,
    EvaluationDifficulty,
    EvaluationTask,
    TaskRequirement,
)
from core.evaluation.harness.metrics import LatencyNoiseTracker, ToolMetricsTracker
from core.evaluation.harness.runner import EvalRunner
from core.evaluation.harness.suites import suite_registry


@pytest.mark.asyncio
async def test_solvability_gate_reference_solution_passes():
    """
    Section 6 & 28: Task Solvability Gate.
    Every capability task must be verified solvable by a reference implementation.
    If a reference solution cannot pass, it indicates a broken task/grader, not agent failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()
        
        # 1. Setup reference solution for simple file edit task
        config_file = ws_root / "config.json"
        config_file.write_text(json.dumps({"version": "1.1.0", "env": "production"}), encoding="utf-8")
        
        task = suite_registry.get_task("cap_simple_file_edit")
        assert task is not None, "Task cap_simple_file_edit must be registered"
        
        runner = EvalRunner(base_runs_dir=ws_root / "evals")
        res = await runner.run_task(task, workspace_dir=ws_root)
        
        # Solvability requirement: Reference solution must achieve 100% pass rate
        assert res.overall_status == "PASS"
        assert res.pass_rate == 1.0
        assert res.pass_count == 1
        assert res.fail_count == 0


@pytest.mark.asyncio
async def test_outcome_based_final_state_grading():
    """
    Section 21: Evidence-first final environment state grading.
    Verifies that grading evaluates actual disk state, not merely assistant self-reports.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()
        
        # Scenario A: Code self-reports success in stdout, but file content on disk is wrong
        index_file = ws_root / "index.html"
        index_file.write_text("<html><body>Unfinished Draft</body></html>", encoding="utf-8")
        
        task = EvaluationTask(
            task_id="test_outcome_grading",
            name="Outcome Grading Validation",
            category=EvaluationCategory.CAPABILITY,
            difficulty=EvaluationDifficulty.SIMPLE,
            prompt="Ensure index.html contains production title",
            functional_checks=[
                FunctionalCheck(
                    check_id="chk_title",
                    name="Production Title Check",
                    layer=CheckLayer.STATIC,
                    expected="Production Dashboard",
                )
            ],
            trial_count=1,
        )
        
        runner = EvalRunner(base_runs_dir=ws_root / "evals")
        res_fail = await runner.run_task(task, workspace_dir=ws_root)
        assert res_fail.overall_status == "FAIL", "Grader must reject incomplete filesystem state"
        
        # Scenario B: Actually correct disk state
        index_file.write_text("<html><body>Production Dashboard</body></html>", encoding="utf-8")
        res_pass = await runner.run_task(task, workspace_dir=ws_root)
        assert res_pass.overall_status == "PASS", "Grader must pass verified filesystem state"


@pytest.mark.asyncio
async def test_multi_trial_statistical_aggregation():
    """
    Section 22: Multi-Trial Evaluation metrics aggregation (pass@k, pass^k, median, p95).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()
        
        # Create a task configured with trial_count = 3
        task = EvaluationTask(
            task_id="test_multi_trial_stats",
            name="Multi-Trial Statistical Aggregation",
            category=EvaluationCategory.CAPABILITY,
            difficulty=EvaluationDifficulty.SIMPLE,
            prompt="Verify syntax",
            functional_checks=[
                FunctionalCheck(
                    check_id="chk_py",
                    name="Python file presence",
                    layer=CheckLayer.STATIC,
                    expected="test.py",
                )
            ],
            trial_count=3,
        )
        (ws_root / "test.py").write_text("print('hello')\n", encoding="utf-8")
        
        runner = EvalRunner(base_runs_dir=ws_root / "evals")
        res = await runner.run_task(task, workspace_dir=ws_root)
        
        assert res.trial_count == 3
        assert res.pass_count == 3
        assert res.pass_rate == 1.0
        assert res.is_flaky is False
        assert res.median_duration >= 0.0
        assert res.p95_duration >= res.median_duration
        
        # Verify serialized dict schema
        data = res.to_dict()
        assert "task_id" in data
        assert "pass_rate" in data
        assert "median_duration" in data
        assert "trials" in data
        assert len(data["trials"]) == 3


@pytest.mark.asyncio
async def test_negative_capability_non_action_stop():
    """
    Section 18: Negative-Capability Tests.
    Agent must not perform unprompted file modifications or unnecessary tools
    when instructed purely to query status or stop.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()
        canary = ws_root / "canary.txt"
        canary.write_text("ORIGINAL_CANARY", encoding="utf-8")
        
        task = suite_registry.get_task("cap_negative_non_action_stop")
        assert task is not None
        
        # Execute query task
        runner = EvalRunner(base_runs_dir=ws_root / "evals")
        res = await runner.run_task(task, workspace_dir=ws_root)
        
        # Verify canary was not mutated
        assert canary.read_text(encoding="utf-8") == "ORIGINAL_CANARY"
        assert res.overall_status == "PASS"


@pytest.mark.asyncio
async def test_flakiness_detection_across_trials():
    """
    Section 82 & 132: Flakiness detection when trials produce inconsistent outcomes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()
        
        counter = {"count": 0}
        
        # Create a task where check alternates based on trial
        class FlakyCheckTask(EvaluationTask):
            pass

        task = EvaluationTask(
            task_id="test_flaky_task",
            name="Flaky Inconsistency Test",
            category=EvaluationCategory.CAPABILITY,
            difficulty=EvaluationDifficulty.MEDIUM,
            prompt="Simulate intermittent environment check",
            trial_count=3,
        )
        
        runner = EvalRunner(base_runs_dir=ws_root / "evals")
        # In trial 1: file exists; trial 2: delete file; trial 3: recreate
        target_f = ws_root / "temp_trial.txt"
        target_f.write_text("EXISTS", encoding="utf-8")
        
        task.functional_checks = [
            FunctionalCheck(
                check_id="chk_intermittent",
                name="Check File",
                layer=CheckLayer.STATIC,
                expected="temp_trial.txt",
            )
        ]
        
        # First trial: passes
        t1 = await runner._run_single_trial(task, "tr_1", 1, ws_root)
        assert t1.status == "PASS"
        
        # Delete file before trial 2
        target_f.unlink()
        t2 = await runner._run_single_trial(task, "tr_2", 2, ws_root)
        assert t2.status == "FAIL"
        
        # Recreate before trial 3
        target_f.write_text("EXISTS", encoding="utf-8")
        t3 = await runner._run_single_trial(task, "tr_3", 3, ws_root)
        assert t3.status == "PASS"
        
        # Manually verify aggregation flags flakiness
        pass_count = sum(1 for t in [t1, t2, t3] if t.status == "PASS")
        fail_count = sum(1 for t in [t1, t2, t3] if t.status == "FAIL")
        is_flaky = pass_count > 0 and fail_count > 0
        assert is_flaky is True


@pytest.mark.asyncio
async def test_capability_regression_guard_properties_abc():
    """
    Capability Regression Guard (Prompt 18 Continuation 2):
    PROPERTY A: Existing files must still use the original LSP/static diagnostic behavior.
    PROPERTY B: Expected value 'clean' must not accidentally require a literal file named 'clean'.
    PROPERTY C: Outcome-based grading must be able to locate an expected string inside an HTML file
               without requiring one hard-coded filename.
    """
    from core.evaluation.functional.evaluator import FunctionalEvaluator
    from core.evaluation.functional.models import FunctionalCheck, CheckLayer, CheckStatus
    from core.code_intelligence.manager import CodeIntelligenceManager

    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()
        lsp_mgr = CodeIntelligenceManager(workspace_root=ws_root, enable_lsp=False)
        evaluator = FunctionalEvaluator(workspace_root=ws_root, lsp_manager=lsp_mgr)

        # Property A: Existing file passes static check
        code_file = ws_root / "module.py"
        code_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        chk_a = FunctionalCheck(
            check_id="chk_a",
            name="Property A Check",
            layer=CheckLayer.STATIC,
            expected="module.py",
        )
        await evaluator._evaluate_static_check(chk_a)
        assert chk_a.status == CheckStatus.PASS
        assert "No syntax" in chk_a.actual

        # Property B: Expected value "clean" passes without a file named "clean"
        assert not (ws_root / "clean").exists()
        chk_b = FunctionalCheck(
            check_id="chk_b",
            name="Property B Clean Check",
            layer=CheckLayer.STATIC,
            expected="clean",
        )
        await evaluator._evaluate_static_check(chk_b)
        assert chk_b.status == CheckStatus.PASS
        assert "clean" in chk_b.actual

        # Property C: Outcome-based grading finds substring in arbitrary HTML file
        subfolder = ws_root / "nested" / "templates"
        subfolder.mkdir(parents=True, exist_ok=True)
        arbitrary_html = subfolder / "view_custom_target.html"
        arbitrary_html.write_text("<main><h1>System Status Dashboard</h1></main>", encoding="utf-8")

        chk_c = FunctionalCheck(
            check_id="chk_c",
            name="Property C Outcome Check",
            layer=CheckLayer.STATIC,
            expected="System Status Dashboard",
        )
        await evaluator._evaluate_static_check(chk_c)
        assert chk_c.status == CheckStatus.PASS
        assert "Found expected substring" in chk_c.actual

        # Missing substring fails cleanly
        chk_c_fail = FunctionalCheck(
            check_id="chk_c_fail",
            name="Property C Outcome Missing",
            layer=CheckLayer.STATIC,
            expected="Nonexistent Dashboard String",
        )
        await evaluator._evaluate_static_check(chk_c_fail)
        assert chk_c_fail.status == CheckStatus.FAIL
        assert "not found in any HTML file" in chk_c_fail.actual

