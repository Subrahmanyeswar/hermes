# core/evaluation/functional/models.py
"""
Data models for Functional Evaluation (Prompt 17).
Defines check layers, statuses, structured findings, and evaluation results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class CheckLayer(str, Enum):
    STATIC = "STATIC"            # Syntax, linting, LSP diagnostics
    TESTS = "TESTS"              # Unit / integration test suites
    RUNTIME = "RUNTIME"          # Process alive, port bound, HTTP ready
    API = "API"                  # HTTP endpoints, response contracts
    BROWSER = "BROWSER"          # UI element visibility, interactions
    PERSISTENCE = "PERSISTENCE"  # State preservation across reload / storage


@dataclass
class FunctionalCheck:
    """An individual verifiable condition evaluated by the functional evaluator."""
    check_id: str
    name: str
    layer: CheckLayer
    description: str = ""
    is_required: bool = True
    expected: str = ""
    actual: str = ""
    status: CheckStatus = CheckStatus.UNKNOWN
    duration_seconds: float = 0.0
    evidence_ids: List[str] = field(default_factory=list)
    failure_reason: Optional[str] = None
    reproduction_steps: List[str] = field(default_factory=list)
    suspected_location: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "layer": self.layer.value,
            "is_required": self.is_required,
            "status": self.status.value,
            "expected": self.expected,
            "actual": self.actual,
            "duration": round(self.duration_seconds, 3),
            "failure_reason": self.failure_reason,
            "evidence_ids": self.evidence_ids,
            "suspected_location": self.suspected_location,
        }


@dataclass
class FunctionalRequirement:
    """A requirement composed of one or more acceptance checks."""
    req_id: str
    title: str
    description: str = ""
    checks: List[FunctionalCheck] = field(default_factory=list)

    @property
    def is_passed(self) -> bool:
        required = [c for c in self.checks if c.is_required]
        return all(c.status == CheckStatus.PASS for c in required)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "req_id": self.req_id,
            "title": self.title,
            "is_passed": self.is_passed,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class FunctionalEvaluationResult:
    """Overall outcome of functional evaluation across all requirements."""
    evaluation_id: str
    task_id: str
    status: CheckStatus
    requirements: List[FunctionalRequirement] = field(default_factory=list)
    passed_checks: int = 0
    failed_checks: int = 0
    blocked_checks: int = 0
    duration_seconds: float = 0.0
    findings: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "blocked_checks": self.blocked_checks,
            "duration": round(self.duration_seconds, 3),
            "requirements": [r.to_dict() for r in self.requirements],
            "findings": self.findings,
            "timestamp": self.timestamp,
        }
