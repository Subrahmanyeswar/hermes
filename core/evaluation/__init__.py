# core/evaluation/__init__.py
"""
Evaluation Subsystem for HERMES 2.x (Prompt 17).
Exports Functional Evaluator, Visual Evaluator, and Evaluation Harness.
"""

from core.evaluation.functional import (
    CheckLayer,
    CheckStatus,
    FunctionalCheck,
    FunctionalEvaluationResult,
    FunctionalEvaluator,
    FunctionalRequirement,
)
from core.evaluation.visual import (
    ResponsiveCheckResult,
    RubricCriterion,
    VisualCategory,
    VisualCheckResult,
    VisualCheckStatus,
    VisualEvaluationResult,
    VisualEvaluator,
    VisualRubric,
)
from core.evaluation.harness import (
    AggregatedEvaluationResult,
    EvalRunner,
    EvaluationCategory,
    EvaluationDifficulty,
    EvaluationSuiteRegistry,
    EvaluationTask,
    LatencyNoiseTracker,
    TaskRequirement,
    ToolMetricsTracker,
    TrialResult,
    suite_registry,
)

__all__ = [
    "CheckLayer",
    "CheckStatus",
    "FunctionalCheck",
    "FunctionalEvaluationResult",
    "FunctionalEvaluator",
    "FunctionalRequirement",
    "ResponsiveCheckResult",
    "RubricCriterion",
    "VisualCategory",
    "VisualCheckResult",
    "VisualCheckStatus",
    "VisualEvaluationResult",
    "VisualEvaluator",
    "VisualRubric",
    "AggregatedEvaluationResult",
    "EvalRunner",
    "EvaluationCategory",
    "EvaluationDifficulty",
    "EvaluationSuiteRegistry",
    "EvaluationTask",
    "LatencyNoiseTracker",
    "TaskRequirement",
    "ToolMetricsTracker",
    "TrialResult",
    "suite_registry",
]
