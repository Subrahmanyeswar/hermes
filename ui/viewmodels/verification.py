# ui/viewmodels/verification.py
"""Verification and Acceptance Ledger ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class AcceptanceCheckViewModel:
    check_id: str
    requirement_id: str
    description: str
    status: str            # NOT_RUN, RUNNING, PASS, FAIL, BLOCKED
    critical: bool = True
    error_message: Optional[str] = None
    last_run_str: str = "N/A"


@dataclass(frozen=True)
class VerificationViewModel:
    status: str = "IDLE"   # IDLE, RUNNING, PASSED, FAILED, INCONCLUSIVE, BLOCKED
    checks: Tuple[AcceptanceCheckViewModel, ...] = ()
    passing_checks: int = 0
    total_checks: int = 0
    critical_failed: int = 0
    confidence_str: str = "N/A"
    issues: Tuple[str, ...] = ()
    repair_required: bool = False
