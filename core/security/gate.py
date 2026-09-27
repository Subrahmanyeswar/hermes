# core/security/gate.py
"""
HERMES 2.x - Single Canonical Security Gate (Prompt 13)
The sole authoritative security gateway between agent intent and tool execution:
  AgentLoop -> ActionExecutor -> SecurityGate -> ToolExecutor
No tool execution, subagent spawn, or handoff ingestion can bypass this gate.
"""

from __future__ import annotations

import logging
import uuid
import time
from typing import Any, Dict, Optional, Tuple, List, Callable

from core.security.approvals import ApprovalStore
from core.security.audit import SecurityAuditLogger
from core.security.classifier import ActionClassifier
from core.security.config import SecurityPolicy, get_default_security_policy
from core.security.content_boundary import ContentBoundary
from core.security.denial import DenialTracker
from core.security.enums import (
    ApprovalScope,
    ContentTrust,
    DenialReasonCode,
    PermissionOutcome,
    RiskLevel,
)
from core.security.handoff_security import HandoffSecurityChecker
from core.security.models import (
    ActionDescriptor,
    ApprovalGrant,
    ApprovalRequest,
    HandoffSecurityAssessment,
    PermissionDecision,
    PromptInjectionAssessment,
    RiskAssessment,
    SecurityExecutionResult,
    SubagentSecurityContext,
    UserIntent,
)
from core.security.policy import PolicyEngine
from core.security.risk import RiskEngine
from core.security.subagent_security import SubagentSecurityGovernor

logger = logging.getLogger("hermes.security.gate")


