# core/repair/controller.py
"""
T1 Self-Repair Controller for HERMES 2.x.

Core Invariants:
1. BOUNDED RECOVERY: Caps attempts strictly to 2-3 attempts per check.
2. IMMEDIATE STALL DETECTION: Identical failure fingerprint on consecutive attempts triggers immediate stall & escalation.
3. CONTEXT-EFFICIENT GUIDANCE: Injects minimal, actionable diagnostic observations into T1 context without prompt bloat.
4. CANONICAL ESCALATION: Publishes REPAIR_STALLED and ESCALATION_REQUESTED when self-repair bounds are exceeded.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.event_bus import EventBus
from core.repair.models import RepairAttempt, RepairBudget, RepairFingerprint
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import FailureClass, RepairStatus

logger = logging.getLogger("hermes.repair.controller")


class RepairController:
    """
    Coordinates bounded T1 self-repair, stall detection, and escalation triggers.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        mission_id: str = "default",
        max_attempts_per_check: int = 3,
        max_total_repairs: int = 10,
    ):
        self.event_bus = event_bus
        self.mission_id = mission_id
        self.budget = RepairBudget(
            max_attempts_per_check=max_attempts_per_check,
            max_total_repairs=max_total_repairs,
        )
        self._attempts_by_check: Dict[str, List[RepairAttempt]] = {}
        self._last_fingerprint_by_check: Dict[str, str] = {}
        self._consecutive_fingerprint_counts: Dict[str, int] = {}

    def classify_failure(self, error_message: str, exit_code: Optional[int] = None) -> FailureClass:
        """
        Deterministically classify an error message or exit code into FailureClass.
        """
        msg = error_message.lower()

        if "syntaxerror" in msg:
            return FailureClass.SYNTAX_ERROR
        if "typeerror" in msg or "attributeerror" in msg:
            return FailureClass.TYPE_ERROR
        if "assertionerror" in msg or "assertion failed" in msg:
            return FailureClass.ASSERTION_FAILED
        if "filenotfounderror" in msg or "no such file" in msg:
            return FailureClass.FILE_CORRUPTED
        if "modulenotfounderror" in msg or "importerror" in msg:
            return FailureClass.MISSING_DEPENDENCY
        if "timeout" in msg:
            return FailureClass.TIMEOUT
        if "permission denied" in msg or "access denied" in msg:
            return FailureClass.PERMISSION_VIOLATION
        if "schema" in msg or "json" in msg and "decode" in msg:
            return FailureClass.SCHEMA_VIOLATION
        if exit_code is not None and exit_code != 0:
            return FailureClass.TEST_FAILED

        return FailureClass.TOOL_EXECUTION_ERROR

    def handle_failure(
        self,
        check_id: str,
        failure_class: FailureClass,
        error_message: str,
        target_path: Optional[str] = None,
        exit_code: Optional[int] = None,
        requirement_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Handle a verification or execution failure.
        Returns:
            (can_retry: bool, reason_or_guidance: str, repair_id: Optional[str])
        """
        fp = RepairFingerprint(
            failure_class=failure_class,
            target_path=target_path,
            error_summary=error_message[:120],
            exit_code=exit_code,
        )
        fp_hash = fp.compute_hash()

        last_fp = self._last_fingerprint_by_check.get(check_id)
        if last_fp == fp_hash:
            streak = self._consecutive_fingerprint_counts.get(check_id, 1) + 1
        else:
            streak = 1

        self._consecutive_fingerprint_counts[check_id] = streak
        self._last_fingerprint_by_check[check_id] = fp_hash

        history = self._attempts_by_check.get(check_id, [])
        attempt_num = len(history) + 1
        repair_id = f"repair_{check_id}_{attempt_num}"

        # 1. Check for stall (identical error twice in a row)
        if streak >= 2:
            self._publish_stalled_event(check_id, requirement_id, task_id, repair_id, "IDENTICAL_FAILURE_RECURRENCE")
            return (
                False,
                f"STALL DETECTED: Failure recurred identically ({failure_class.value}). Self-repair halted.",
                repair_id,
            )

        # 2. Check repair budget
        if attempt_num > self.budget.max_attempts_per_check:
            self._publish_stalled_event(check_id, requirement_id, task_id, repair_id, "MAX_ATTEMPTS_EXCEEDED")
            return (
                False,
                f"BUDGET EXCEEDED: Reached max repair attempts ({self.budget.max_attempts_per_check}) for check {check_id}.",
                repair_id,
            )

        if not self.budget.can_attempt():
            self._publish_stalled_event(check_id, requirement_id, task_id, repair_id, "TOTAL_REPAIR_BUDGET_EXHAUSTED")
            return (
                False,
                "BUDGET EXCEEDED: Global repair budget exhausted.",
                repair_id,
            )

        # Record attempt
        self.budget.record_attempt()
        attempt = RepairAttempt(
            attempt_id=f"att_{uuid.uuid4().hex[:6]}",
            repair_id=repair_id,
            check_id=check_id,
            requirement_id=requirement_id,
            attempt_number=attempt_num,
            failure_class=failure_class,
            fingerprint=fp_hash,
            status=RepairStatus.IN_PROGRESS,
        )
        if check_id not in self._attempts_by_check:
            self._attempts_by_check[check_id] = []
        self._attempts_by_check[check_id].append(attempt)

        # Publish canonical event
        self._publish_attempt_event(attempt, task_id=task_id)

        # Generate structured guidance
        guidance = self.generate_t1_repair_observation(
            check_id=check_id,
            attempt_number=attempt_num,
            max_attempts=self.budget.max_attempts_per_check,
            failure_class=failure_class,
            error_message=error_message,
            target_path=target_path,
        )

        return (True, guidance, repair_id)

    def record_success(self, check_id: str) -> None:
        """Record successful repair and clear check-specific failure streaks."""
        self._last_fingerprint_by_check.pop(check_id, None)
        self._consecutive_fingerprint_counts.pop(check_id, None)
        history = self._attempts_by_check.get(check_id, [])
        if history:
            history[-1].status = RepairStatus.SUCCEEDED

    def generate_t1_repair_observation(
        self,
        check_id: str,
        attempt_number: int,
        max_attempts: int,
        failure_class: FailureClass,
        error_message: str,
        target_path: Optional[str] = None,
    ) -> str:
        """
        Generate concise, high-signal observation for T1 prompt context.
        """
        lines = [
            f"[HERMES SELF-REPAIR ATTEMPT {attempt_number}/{max_attempts}]",
            f"Check: {check_id}",
            f"Failure Class: {failure_class.value}",
        ]
        if target_path:
            lines.append(f"Target: {target_path}")
        lines.append(f"Error: {error_message}")
        lines.append("Directive: Inspect the specific root cause and apply a minimal, surgical fix. Do not repeat failed actions.")
        return "\n".join(lines)

    def _publish_attempt_event(self, attempt: RepairAttempt, task_id: Optional[str] = None) -> None:
        if not self.event_bus:
            return
        event = HermesEvent(
            event_type=EventType.REPAIR_ATTEMPTED,
            mission_id=self.mission_id,
            task_id=task_id,
            requirement_id=attempt.requirement_id,
            acceptance_check_id=attempt.check_id,
            repair_id=attempt.repair_id,
            payload=attempt.to_dict(),
        )
        self.event_bus.publish(event)

    def _publish_stalled_event(
        self,
        check_id: str,
        requirement_id: Optional[str],
        task_id: Optional[str],
        repair_id: str,
        reason: str,
    ) -> None:
        if not self.event_bus:
            return
        event = HermesEvent(
            event_type=EventType.REPAIR_STALLED,
            mission_id=self.mission_id,
            task_id=task_id,
            requirement_id=requirement_id,
            acceptance_check_id=check_id,
            repair_id=repair_id,
            payload={
                "check_id": check_id,
                "requirement_id": requirement_id,
                "repair_id": repair_id,
                "reason": reason,
            },
        )
        self.event_bus.publish(event)
