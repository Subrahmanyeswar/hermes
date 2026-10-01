# core/evaluation/visual/models.py
"""
Data models for Visual Evaluation (Prompt 17).
Defines visual categories, rubric criteria, check results, and evaluation summaries.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class VisualCategory(str, Enum):
    DESIGN_QUALITY = "DESIGN_QUALITY"
    LAYOUT = "LAYOUT"
    VISUAL_HIERARCHY = "VISUAL_HIERARCHY"
    TYPOGRAPHY = "TYPOGRAPHY"
    SPACING = "SPACING"
    COLOR_CONTRAST = "COLOR_CONTRAST"
    COMPONENT_CONSISTENCY = "COMPONENT_CONSISTENCY"
    RESPONSIVE_BEHAVIOR = "RESPONSIVE_BEHAVIOR"
    INTERACTION_CLARITY = "INTERACTION_CLARITY"
    ORIGINALITY = "ORIGINALITY"
    ACCESSIBILITY_SIGNALS = "ACCESSIBILITY_SIGNALS"


class VisualCheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class VisualCheckResult:
    """Outcome for a single visual category or deterministic check."""
    category: VisualCategory
    status: VisualCheckStatus
    score: float = 0.0  # 0.0 to 1.0
    weight: float = 1.0
    details: str = ""
    evidence_artifact_ids: List[str] = field(default_factory=list)
    reproduction_note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "status": self.status.value,
            "score": round(self.score, 2),
            "weight": self.weight,
            "details": self.details,
            "evidence_artifact_ids": self.evidence_artifact_ids,
            "reproduction_note": self.reproduction_note,
        }


@dataclass
class ResponsiveCheckResult:
    """Results of checking layout across multiple device viewports."""
    viewport_name: str
    width: int
    height: int
    has_horizontal_overflow: bool = False
    interactive_elements_visible: bool = True
    screenshot_artifact_id: Optional[str] = None
    issues: List[str] = field(default_factory=list)

    @property
    def is_passed(self) -> bool:
        return not self.has_horizontal_overflow and self.interactive_elements_visible and not self.issues

    def to_dict(self) -> Dict[str, Any]:
        return {
            "viewport": self.viewport_name,
            "dimensions": f"{self.width}x{self.height}",
            "passed": self.is_passed,
            "has_horizontal_overflow": self.has_horizontal_overflow,
            "interactive_elements_visible": self.interactive_elements_visible,
            "screenshot_id": self.screenshot_artifact_id,
            "issues": self.issues,
        }


@dataclass
class VisualEvaluationResult:
    """Overall outcome of visual evaluation across deterministic backstops, responsive tests, and rubric."""
    evaluation_id: str
    task_id: str
    overall_status: VisualCheckStatus
    overall_score: float  # 0.0 - 1.0
    threshold: float = 0.70
    category_results: List[VisualCheckResult] = field(default_factory=list)
    responsive_results: List[ResponsiveCheckResult] = field(default_factory=list)
    deterministic_issues: List[str] = field(default_factory=list)
    comments: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "task_id": self.task_id,
            "status": self.overall_status.value,
            "overall_score": round(self.overall_score, 2),
            "threshold": self.threshold,
            "deterministic_issues": self.deterministic_issues,
            "categories": [c.to_dict() for c in self.category_results],
            "responsive": [r.to_dict() for r in self.responsive_results],
            "comments": self.comments,
            "timestamp": self.timestamp,
        }
