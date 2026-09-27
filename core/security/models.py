# core/security/models.py
"""
Data models for HERMES 2.x Security and Permission Architecture.
All models carry stable correlation identifiers and immutable representations.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set

from core.security.enums import (
    RiskLevel,
    RiskDimension,
    PermissionOutcome,
    ApprovalScope,
    ContentTrust,
    PromptInjectionStatus,
    InjectionAttackFamily,
    DenialReasonCode,
)


@dataclass
class UserIntent:
    """Explicit authorized intent established by user input."""
    intent_id: str = field(default_factory=lambda: f"intent_{uuid.uuid4().hex[:8]}")
    requested_goal: str = ""
    authorized_scope: List[str] = field(default_factory=list)
    explicit_constraints: List[str] = field(default_factory=list)
    prohibited_operations: List[str] = field(default_factory=list)
    target_resources: List[str] = field(default_factory=list)
    confidence: float = 1.0
    source_messages: List[str] = field(default_factory=list)
    raw_prompt: str = ""
    goal_summary: Optional[str] = None
    prohibitions: Optional[List[str]] = None

    def __post_init__(self):
        if self.goal_summary and not self.requested_goal:
            self.requested_goal = self.goal_summary
        elif self.requested_goal and not self.goal_summary:
            self.goal_summary = self.requested_goal

        if self.prohibitions and not self.prohibited_operations:
            self.prohibited_operations = list(self.prohibitions)
        elif self.prohibited_operations and not self.prohibitions:
            self.prohibitions = list(self.prohibited_operations)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionDescriptor:
    """
    Structured, normalized representation of an action proposed by an agent.
    Separates the physical action from agent reasoning.
    """
    action_id: str = field(default_factory=lambda: f"act_{uuid.uuid4().hex[:8]}")
    tool_name: str = ""
    operation: str = ""  # read, write, edit, delete, execute, network, delegate
    arguments: Dict[str, Any] = field(default_factory=dict)
    target_paths: List[str] = field(default_factory=list)
    cwd: str = ""
    network_destinations: List[str] = field(default_factory=list)
    filesystem_scope: str = "workspace"  # workspace, external, system
    data_sources: List[str] = field(default_factory=list)
    expected_side_effects: List[str] = field(default_factory=list)
    reversibility: bool = True
    destructive: bool = False
    external_side_effect: bool = False
    mission_id: Optional[str] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    agent_id: str = "primary"
    action_fingerprint: str = ""
    canonical_path: Optional[str] = None
    command_str: Optional[str] = None
    target_url: Optional[str] = None
    is_read_only: bool = True
    is_subagent_action: bool = False
    task_id: Optional[str] = None
    risk_assessment: Optional[RiskAssessment] = None

    def __post_init__(self):
        if self.canonical_path and self.canonical_path not in self.target_paths:
            self.target_paths.append(self.canonical_path)
        if self.target_url and self.target_url not in self.network_destinations:
            self.network_destinations.append(self.target_url)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RiskAssessment:
    """Output of the RiskEngine evaluating an ActionDescriptor."""
    assessment_id: str = field(default_factory=lambda: f"risk_{uuid.uuid4().hex[:8]}")
    risk_level: RiskLevel = RiskLevel.SAFE
    dimensions: List[RiskDimension] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    confidence: float = 1.0
    action_fingerprint: str = ""
    created_at: float = field(default_factory=time.monotonic)
    level: Optional[RiskLevel] = None
    score: Optional[float] = None
    summary: Optional[str] = None

    def __post_init__(self):
        if self.level is not None:
            self.risk_level = self.level
        else:
            self.level = self.risk_level

        if self.score is not None:
            self.confidence = self.score
        else:
            self.score = self.confidence

        if self.summary is not None and self.summary not in self.reasons:
            self.reasons.append(self.summary)
        elif self.reasons and not self.summary:
            self.summary = "; ".join(self.reasons)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["risk_level"] = self.risk_level.value
        d["dimensions"] = [dim.value for dim in self.dimensions]
        return d


@dataclass
class PermissionDecision:
    """The authoritative clearance decision issued by the PolicyEngine."""
    decision_id: str = field(default_factory=lambda: f"perm_{uuid.uuid4().hex[:8]}")
    outcome: PermissionOutcome = PermissionOutcome.ALLOW
    reason_code: DenialReasonCode = DenialReasonCode.POLICY_VIOLATION
    reason: str = "Authorized"
    risk_assessment: Optional[RiskAssessment] = None
    required_approval_scope: ApprovalScope = ApprovalScope.ONE_ACTION
    allowed_alternatives: List[str] = field(default_factory=list)
    fingerprint: str = ""
    expires_at: Optional[float] = None
    created_at: float = field(default_factory=time.monotonic)

    @property
    def required_scope(self) -> ApprovalScope:
        return self.required_approval_scope

    @required_scope.setter
    def required_scope(self, val: ApprovalScope) -> None:
        self.required_approval_scope = val

    @property
    def suggested_alternative(self) -> Optional[str]:
        return self.allowed_alternatives[0] if self.allowed_alternatives else None

    @suggested_alternative.setter
    def suggested_alternative(self, val: Optional[str]) -> None:
        if val:
            self.allowed_alternatives = [val]

    @property
    def is_allowed(self) -> bool:
        return self.outcome == PermissionOutcome.ALLOW

    @property
    def is_denied(self) -> bool:
        return self.outcome == PermissionOutcome.DENY

    @property
    def requires_ask(self) -> bool:
        return self.outcome == PermissionOutcome.ASK

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        d["reason_code"] = self.reason_code.value
        d["required_approval_scope"] = self.required_approval_scope.value
        if self.risk_assessment:
            d["risk_assessment"] = self.risk_assessment.to_dict()
        return d


@dataclass
class ApprovalGrant:
    """An active user authorization grant."""
    grant_id: str = field(default_factory=lambda: f"grant_{uuid.uuid4().hex[:8]}")
    session_id: Optional[str] = None
    scope: ApprovalScope = ApprovalScope.ONE_ACTION
    fingerprint: Optional[str] = None
    tool_name: str = ""
    path_scope: Optional[str] = None
    pattern: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)
    expires_at: Optional[float] = None
    issuer: str = "user"
    reason: str = ""
    max_uses: int = 1
    uses_count: int = 0
    policy_version: str = "1.0.0"
    revoked: bool = False
    action_fingerprint: Optional[str] = None
    path_prefix: Optional[str] = None
    command_pattern: Optional[str] = None
    granted_by: Optional[str] = None
    remaining_uses: Optional[int] = None

    def __post_init__(self):
        if self.action_fingerprint and not self.fingerprint:
            self.fingerprint = self.action_fingerprint
        elif self.fingerprint and not self.action_fingerprint:
            self.action_fingerprint = self.fingerprint

        if self.path_prefix and not self.path_scope:
            self.path_scope = self.path_prefix
        elif self.path_scope and not self.path_prefix:
            self.path_prefix = self.path_scope

        if self.command_pattern and not self.pattern:
            self.pattern = self.command_pattern
        elif self.pattern and not self.command_pattern:
            self.command_pattern = self.pattern

        if self.granted_by and self.issuer == "user":
            self.issuer = self.granted_by
        elif self.issuer and not self.granted_by:
            self.granted_by = self.issuer

        if self.remaining_uses is not None:
            self.uses_count = max(0, self.max_uses - self.remaining_uses)
        else:
            self.remaining_uses = max(0, self.max_uses - self.uses_count)

    @property
    def is_expired(self) -> bool:
        if self.revoked:
            return True
        if self.expires_at is not None and time.time() > self.expires_at:
            return True
        if self.scope in (ApprovalScope.ONE_ACTION, ApprovalScope.ONE_TOOL_CALL) and self.uses_count >= self.max_uses:
            return True
        return False

    def can_apply(
        self,
        action: Optional[ActionDescriptor] = None,
        fingerprint: Optional[str] = None,
        current_policy_version: Optional[str] = None,
    ) -> bool:
        """Evaluate if this grant authorizes the action."""
        if self.revoked or self.is_expired:
            return False
        if (self.max_uses - self.uses_count) <= 0:
            return False

        if current_policy_version and self.policy_version != current_policy_version:
            return False

        if action is None and fingerprint is None:
            return True

        candidate_fps = {f for f in (fingerprint, getattr(action, "action_fingerprint", None)) if f}
        grant_fps = {f for f in (self.fingerprint, self.action_fingerprint) if f}

        if self.scope in (ApprovalScope.ONE_ACTION, ApprovalScope.ONE_TOOL_CALL):
            return bool(candidate_fps & grant_fps)

        if action:
            if self.scope == ApprovalScope.TOOL_SCOPE:
                return self.tool_name == action.tool_name

            if self.scope == ApprovalScope.ACTION_PATTERN:
                if self.tool_name != action.tool_name:
                    return False
                if self.pattern and self.pattern in str(action.arguments):
                    return True
                return bool(candidate_fps & grant_fps)

            if self.scope == ApprovalScope.PATH_SCOPE:
                if self.tool_name and self.tool_name != action.tool_name:
                    return False
                for p in action.target_paths:
                    if self.path_scope and not p.startswith(self.path_scope):
                        return False
                return True

            if self.scope == ApprovalScope.SESSION_SCOPE:
                if self.tool_name and self.tool_name != action.tool_name:
                    return False
                return True

        return False

    def consume(self) -> bool:
        if self.revoked or self.is_expired or (self.max_uses - self.uses_count) <= 0:
            return False
        self.uses_count += 1
        self.remaining_uses = max(0, self.max_uses - self.uses_count)
        return True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scope"] = self.scope.value
        return d


@dataclass
class ApprovalRequest:
    """Pending user authorization request."""
    request_id: str = field(default_factory=lambda: f"req_appr_{uuid.uuid4().hex[:8]}")
    mission_id: Optional[str] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    action_descriptor: Optional[ActionDescriptor] = None
    risk_assessment: Optional[RiskAssessment] = None
    proposed_scope: ApprovalScope = ApprovalScope.ONE_ACTION
    status: str = "PENDING"  # PENDING, APPROVED, DENIED, CANCELLED, EXPIRED
    created_at: float = field(default_factory=time.monotonic)
    expires_at: Optional[float] = None
    resolved_at: Optional[float] = None
    resolved: bool = False
    approved: bool = False
    resolved_by: str = "user"
    action: Optional[ActionDescriptor] = None
    assessment: Optional[RiskAssessment] = None
    required_scope: ApprovalScope = ApprovalScope.ONE_ACTION

    def __post_init__(self):
        if self.action and not self.action_descriptor:
            self.action_descriptor = self.action
        elif self.action_descriptor and not self.action:
            self.action = self.action_descriptor

        if self.assessment and not self.risk_assessment:
            self.risk_assessment = self.assessment
        elif self.risk_assessment and not self.assessment:
            self.assessment = self.risk_assessment

        if self.required_scope != ApprovalScope.ONE_ACTION and self.proposed_scope == ApprovalScope.ONE_ACTION:
            self.proposed_scope = self.required_scope
        elif self.proposed_scope != ApprovalScope.ONE_ACTION and self.required_scope == ApprovalScope.ONE_ACTION:
            self.required_scope = self.proposed_scope

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["proposed_scope"] = self.proposed_scope.value
        if self.action_descriptor:
            d["action_descriptor"] = self.action_descriptor.to_dict()
        if self.risk_assessment:
            d["risk_assessment"] = self.risk_assessment.to_dict()
        return d


@dataclass
class PromptInjectionAssessment:
    """Output of the PromptInjectionProbe evaluating external text."""
    assessment_id: str = field(default_factory=lambda: f"inj_{uuid.uuid4().hex[:8]}")
    status: PromptInjectionStatus = PromptInjectionStatus.NOT_DETECTED
    confidence: float = 0.0
    attack_family: Optional[InjectionAttackFamily] = None
    matched_patterns: List[str] = field(default_factory=list)
    reason: Optional[str] = None
    warning_required: bool = False
    should_block: bool = False
    provenance: ContentTrust = ContentTrust.LOCAL_FILE
    source_id: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)
    indicators: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.indicators and not self.matched_patterns:
            self.matched_patterns = list(self.indicators)
        elif self.matched_patterns and not self.indicators:
            self.indicators = list(self.matched_patterns)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["attack_family"] = self.attack_family.value if self.attack_family else None
        d["provenance"] = self.provenance.value
        return d


@dataclass
class SubagentSecurityContext:
    """Authoritative security boundary for child subagents."""
    agent_id: str
    parent_agent_id: Optional[str] = None
    permission_ceiling: Set[str] = field(default_factory=set)
    allowed_tools: List[str] = field(default_factory=list)
    denied_tools: List[str] = field(default_factory=list)
    allowed_paths: List[str] = field(default_factory=list)
    denied_paths: List[str] = field(default_factory=list)
    can_network: bool = False
    can_shell: bool = False
    can_mutate: bool = False
    risk_ceiling: RiskLevel = RiskLevel.MEDIUM
    current_depth: int = 0
    max_depth: int = 2
    # Compatibility properties
    parent_id: Optional[str] = None
    depth: Optional[int] = None
    read_only: Optional[bool] = None
    path_boundaries: Optional[List[str]] = None
    can_spawn_subagents: Optional[bool] = None
    network_enabled: Optional[bool] = None

    def __post_init__(self):
        if self.parent_id is not None and self.parent_agent_id is None:
            self.parent_agent_id = self.parent_id
        elif self.parent_agent_id is not None and self.parent_id is None:
            self.parent_id = self.parent_agent_id

        if self.depth is not None:
            self.current_depth = self.depth
        else:
            self.depth = self.current_depth

        if self.read_only is not None:
            self.can_mutate = not self.read_only
        else:
            self.read_only = not self.can_mutate

        if self.path_boundaries is not None:
            self.allowed_paths = list(self.path_boundaries)
        else:
            self.path_boundaries = list(self.allowed_paths)

        if self.network_enabled is not None:
            self.can_network = self.network_enabled
        else:
            self.network_enabled = self.can_network

        if self.can_spawn_subagents is None:
            self.can_spawn_subagents = (self.current_depth < self.max_depth)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["permission_ceiling"] = list(self.permission_ceiling)
        d["risk_ceiling"] = self.risk_ceiling.value
        return d


@dataclass
class HandoffSecurityAssessment:
    """Verification assessment of subagent results upon return to parent."""
    assessment_id: str = field(default_factory=lambda: f"handoff_sec_{uuid.uuid4().hex[:8]}")
    agent_id: str = ""
    parent_agent_id: str = ""
    status: str = "BENIGN"  # BENIGN, SUSPICIOUS, SECURITY_VIOLATION, CRITICAL
    risk_level: RiskLevel = RiskLevel.LOW
    findings: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    warning_required: bool = False
    blocked_elements: List[str] = field(default_factory=list)
    subagent_id: str = ""
    safe_to_ingest: bool = True
    injection_detected: bool = False
    sanitized_payload: str = ""

    def __post_init__(self):
        if self.subagent_id and not self.agent_id:
            self.agent_id = self.subagent_id
        elif self.agent_id and not self.subagent_id:
            self.subagent_id = self.agent_id

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["risk_level"] = self.risk_level.value
        return d


@dataclass
class SecurityViolation:
    """Record of an unauthorized or suspicious action attempt."""
    violation_id: str = field(default_factory=lambda: f"viol_{uuid.uuid4().hex[:8]}")
    action_id: str = ""
    tool_name: str = ""
    reason_code: DenialReasonCode = DenialReasonCode.POLICY_VIOLATION
    description: str = ""
    severity: RiskLevel = RiskLevel.HIGH
    agent_id: str = "primary"
    turn_id: Optional[str] = None
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["reason_code"] = self.reason_code.value
        d["severity"] = self.severity.value
        return d


@dataclass
class SecurityContext:
    """Full runtime security context passed across execution stages."""
    mission_id: str
    session_id: str
    turn_id: Optional[str] = None
    agent_id: str = "primary"
    parent_agent_id: Optional[str] = None
    user_intent: Optional[UserIntent] = None
    subagent_context: Optional[SubagentSecurityContext] = None
    is_headless: bool = False
    policy_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "agent_id": self.agent_id,
            "parent_agent_id": self.parent_agent_id,
            "user_intent": self.user_intent.to_dict() if self.user_intent else None,
            "subagent_context": self.subagent_context.to_dict() if self.subagent_context else None,
            "is_headless": self.is_headless,
            "policy_version": self.policy_version,
        }


@dataclass
class SecurityExecutionResult:
    """Outcome of passing an action through the SecurityGate."""
    decision: PermissionDecision
    action_fingerprint: str = ""
    risk_assessment: Optional[RiskAssessment] = None
    executed: bool = False
    denied: bool = False
    reason: str = ""
    audit_id: str = field(default_factory=lambda: f"audit_{uuid.uuid4().hex[:8]}")
    raw_output: str = ""
    sanitized_output: str = ""
    injection_assessment: Optional[PromptInjectionAssessment] = None
    observation: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "action_fingerprint": self.action_fingerprint,
            "risk_assessment": self.risk_assessment.to_dict() if self.risk_assessment else None,
            "executed": self.executed,
            "denied": self.denied,
            "reason": self.reason,
            "audit_id": self.audit_id,
            "injection_assessment": self.injection_assessment.to_dict() if self.injection_assessment else None,
        }
