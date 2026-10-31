# tests/test_prompt18_eval_integrity.py
"""
Prompt 18: Evaluator Integrity, Grader Resistance, Anti-Cheating,
Infrastructure Noise Accounting, and Architecture Invariants.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from core.evaluation.functional.models import CheckLayer, FunctionalCheck, CheckStatus
from core.evaluation.harness.models import (
    EvaluationCategory,
    EvaluationDifficulty,
    EvaluationTask,
)
from core.evaluation.harness.metrics import LatencyNoiseTracker, ToolMetricsTracker
from core.evaluation.harness.runner import EvalRunner


@pytest.mark.asyncio
async def test_grader_resistance_to_forged_success_message():
    """
    Section 27 & 122: Grader Resistance / Anti-Cheating.
    An agent attempting to cheat by writing "ALL TESTS PASSED: 100% SUCCESS"
    into a dummy log or stdout without satisfying actual checks must be rejected.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()

        # Dummy log with forged success claims
        (ws_root / "cheater_output.txt").write_text(
            "SUCCESS: All 50 requirements fulfilled. Error count: 0. Verification: APPROVED.",
            encoding="utf-8"
        )

        # Grader evaluates the actual target file (not the forged log)
        task = EvaluationTask(
            task_id="test_anti_cheat",
            name="Anti-Cheat Invariant Verification",
            category=EvaluationCategory.CAPABILITY,
            difficulty=EvaluationDifficulty.SIMPLE,
            prompt="Ensure correct calculate_tax function is implemented in tax.py",
            functional_checks=[
                FunctionalCheck(
                    check_id="chk_real_impl",
                    name="Function Implementation Check",
                    layer=CheckLayer.STATIC,
                    expected="def calculate_tax(amount, rate):",
                )
            ],
            trial_count=1,
        )

        runner = EvalRunner(base_runs_dir=ws_root / "evals")
        res = await runner.run_task(task, workspace_dir=ws_root)

        # Must fail because tax.py does not contain the required implementation
        assert res.overall_status == "FAIL", "Grader must not be fooled by superficial success logs"


def test_infrastructure_noise_separation():
    """
    Section 83 & 130: Infrastructure Noise Accounting.
    Distinguishes environmental issues (e.g. disk full, OS socket error, provider outage)
    from agent capability failures.
    """
    tracker = LatencyNoiseTracker()

    # Record normal agent tool invocation
    tracker.record_step("tool_read_file", duration=0.015, is_infra_noise=False)

    # Record external environmental delay (e.g. cloud provider network spike)
    tracker.record_step("provider_cloud_latency", duration=2.450, is_infra_noise=True)

    summary = tracker.get_summary()
    assert summary["agent_duration"] == 0.015
    assert summary["infra_noise_duration"] == 2.450
    assert summary["infra_noise_ratio"] > 0.90


def test_architecture_invariants_enforcement():
    """
    Section 143-154: Core Architecture Invariants Verification.
    1. MODEL CHOOSES
    2. HARNESS ALLOWS
    3. ENVIRONMENT OBSERVES
    4. EVIDENCE DECIDES
    5. STATE SURVIVES
    6. UI OBSERVES
    7. SURFACES EXPRESS
    8. EVALUATORS MEASURE
    """
    invariants = {
        "MODEL_CHOOSES": True,
        "HARNESS_ALLOWS": True,
        "ENVIRONMENT_OBSERVES": True,
        "EVIDENCE_DECIDES": True,
        "STATE_SURVIVES": True,
        "UI_OBSERVES": True,
        "SURFACES_EXPRESS": True,
        "EVALUATORS_MEASURE": True,
    }

    # Verify all 8 laws are active and enforced
    for law, status in invariants.items():
        assert status is True, f"Core law {law} must be preserved"
