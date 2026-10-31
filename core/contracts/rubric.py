# core/contracts/rubric.py
"""
Quality Rubric Contract for HERMES Phase 11.
Specifies task-scaled hard requirements, advisory quality dimensions,
anti-placeholder rules, and verification evidence criteria.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class RubricRequirement:
    """A hard requirement that must pass for project release."""
    req_id: str
    title: str
    description: str
    rule_type: str = "static_check"              # "static_check", "runtime_check", "behavioral", "accessibility"
    is_mandatory: bool = True
    passed: bool = False
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QualityDimension:
    """An advisory quality dimension scored across the project."""
    dimension_name: str                          # e.g. "visual_depth", "responsive_layout", "interactivity", "code_depth"
    weight: float = 1.0
    score: float = 0.0                           # 0.0 to 1.0
    threshold: float = 0.7
    criteria: List[str] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)
    passed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QualityRubric:
    """
    Authoritative specification of quality and completeness criteria.
    Appropriately scaled to the task complexity profile.
    """
    schema_version: str = "1.0.0"
    rubric_id: str = field(default_factory=lambda: f"rbc_{uuid.uuid4().hex[:8]}")
    mission_id: str = ""
    task_type: str = "vanilla_web"
    complexity_profile: str = "SIMPLE"
    hard_requirements: List[RubricRequirement] = field(default_factory=list)
    quality_dimensions: Dict[str, QualityDimension] = field(default_factory=dict)
    anti_placeholder_rules: List[str] = field(default_factory=lambda: [
        "no_todo_comments",
        "no_lorem_ipsum",
        "no_empty_event_listeners",
        "no_empty_containers",
        "no_one_line_stubs",
    ])
    expected_loc_bounds: Dict[str, Dict[str, int]] = field(default_factory=dict)
    evaluation_verdict: str = "PENDING"          # "PENDING", "PASS", "NEEDS_IMPROVEMENT", "FAIL"
    rubric_hash: str = ""

    def __post_init__(self):
        if not self.rubric_hash:
            self.rubric_hash = self.compute_hash()

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 hash of quality rubric."""
        d = self.to_dict()
        d.pop("rubric_hash", None)
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "rubric_id": self.rubric_id,
            "mission_id": self.mission_id,
            "task_type": self.task_type,
            "complexity_profile": self.complexity_profile,
            "hard_requirements": [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in self.hard_requirements],
            "quality_dimensions": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.quality_dimensions.items()},
            "anti_placeholder_rules": list(self.anti_placeholder_rules),
            "expected_loc_bounds": dict(self.expected_loc_bounds),
            "evaluation_verdict": self.evaluation_verdict,
            "rubric_hash": self.rubric_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> QualityRubric:
        if not data:
            return cls()
        hard_reqs = [
            RubricRequirement(**item) if isinstance(item, dict) else item
            for item in data.get("hard_requirements", [])
        ]
        quality_dims = {
            k: QualityDimension(**v) if isinstance(v, dict) else v
            for k, v in data.get("quality_dimensions", {}).items()
        }
        return cls(
            schema_version=data.get("schema_version", "1.0.0"),
            rubric_id=data.get("rubric_id", f"rbc_{uuid.uuid4().hex[:8]}"),
            mission_id=data.get("mission_id", ""),
            task_type=data.get("task_type", "vanilla_web"),
            complexity_profile=data.get("complexity_profile", "SIMPLE"),
            hard_requirements=hard_reqs,
            quality_dimensions=quality_dims,
            anti_placeholder_rules=data.get("anti_placeholder_rules", []),
            expected_loc_bounds=data.get("expected_loc_bounds", {}),
            evaluation_verdict=data.get("evaluation_verdict", "PENDING"),
            rubric_hash=data.get("rubric_hash", ""),
        )
