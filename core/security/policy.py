# core/security/policy.py
"""
Deterministic Permission Policy Engine for HERMES 2.x.
Enforces strict precedence:
1. Hard Security Deny (Critical risk / self-modification) -> DENY
2. User Intent Prohibitions -> DENY
3. Explicit Tool/Path Blocklist -> DENY
4. Active User Approval Grant -> ALLOW
5. Safe Deterministic Operations -> ALLOW
6. Low-Risk Workspace Operations -> ALLOW
7. Medium / High Risk Operations -> ASK
8. Unknown / Ambiguous Operations -> Fail-Closed (ASK or DENY)
"""

from __future__ import annotations

from typing import List, Optional

from core.security.action_fingerprint import compute_action_fingerprint
from core.security.approvals import ApprovalStore
from core.security.config import SecurityPolicy
from core.security.enums import (
    ApprovalScope,
    DenialReasonCode,
    HeadlessBehavior,
    PermissionOutcome,
    RiskDimension,
    RiskLevel,
)
from core.security.models import (
    ActionDescriptor,
    PermissionDecision,
    RiskAssessment,
    SecurityContext,
)


class PolicyEngine:
    """
    Authoritative Policy Engine determining ALLOW, DENY, or ASK.
    """

    def __init__(self, policy: Optional[SecurityPolicy] = None):
        self.policy = policy or SecurityPolicy()

    def evaluate(
        self,
        action: ActionDescriptor,
        risk: Optional[RiskAssessment] = None,
        context: Optional[SecurityContext] = None,
        approval_store: Optional[ApprovalStore] = None,
        assessment: Optional[RiskAssessment] = None,
        matching_grant: Optional[ApprovalGrant] = None,
        user_intent: Optional[UserIntent] = None,
        headless_mode: Optional[bool] = None,
    ) -> PermissionDecision:
        """
        Evaluate proposed action against authoritative policy precedence.
        """
        effective_risk = risk or assessment or action.risk_assessment or RiskAssessment(risk_level=RiskLevel.SAFE)
        is_headless = headless_mode if headless_mode is not None else (context.is_headless if context else self.policy.headless_mode)
        u_intent = user_intent or (context.user_intent if context else None)
        sub_ctx = context.subagent_context if context else None
        session_id = context.session_id if context else getattr(action, "session_id", None)

        fingerprint = compute_action_fingerprint(
            action,
            policy_version=self.policy.policy_version,
            workspace_root=self.policy.workspace_root,
        )

        # ── 1. Hard Security Deny (CRITICAL Risk) ────────────────────────────
        # Critical operations (security tampering, outside-workspace destruction, credential access)
        # can NEVER be authorized by normal user grants or model classifiers.
        if effective_risk.risk_level == RiskLevel.CRITICAL:
            reason = "; ".join(effective_risk.reasons) or "Critical risk action is hard-denied."
            reason_code = DenialReasonCode.HARD_SECURITY_DENY
            if RiskDimension.SECURITY_CONTROL_CHANGE in effective_risk.dimensions or RiskDimension.SECURITY_TAMPERING in effective_risk.dimensions:
                reason_code = DenialReasonCode.SECURITY_POLICY_MODIFICATION
            elif RiskDimension.CREDENTIALS in effective_risk.dimensions or RiskDimension.CREDENTIAL in effective_risk.dimensions:
                reason_code = DenialReasonCode.CREDENTIAL_ACCESS
            elif RiskDimension.FILESYSTEM in effective_risk.dimensions or RiskDimension.FILESYSTEM_WRITE in effective_risk.dimensions:
                reason_code = DenialReasonCode.OUTSIDE_WORKSPACE

            return PermissionDecision(
                outcome=PermissionOutcome.DENY,
                reason_code=reason_code,
                reason=f"SECURITY HARD-DENY: {reason}",
                risk_assessment=effective_risk,
                fingerprint=fingerprint,
                allowed_alternatives=[
                    "Inspect code within workspace without modifying security modules.",
                    "Use isolated sandbox or mock resources.",
                ],
            )

        # ── 2. User Intent Prohibitions ──────────────────────────────────────
        prohibitions = u_intent.prohibitions if u_intent else []
        if prohibitions:
            for prohibited in prohibitions:
                p_lower = prohibited.lower()
                cmd = str(action.arguments.get("command", "") or action.arguments.get("cmd", "")).lower()
                op = (action.operation or "").lower()
                if p_lower in cmd or p_lower in op or (action.destructive and "delete" in p_lower):
                    return PermissionDecision(
                        outcome=PermissionOutcome.DENY,
                        reason_code=DenialReasonCode.USER_INTENT_PROHIBITED,
                        reason=f"Action violates explicit user prohibition: '{prohibited}'.",
                        risk_assessment=effective_risk,
                        fingerprint=fingerprint,
                        allowed_alternatives=["Perform non-destructive inspection."],
                    )
        # ── 3. Explicit Tool Blocklist ────────────────────────────────────────
        tool_name = (action.tool_name or "").lower().strip()
        if tool_name in [t.lower() for t in self.policy.denied_tools]:
            return PermissionDecision(
                outcome=PermissionOutcome.DENY,
                reason_code=DenialReasonCode.POLICY_VIOLATION,
                reason=f"Tool '{tool_name}' is explicitly denied by current security policy.",
                risk_assessment=effective_risk,
                fingerprint=fingerprint,
                allowed_alternatives=["Use permitted workspace tools."],
            )

        # ── 4. Subagent Permission Ceiling Check ─────────────────────────────
        if sub_ctx:
            if tool_name in [t.lower() for t in sub_ctx.denied_tools]:
                return PermissionDecision(
                    outcome=PermissionOutcome.DENY,
                    reason_code=DenialReasonCode.SUBAGENT_PERMISSION_ESCALATION,
                    reason=f"Tool '{tool_name}' prohibited by parent subagent ceiling.",
                    risk_assessment=effective_risk,
                    fingerprint=fingerprint,
                )
            if not sub_ctx.can_shell and RiskDimension.SHELL in effective_risk.dimensions:
                return PermissionDecision(
                    outcome=PermissionOutcome.DENY,
                    reason_code=DenialReasonCode.SUBAGENT_PERMISSION_ESCALATION,
                    reason="Subagent is prohibited from shell command execution.",
                    risk_assessment=effective_risk,
                    fingerprint=fingerprint,
                )
            if not sub_ctx.can_mutate and (action.destructive or action.operation in ("write", "edit", "delete")):
                return PermissionDecision(
                    outcome=PermissionOutcome.DENY,
                    reason_code=DenialReasonCode.SUBAGENT_PERMISSION_ESCALATION,
                    reason="Subagent is read-only and cannot mutate filesystem.",
                    risk_assessment=effective_risk,
                    fingerprint=fingerprint,
                )
            if not sub_ctx.can_network and RiskDimension.NETWORK in effective_risk.dimensions:
                return PermissionDecision(
                    outcome=PermissionOutcome.DENY,
                    reason_code=DenialReasonCode.SUBAGENT_PERMISSION_ESCALATION,
                    reason="Subagent is prohibited from external network connections.",
                    risk_assessment=effective_risk,
                    fingerprint=fingerprint,
                )

        # ── 5. Active User Approval Grant Match ───────────────────────────────
        grant_to_use = matching_grant
        if not grant_to_use and approval_store:
            if hasattr(approval_store, "find_matching_grant"):
                grant_to_use = approval_store.find_matching_grant(action=action, session_id=session_id)
            elif hasattr(approval_store, "find_valid_grant"):
                grant_to_use = approval_store.find_valid_grant(
                    action=action,
                    fingerprint=fingerprint,
                    session_id=session_id,
                    current_policy_version=self.policy.policy_version,
                )

        if grant_to_use and grant_to_use.can_apply(action=action, fingerprint=fingerprint, current_policy_version=self.policy.policy_version):
            grant_to_use.consume()
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                reason=f"Authorized by user approval grant '{grant_to_use.grant_id}' (scope={grant_to_use.scope.value}).",
                risk_assessment=effective_risk,
                fingerprint=fingerprint,
            )

        # ── 6. Deterministic SAFE Actions ─────────────────────────────────────
        if effective_risk.risk_level == RiskLevel.SAFE:
            return PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                reason="Safe read-only or inspection action inside workspace.",
                risk_assessment=effective_risk,
                fingerprint=fingerprint,
            )

        # ── 7. LOW-Risk Actions (Workspace Edits, Standard Tests) ─────────────
        if effective_risk.risk_level == RiskLevel.LOW:
            if self.policy.auto_allow_workspace_edits:
                return PermissionDecision(
                    outcome=PermissionOutcome.ALLOW,
                    reason="Low-risk workspace modification authorized by policy.",
                    risk_assessment=effective_risk,
                    fingerprint=fingerprint,
                )

        # ── 8. Headless Mode Evaluation for MEDIUM / HIGH Actions ─────────────
        if is_headless:
            return PermissionDecision(
                outcome=PermissionOutcome.DENY,
                reason_code=DenialReasonCode.HEADLESS_APPROVAL_REQUIRED,
                reason=f"Action of risk={effective_risk.risk_level.value} requires user approval, but runtime is in headless non-interactive mode (FAIL_CLOSED).",
                risk_assessment=effective_risk,
                fingerprint=fingerprint,
                allowed_alternatives=["Run with pre-authorized session policy or in interactive mode."],
            )

        # ── 9. MEDIUM / HIGH Risk Actions Require User Approval (ASK) ─────────
        required_scope = ApprovalScope.ONE_ACTION
        if RiskDimension.SHELL in effective_risk.dimensions or RiskDimension.COMMAND_EXECUTION in effective_risk.dimensions:
            required_scope = ApprovalScope.ACTION_PATTERN
        elif RiskDimension.FILESYSTEM in effective_risk.dimensions or RiskDimension.FILESYSTEM_WRITE in effective_risk.dimensions:
            required_scope = ApprovalScope.PATH_SCOPE

        ask_reasons = "; ".join(effective_risk.reasons) or f"Action has risk level {effective_risk.risk_level.value}."
        return PermissionDecision(
            outcome=PermissionOutcome.ASK,
            reason=f"Confirmation required: {ask_reasons}",
            risk_assessment=effective_risk,
            required_approval_scope=required_scope,
            fingerprint=fingerprint,
            allowed_alternatives=[
                "Approve action once or for session pattern.",
                "Review git diff or test in isolated container.",
                "Deny and choose safe read-only path.",
            ],
        )
