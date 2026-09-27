# core/repair/models.py
"""
T1 Self-Repair Models & Fingerprints for HERMES 2.x.

Core Invariants:
1. BOUNDED REPAIR: Self-repair attempts per check/failure are strictly capped (default 2-3) to prevent endless retry loops.
2. STALL DETECTION: Identical failure fingerprints on consecutive attempts trigger immediate stall detection.
3. CAUSAL ACCOUNTABILITY: Every repair attempt carries the exact failure classification, previous attempt IDs, and resulting state.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.runtime_state.models import FailureClass, RepairStatus


@dataclass
class RepairFingerprint:
    """
    Cryptographic signature of a failure mode to detect non-progress and infinite loops.
    """
    failure_class: FailureClass
    target_path: Optional[str] = None
    error_summary: str = ""
    exit_code: Optional[int] = None

    def compute_hash(self) -> str:
        s = f"{self.failure_class.value}:{self.target_path or ''}:{self.error_summary}:{self.exit_code}"
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


@dataclass
class RepairBudget:
    """Limits on automated repair attempts."""
    max_attempts_per_check: int = 3
    max_total_repairs: int = 10
    current_attempts: int = 0
    total_repairs: int = 0

    def can_attempt(self) -> bool:
        return (
            self.current_attempts < self.max_attempts_per_check
            and self.total_repairs < self.max_total_repairs
        )

    def record_attempt(self) -> None:
        self.current_attempts += 1
        self.total_repairs += 1

    def reset_check(self) -> None:
        self.current_attempts = 0


@dataclass
class RepairAttempt:
    """Record of a single self-repair execution."""
    attempt_id: str
    repair_id: str
    check_id: str
    requirement_id: Optional[str] = None
    attempt_number: int = 1
    failure_class: FailureClass = FailureClass.OTHER
    fingerprint: str = ""
    proposed_remedy: str = ""
    status: RepairStatus = RepairStatus.IN_PROGRESS
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "repair_id": self.repair_id,
            "check_id": self.check_id,
            "requirement_id": self.requirement_id,
            "attempt_number": self.attempt_number,
            "failure_class": self.failure_class.value,
            "fingerprint": self.fingerprint,
            "proposed_remedy": self.proposed_remedy,
            "status": self.status.value,
            "timestamp": self.timestamp,
        }