class SecurityGate:
    """
    Unified security gate enforcing all Prompt 13 policies, classifications,
    approvals, injection screening, subagent ceilings, and audit logging.
    """

    def __init__(
        self,
        policy: Optional[SecurityPolicy] = None,
        approval_store: Optional[ApprovalStore] = None,
        audit_logger: Optional[SecurityAuditLogger] = None,
        content_boundary: Optional[ContentBoundary] = None,
        denial_tracker: Optional[DenialTracker] = None,
        event_emitter: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.policy = policy or get_default_security_policy()
        self.approval_store = approval_store or ApprovalStore(self.policy.approval_cache_ttl_seconds)
        self.audit_logger = audit_logger or SecurityAuditLogger()
        self.content_boundary = content_boundary or ContentBoundary()
        self.denial_tracker = denial_tracker or DenialTracker(self.policy.max_consecutive_denials)
        self.event_emitter = event_emitter

        # Core subcomponents
        self.risk_engine = RiskEngine(self.policy)
        self.classifier = ActionClassifier(self.risk_engine, self.policy)
        self.policy_engine = PolicyEngine(self.policy)
        self.subagent_governor = SubagentSecurityGovernor(self.policy)
        self.handoff_checker = HandoffSecurityChecker(self.content_boundary)

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Helper to emit events if callback registered."""
        if self.event_emitter:
            try:
                self.event_emitter(event_type, payload)
            except Exception as e:
                logger.warning("Event emitter failed in SecurityGate: %s", e)

    def evaluate_action(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_intent: Optional[UserIntent] = None,
        session_id: Optional[str] = None,
        subagent_context: Optional[SubagentSecurityContext] = None,
        headless_mode: Optional[bool] = None,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Tuple[PermissionDecision, ActionDescriptor]:
        """
        Primary gate entrypoint for evaluating a proposed tool action.
        Returns (PermissionDecision, ActionDescriptor).
        """
        is_headless = headless_mode if headless_mode is not None else self.policy.headless_mode

        # 1. Build canonical ActionDescriptor
        action = self.classifier.build_descriptor(
            tool_name=tool_name,
            arguments=arguments,
            is_subagent=(subagent_context is not None),
            agent_id=subagent_context.agent_id if subagent_context else None,
            task_id=task_id,
        )

        # 2. Check Subagent Security Ceiling if action proposed by a subagent
        if subagent_context:
            subagent_ok, subagent_denial = self.subagent_governor.check_child_action(
                subagent_context, action
            )
            if not subagent_ok:
                decision = PermissionDecision(
                    outcome=PermissionOutcome.DENY,
                    reason=f"Subagent ceiling violated: {subagent_denial}",
                    reason_code=DenialReasonCode.SUBAGENT_CEILING_VIOLATION,
                    required_scope=ApprovalScope.EXACT_ACTION,
                    suggested_alternative="Request parent agent or run with authorized tool set.",
                )
                self._record_and_audit(action, decision, session_id, subagent_context)
                self._emit("SUBAGENT_PERMISSION_CEILING_ENFORCED", {
                    "tool_name": tool_name,
                    "agent_id": subagent_context.agent_id,
                    "reason": subagent_denial,
                })
                return decision, action

        # 3. Classify Action & Assess Risk (14 dimensions)
        action, risk = self.classifier.classify_action(action, user_intent)
        self._emit("SECURITY_RISK_ASSESSED", {
            "tool_name": tool_name,
            "risk_level": risk.level.value,
            "risk_score": risk.score,
            "dimensions": [d.value for d in risk.dimensions],
            "fingerprint": action.action_fingerprint,
        })

        # 4. Check for active approval grant
        matching_grant = self.approval_store.find_matching_grant(action, session_id)

        # 5. Evaluate Permission Policy
        decision = self.policy_engine.evaluate(
            action=action,
            assessment=risk,
            matching_grant=matching_grant,
            user_intent=user_intent,
            headless_mode=is_headless,
        )

        # 6. If denied, check for safe alternatives
        if decision.outcome == PermissionOutcome.DENY and not decision.suggested_alternative:
            decision.suggested_alternative = self.denial_tracker.suggest_alternative(action)

        # 7. Record decision in denial tracker & check loop
        loop_detected, escalation_msg = self.denial_tracker.record_decision(decision)
        if loop_detected:
            self._emit("SECURITY_ESCALATION", {
                "reason": escalation_msg,
                "consecutive_denials": self.denial_tracker.consecutive_denials,
                "last_action": action.tool_name,
            })

        # 8. Record and audit decision
        self._record_and_audit(action, decision, session_id, subagent_context)

        # 9. Emit canonical decision events
        self._emit("PERMISSION_EVALUATED", {
            "tool_name": tool_name,
            "outcome": decision.outcome.value,
            "reason_code": decision.reason_code.value,
            "fingerprint": action.action_fingerprint,
        })

        if decision.outcome == PermissionOutcome.ASK:
            # Create a pending approval request
            req = ApprovalRequest(
                request_id=f"req_{uuid.uuid4().hex[:10]}",
                action=action,
                assessment=risk,
                required_scope=decision.required_scope,
                session_id=session_id,
                created_at=time.time(),
            )
            self.approval_store.add_request(req)
            self._emit("PERMISSION_ASKED", {
                "request_id": req.request_id,
                "tool_name": tool_name,
                "scope": decision.required_scope.value,
                "risk_level": risk.level.value,
            })
        elif decision.outcome == PermissionOutcome.ALLOW:
            if matching_grant:
                matching_grant.consume()
                self._emit("PERMISSION_GRANTED", {
                    "grant_id": matching_grant.grant_id,
                    "tool_name": tool_name,
                    "remaining_uses": matching_grant.remaining_uses,
                })

        return decision, action

    def _record_and_audit(
        self,
        action: ActionDescriptor,
        decision: PermissionDecision,
        session_id: Optional[str] = None,
        subagent_context: Optional[SubagentSecurityContext] = None,
    ) -> None:
        """Internal helper to record audit entry."""
        self.audit_logger.log_record(
            event_name=f"PERMISSION_{decision.outcome.value}",
            details={
                "tool_name": action.tool_name,
                "fingerprint": action.action_fingerprint,
                "arguments": action.arguments,
                "canonical_path": action.canonical_path,
                "outcome": decision.outcome.value,
                "reason_code": decision.reason_code.value,
                "reason": decision.reason,
                "risk_level": action.risk_assessment.level.value if action.risk_assessment else "UNKNOWN",
                "risk_score": action.risk_assessment.score if action.risk_assessment else 0.0,
            },
            session_id=session_id,
            agent_id=subagent_context.agent_id if subagent_context else None,
        )

    def screen_observation(
        self,
        raw_output: str,
        trust_level: ContentTrust = ContentTrust.UNTRUSTED_EXTERNAL,
        source_id: Optional[str] = None,
    ) -> Tuple[str, PromptInjectionAssessment]:
        """
        Screen tool output before feeding into agent context.
        Returns (sanitized_view, assessment).
        """
        sanitized, assessment = self.content_boundary.process_observation(
            raw_output=raw_output,
            trust_level=trust_level,
            source_id=source_id,
        )

        if assessment.status != PromptInjectionStatus.SAFE:
            self._emit("PROMPT_INJECTION_DETECTED", {
                "source_id": source_id,
                "status": assessment.status.value,
                "family": assessment.attack_family.value if assessment.attack_family else None,
                "confidence": assessment.confidence,
                "indicators": assessment.indicators,
            })
            self._emit("CONTENT_SANITIZED", {
                "source_id": source_id,
                "indicators_count": len(assessment.indicators),
            })
            self.audit_logger.log_record(
                event_name="PROMPT_INJECTION_FLAGGED",
                details={
                    "source_id": source_id,
                    "confidence": assessment.confidence,
                    "family": assessment.attack_family.value if assessment.attack_family else "UNKNOWN",
                    "reason": assessment.reason,
                },
            )

        return sanitized, assessment

    def authorize_subagent_delegation(
        self,
        parent_context: SubagentSecurityContext,
        requested_tools: List[str],
    ) -> Tuple[bool, Optional[str], SubagentSecurityContext]:
        """Check outbound delegation authorization and compute child security ceiling."""
        return self.subagent_governor.authorize_delegation(parent_context, requested_tools)

    def inspect_subagent_handoff(
        self,
        child_context: SubagentSecurityContext,
        return_payload: str,
        artifacts_produced: Optional[List[str]] = None,
    ) -> HandoffSecurityAssessment:
        """Screen child return handoff for prompt injection and leaks."""
        assessment = self.handoff_checker.inspect_handoff(
            child_context=child_context,
            return_payload=return_payload,
            artifacts_produced=artifacts_produced,
        )

        if not assessment.safe_to_ingest:
            self._emit("HANDOFF_SECURITY_VIOLATION", {
                "subagent_id": child_context.agent_id,
                "violations": assessment.violations,
            })
            self.audit_logger.log_record(
                event_name="HANDOFF_SECURITY_VIOLATION",
                details={
                    "subagent_id": child_context.agent_id,
                    "violations": assessment.violations,
                },
            )

        return assessment
