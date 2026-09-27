# core/security/__init__.py
"""
HERMES 2.x - Security Subsystem (Prompt 13)
Export authoritative security boundaries, models, gate, and service.
"""

from core.security.enums import (
    RiskLevel,
    RiskDimension,
    PermissionOutcome,
    ApprovalScope,
    ContentTrust,
    PromptInjectionStatus,
    InjectionAttackFamily,
    DenialReasonCode,
    HeadlessBehavior,
)
from core.security.models import (
    UserIntent,
    ActionDescriptor,
    RiskAssessment,
    PermissionDecision,
    ApprovalGrant,
    ApprovalRequest,
    PromptInjectionAssessment,
    SubagentSecurityContext,
    HandoffSecurityAssessment,
    SecurityViolation,
    SecurityExecutionResult,
)
from core.security.config import (
    SecurityPolicy,
    get_default_security_policy,
    validate_security_policy,
)
from core.security.action_fingerprint import (
    compute_action_fingerprint,
    normalize_path,
    normalize_arguments,
)
from core.security.intent import IntentAnalyzer
from core.security.risk import RiskEngine, redact_sensitive_text
from core.security.policy import PolicyEngine
from core.security.approvals import ApprovalStore
from core.security.prompt_injection import PromptInjectionProbe
from core.security.content_boundary import ContentBoundary
from core.security.subagent_security import SubagentSecurityGovernor
from core.security.handoff_security import HandoffSecurityChecker
from core.security.denial import DenialTracker
from core.security.classifier import ActionClassifier
from core.security.audit import SecurityAuditLogger
from core.security.gate import SecurityGate
from core.security.service import SecurityService

__all__ = [
    "RiskLevel",
    "RiskDimension",
    "PermissionOutcome",
    "ApprovalScope",
    "ContentTrust",
    "PromptInjectionStatus",
    "InjectionAttackFamily",
    "DenialReasonCode",
    "HeadlessBehavior",
    "UserIntent",
    "ActionDescriptor",
    "RiskAssessment",
    "PermissionDecision",
    "ApprovalGrant",
    "ApprovalRequest",
    "PromptInjectionAssessment",
    "SubagentSecurityContext",
    "HandoffSecurityAssessment",
    "SecurityViolation",
    "SecurityExecutionResult",
    "SecurityPolicy",
    "get_default_security_policy",
    "validate_security_policy",
    "compute_action_fingerprint",
    "normalize_path",
    "normalize_arguments",
    "IntentAnalyzer",
    "RiskEngine",
    "redact_sensitive_text",
    "PolicyEngine",
    "ApprovalStore",
    "PromptInjectionProbe",
    "ContentBoundary",
    "SubagentSecurityGovernor",
    "HandoffSecurityChecker",
    "DenialTracker",
    "ActionClassifier",
    "SecurityAuditLogger",
    "SecurityGate",
    "SecurityService",
]
