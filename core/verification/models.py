# core/verification/models.py
"""
Deterministic Verification Models for HERMES 2.x.

Core Invariants:
1. DETERMINISTIC VERIFICATION: Verifiers evaluate objective facts, not model claims.
2. VERDICT INTEGRITY:
   - PASS: All assertions satisfied by fresh, valid evidence.
   - FAIL: One or more assertions objectively violated.
   - INCONCLUSIVE: Evidence missing, corrupt, or insufficient to reach determination.
   - BLOCKED: Environment or dependency failure prevented evaluation.
3. CAUSAL REPRODUCIBILITY: Every verification result includes the exact evidence IDs and fingerprints used.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.runtime_state.models import FailureClass


class VerificationVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"


class CheckType(str, Enum):
    FILESYSTEM = "FILESYSTEM"
    PYTHON_AST = "PYTHON_AST"
    JSON_SCHEMA = "JSON_SCHEMA"
    TEST_RESULT = "TEST_RESULT"
    GIT_STATUS = "GIT_STATUS"
    COMPOSITE = "COMPOSITE"
    COMMAND_EXIT = "COMMAND_EXIT"
    CUSTOM = "CUSTOM"


@dataclass
class VerificationResult:
    """The authoritative outcome of evaluating an acceptance check against evidence."""
    check_id: str
    requirement_id: Optional[str] = None
    verdict: VerificationVerdict = VerificationVerdict.INCONCLUSIVE
    failure_class: Optional[FailureClass] = None
    message: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    fingerprint: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.verdict == VerificationVerdict.PASS

    @property
    def failed(self) -> bool:
        return self.verdict == VerificationVerdict.FAIL

    @property
    def repair_required(self) -> bool:
        return self.verdict == VerificationVerdict.FAIL

    @property
    def evidence_required(self) -> bool:
        return self.verdict == VerificationVerdict.INCONCLUSIVE

    @property
    def escalation_required(self) -> bool:
        return self.verdict == VerificationVerdict.BLOCKED

    @property
    def blocked(self) -> bool:
        return self.verdict == VerificationVerdict.BLOCKED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "requirement_id": self.requirement_id,
            "verdict": self.verdict.value,
            "failure_class": self.failure_class.value if self.failure_class else None,
            "message": self.message,
            "evidence_ids": list(self.evidence_ids),
            "details": self.details,
            "fingerprint": self.fingerprint,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "passed": self.passed,
            "repair_required": self.repair_required,
            "evidence_required": self.evidence_required,
            "escalation_required": self.escalation_required,
            "blocked": self.blocked,
        }
