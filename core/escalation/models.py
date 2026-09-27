# core/escalation/models.py
"""
Selective Escalation Models for HERMES 2.x (T2 Critic & T3 Judge).

Core Invariants:
1. FACT OVERRIDE PROHIBITION: Neither T2 nor T3 may override failed objective facts (compiler errors, failing tests, missing files).
2. WORKSPACE CONFINEMENT: Neither T2 nor T3 may directly mutate workspace files. They evaluate and judge only.
3. BOUNDED EVALUATION PACKETS: Packet sent to T2/T3 is strictly minimized to prevent context explosion.
4. BOUNDED ESCALATION BUDGET: Capped number of T2/T3 invocations per mission.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.runtime_state.models import DisagreementClass, EscalationDecisionType, FailureClass


@dataclass
class EscalationBudget:
    """Limits on T2 Critic and T3 Judge invocations."""
    max_t2_evaluations: int = 10
    max_t3_arbitrations: int = 5
    current_t2: int = 0
    current_t3: int = 0

    def can_call_t2(self) -> bool:
        return self.current_t2 < self.max_t2_evaluations

    def can_call_t3(self) -> bool:
        return self.current_t3 < self.max_t3_arbitrations

    def record_t2(self) -> None:
        self.current_t2 += 1

    def record_t3(self) -> None:
        self.current_t3 += 1


@dataclass
class T2CriticResult:
    """The structured evaluation outcome from T2 Critic."""
    evaluation_id: str
    requirement_id: Optional[str] = None
    check_id: Optional[str] = None
    approved: bool = False
    confidence: float = 0.0
    critique: str = ""
    identified_risks: List[str] = field(default_factory=list)
    failure_class: Optional[FailureClass] = None
    suggested_action: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "requirement_id": self.requirement_id,
            "check_id": self.check_id,
            "approved": self.approved,
            "confidence": self.confidence,
            "critique": self.critique,
            "identified_risks": self.identified_risks,
            "failure_class": self.failure_class.value if self.failure_class else None,
            "suggested_action": self.suggested_action,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
        }


@dataclass
class T3JudgeResult:
    """The binding judgment outcome from T3 Judge."""
    judgment_id: str
    requirement_id: Optional[str] = None
    decision: EscalationDecisionType = EscalationDecisionType.REJECT
    rationale: str = ""
    binding_directives: List[str] = field(default_factory=list)
    fact_invariant_checked: bool = True
    disagreement_class: Optional[DisagreementClass] = None
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "judgment_id": self.judgment_id,
            "requirement_id": self.requirement_id,
            "decision": self.decision.value,
            "rationale": self.rationale,
            "binding_directives": self.binding_directives,
            "fact_invariant_checked": self.fact_invariant_checked,
            "disagreement_class": self.disagreement_class.value if self.disagreement_class else None,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
        }
