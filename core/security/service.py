# core/security/service.py
"""
HERMES 2.x - Security Service Facade (Prompt 13)
High-level service interface for managing security policies, approvals, audit logs,
and interactions between the AgentLoop and the human operator/TUI.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.security.approvals import ApprovalStore
from core.security.audit import SecurityAuditLogger
from core.security.config import SecurityPolicy, get_default_security_policy
from core.security.enums import ApprovalScope, PermissionOutcome
from core.security.gate import SecurityGate
from core.security.intent import IntentAnalyzer
from core.security.models import (
    ActionDescriptor,
    ApprovalGrant,
    ApprovalRequest,
    PermissionDecision,
    UserIntent,
)

logger = logging.getLogger("hermes.security.service")


class SecurityService:
    """
    Primary API facade for managing HERMES security in runtime sessions.
    """

    def __init__(
        self,
        policy: Optional[SecurityPolicy] = None,
        log_file_path: Optional[str] = None,
    ) -> None:
        self.policy = policy or get_default_security_policy()
        self.approval_store = ApprovalStore(self.policy.approval_cache_ttl_seconds)
        self.audit_logger = SecurityAuditLogger(log_file_path)
        self.gate = SecurityGate(
            policy=self.policy,
            approval_store=self.approval_store,
            audit_logger=self.audit_logger,
        )
        self.current_user_intent: Optional[UserIntent] = None

    def set_user_intent_from_prompt(self, user_prompt: str) -> UserIntent:
        """Parse and set authoritative user intent from prompt."""
        self.current_user_intent = IntentAnalyzer.from_user_prompt(user_prompt)
        return self.current_user_intent

    def evaluate_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Tuple[PermissionDecision, ActionDescriptor]:
        """Evaluate a tool action against policy."""
        return self.gate.evaluate_action(
            tool_name=tool_name,
            arguments=arguments,
            user_intent=self.current_user_intent,
            session_id=session_id,
            task_id=task_id,
        )

    def grant_approval(
        self,
        request_id: str,
        scope: ApprovalScope = ApprovalScope.ONCE,
        max_uses: int = 1,
        resolved_by: str = "user",
        ttl_seconds: Optional[float] = None,
    ) -> Optional[ApprovalGrant]:
        """User grant resolution."""
        return self.approval_store.resolve_request(
            request_id=request_id,
            approved=True,
            scope=scope,
            max_uses=max_uses,
            resolved_by=resolved_by,
            ttl_seconds=ttl_seconds,
        )

    def deny_approval(
        self,
        request_id: str,
        resolved_by: str = "user",
    ) -> bool:
        """User denial resolution."""
        res = self.approval_store.resolve_request(
            request_id=request_id,
            approved=False,
            resolved_by=resolved_by,
        )
        return res is None

    def get_pending_requests(self) -> List[ApprovalRequest]:
        """Return all requests awaiting operator decision."""
        return self.approval_store.get_pending_requests()

    def get_audit_records(self) -> List[Dict[str, Any]]:
        """Return audit trail records."""
        return self.audit_logger.get_records()

    def update_policy(self, **kwargs: Any) -> SecurityPolicy:
        """Update runtime policy settings."""
        for k, v in kwargs.items():
            if hasattr(self.policy, k):
                setattr(self.policy, k, v)
        return self.policy
