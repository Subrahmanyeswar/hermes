# core/evaluation/harness/models.py
"""
Data models for Evaluation Harness (Prompt 17).
Defines tasks, requirements, trials, aggregated scorecard results, and suites.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.evaluation.functional.models import FunctionalCheck, FunctionalEvaluationResult
from core.evaluation.visual.models import VisualEvaluationResult


class EvaluationCategory(str, Enum):
    CAPABILITY = "CAPABILITY"
    REGRESSION = "REGRESSION"
    HELDOUT = "HELDOUT"
    CHAOS = "CHAOS"
    SECURITY = "SECURITY"
    SOAK = "SOAK"


class EvaluationDifficulty(str, Enum):
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"


@dataclass
class TaskRequirement:
    req_id: str
    title: str
    description: str = ""
    is_required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "req_id": self.req_id,
            "title": self.title,
            "description": self.description,
            "is_required": self.is_required,
        }


@dataclass
class EvaluationTask:
    """Definition of an evaluation task executed by the harness."""
    task_id: str
    name: str
    category: EvaluationCategory
    difficulty: EvaluationDifficulty
    prompt: str
    requirements: List[TaskRequirement] = field(default_factory=list)
    functional_checks: List[FunctionalCheck] = field(default_factory=list)
    workspace_fixture: Optional[str] = None
    requires_browser: bool = False
    requires_visual: bool = False
    trial_count: int = 1
    timeout_seconds: float = 60.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "category": self.category.value,
            "difficulty": self.difficulty.value,
            "prompt": self.prompt,
            "requirements": [r.to_dict() for r in self.requirements],
            "functional_checks": [c.to_dict() for c in self.functional_checks],
            "workspace_fixture": self.workspace_fixture,
            "requires_browser": self.requires_browser,
            "requires_visual": self.requires_visual,
            "trial_count": self.trial_count,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass
class TrialResult:
    """Execution outcome of a single trial run."""
    trial_id: str
    trial_index: int
    status: str  # PASS, FAIL, BLOCKED, PARTIAL
    functional_result: Optional[FunctionalEvaluationResult] = None
    visual_result: Optional[VisualEvaluationResult] = None
    duration_seconds: float = 0.0
    tool_metrics: Dict[str, int] = field(default_factory=dict)
    latency_breakdown: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def is_passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "trial_index": self.trial_index,
            "status": self.status,
            "duration": round(self.duration_seconds, 3),
            "functional": self.functional_result.to_dict() if self.functional_result else None,
            "visual": self.visual_result.to_dict() if self.visual_result else None,
            "tool_metrics": self.tool_metrics,
            "latency_breakdown": {k: round(v, 3) for k, v in self.latency_breakdown.items()},
            "error": self.error,
        }


@dataclass
class AggregatedEvaluationResult:
    """Multi-trial statistical aggregation and scorecard for an evaluation task."""
    task_id: str
    task_name: str
    category: str
    trial_count: int
    pass_count: int
    fail_count: int
    blocked_count: int
    pass_rate: float
    is_flaky: bool
    median_duration: float
    p95_duration: float
    failure_modes: List[str]
    overall_status: str  # PASS, FAIL, FLAKY, BLOCKED
    trials: List[TrialResult] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "category": self.category,
            "trial_count": self.trial_count,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "blocked_count": self.blocked_count,
            "pass_rate": round(self.pass_rate, 2),
            "is_flaky": self.is_flaky,
            "median_duration": round(self.median_duration, 3),
            "p95_duration": round(self.p95_duration, 3),
            "failure_modes": self.failure_modes,
            "overall_status": self.overall_status,
            "trials": [t.to_dict() for t in self.trials],
            "timestamp": self.timestamp,
        }
