# core/escalation/engine.py
"""
Selective Escalation Engine for HERMES 2.x.

Core Invariants:
1. SELECTIVE ESCALATION: Routine low-risk changes with passing checks strictly bypass escalation.
2. DISAGREEMENT RESOLUTION: Directs unresolved T1/T2 friction to T3 Judge.
3. CONSTITUTIONAL FACT INVARIANT: T3 Judge is strictly prevented from validating failed physical evidence.
4. CANONICAL AUDIT LOG: All escalation stages emit canonical events to the EventBus.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.event_bus import EventBus
from core.escalation.critic import T2Critic
from core.escalation.judge import T3Judge
from core.escalation.models import EscalationBudget, T2CriticResult, T3JudgeResult
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import EscalationDecisionType
from core.verification.models import VerificationResult, VerificationVerdict
from core.verification.policy import VerificationPolicy, VerificationRiskLevel

logger = logging.getLogger("hermes.escalation.engine")


class EscalationEngine:
    """
    Orchestrates selective evaluation through T2 Critic and T3 Judge.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        mission_id: str = "default",
        t2_evaluator_fn: Optional[Callable[[str], str]] = None,
        t3_arbiter_fn: Optional[Callable[[str], str]] = None,
        max_t2_evaluations: int = 10,
        max_t3_arbitrations: int = 5,
    ):
        self.event_bus = event_bus
        self.mission_id = mission_id
        self.critic = T2Critic(evaluator_fn=t2_evaluator_fn)
        self.judge = T3Judge(arbiter_fn=t3_arbiter_fn)
        self.budget = EscalationBudget(
            max_t2_evaluations=max_t2_evaluations,
            max_t3_arbitrations=max_t3_arbitrations,
        )

    def evaluate_verification(
        self,
        requirement_id: Optional[str],
        check_id: Optional[str],
        verification_results: List[VerificationResult],
        files_modified: Optional[List[str]] = None,
        lines_changed: int = 0,
        code_diff: Optional[str] = None,
        goal_summary: str = "",
        requirement_desc: str = "",
        force_escalation: bool = False,
        task_id: Optional[str] = None,
        failure_count: int = 0,
        t1_repair_exhausted: bool = False,
        waiver_authorized: bool = False,
        is_critical_requirement: bool = True,
    ) -> Tuple[bool, Optional[T2CriticResult], Optional[T3JudgeResult]]:
        """
        Evaluate whether verification outcome requires escalation.
        Returns:
            (approved: bool, t2_result: Optional[T2CriticResult], t3_result: Optional[T3JudgeResult])
        """
        escalation_id = f"esc_{uuid.uuid4().hex[:8]}"
        all_passed = all(vr.verdict == VerificationVerdict.PASS for vr in verification_results)

        # 1. Check Risk Profile
        actual_failures = failure_count if failure_count > 0 else (0 if all_passed else 1)
        risk_level = VerificationPolicy.assess_risk(
            files_modified=files_modified,
            lines_changed=lines_changed,
            failure_count=actual_failures,
        )

        # 2a. Check Low-Risk Passing Bypass
        if not force_escalation and VerificationPolicy.should_bypass_t2_t3(risk_level, all_passed):
            if self.event_bus:
                event = HermesEvent(
                    event_type=EventType.ESCALATION_SKIPPED,
                    mission_id=self.mission_id,
                    task_id=task_id,
                    requirement_id=requirement_id,
                    acceptance_check_id=check_id,
                    escalation_id=escalation_id,
                    payload={
                        "reason": "LOW_RISK_BYPASS",
                        "risk_level": risk_level.value,
                        "checks_passed": len(verification_results),
                    },
                )
                self.event_bus.publish(event)
            return (True, None, None)

        # 2b. Ordinary deterministic failures route to T1 repair before T2 unless high risk or T1 exhausted
        if not all_passed and not force_escalation and not t1_repair_exhausted and risk_level not in (VerificationRiskLevel.HIGH, VerificationRiskLevel.CRITICAL):
            if self.event_bus:
                event = HermesEvent(
                    event_type=EventType.ESCALATION_SKIPPED,
                    mission_id=self.mission_id,
                    task_id=task_id,
                    requirement_id=requirement_id,
                    acceptance_check_id=check_id,
                    escalation_id=escalation_id,
                    payload={
                        "reason": "ROUTED_TO_T1_REPAIR",
                        "risk_level": risk_level.value,
                        "all_passed": False,
                    },
                )
                self.event_bus.publish(event)
            return (False, None, None)

        # 3. Escalate to T2 Critic
        if not self.budget.can_call_t2():
            logger.warning("Escalation budget for T2 exhausted.")
            return (all_passed, None, None)

        self.budget.record_t2()
        self._publish_event(EventType.T2_REQUESTED, escalation_id, requirement_id, check_id, task_id)
        self._publish_event(EventType.T2_STARTED, escalation_id, requirement_id, check_id, task_id)

        packet = self.critic.build_packet(
            goal_summary=goal_summary,
            requirement_desc=requirement_desc,
            verification_results=verification_results,
            code_diff=code_diff,
        )

        t2_res = self.critic.evaluate(requirement_id, check_id, packet)
        self._publish_event(
            EventType.T2_COMPLETED,
            escalation_id,
            requirement_id,
            check_id,
            task_id,
            payload=t2_res.to_dict(),
        )

        # If T2 approved, we are done
        if t2_res.approved:
            return (True, t2_res, None)

        # 4. If T2 rejects and this is high risk or disputed, escalate to T3 Judge
        if not self.budget.can_call_t3():
            logger.warning("Escalation budget for T3 exhausted.")
            return (False, t2_res, None)

        self.budget.record_t3()
        self._publish_event(EventType.T3_REQUESTED, escalation_id, requirement_id, check_id, task_id)
        self._publish_event(EventType.T3_STARTED, escalation_id, requirement_id, check_id, task_id)

        t3_res = self.judge.arbitrate(
            requirement_id=requirement_id,
            check_id=check_id,
            dispute_summary=f"T2 Critic rejected verification: {t2_res.critique}",
            verification_results=verification_results,
            t2_critique=t2_res.critique,
            is_critical_requirement=is_critical_requirement,
            waiver_authorized=waiver_authorized,
        )

        self._publish_event(
            EventType.T3_COMPLETED,
            escalation_id,
            requirement_id,
            check_id,
            task_id,
            payload=t3_res.to_dict(),
        )

        final_approved = (t3_res.decision == EscalationDecisionType.APPROVE)
        return (final_approved, t2_res, t3_res)

    def _publish_event(
        self,
        event_type: EventType,
        escalation_id: str,
        requirement_id: Optional[str],
        check_id: Optional[str],
        task_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.event_bus:
            return
        event = HermesEvent(
            event_type=event_type,
            mission_id=self.mission_id,
            task_id=task_id,
            requirement_id=requirement_id,
            acceptance_check_id=check_id,
            escalation_id=escalation_id,
            payload=payload or {},
        )
        self.event_bus.publish(event)
