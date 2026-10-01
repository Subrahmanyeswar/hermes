# core/evaluation/harness/__init__.py
"""
Evaluation Harness Subsystem for HERMES 2.x (Prompt 17).
"""

from core.evaluation.harness.models import (
    AggregatedEvaluationResult,
    EvaluationCategory,
    EvaluationDifficulty,
    EvaluationTask,
    TaskRequirement,
    TrialResult,
)
from core.evaluation.harness.metrics import (
    LatencyNoiseTracker,
    ToolMetricsTracker,
)
from core.evaluation.harness.runner import EvalRunner
from core.evaluation.harness.suites import (
    EvaluationSuiteRegistry,
    suite_registry,
)

__all__ = [
    "AggregatedEvaluationResult",
    "EvaluationCategory",
    "EvaluationDifficulty",
    "EvaluationTask",
    "TaskRequirement",
    "TrialResult",
    "LatencyNoiseTracker",
    "ToolMetricsTracker",
    "EvalRunner",
    "EvaluationSuiteRegistry",
    "suite_registry",
]
