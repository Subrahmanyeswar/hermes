# tests/test_permission_policy.py
"""
Unit tests for Prompt 13 Permission Policy Engine (ALLOW / DENY / ASK, Precedence, Approvals).
"""

import time
import pytest
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
    ApprovalGrant,
    RiskAssessment,
    UserIntent,
)
from core.security.policy import PolicyEngine


@pytest.fixture
def policy_engine():
    return PolicyEngine()


def test_critical_risk_is_hard_denied(policy_engine):
    action = ActionDescriptor(tool_name="run_command", arguments={"command": "rm -rf /"})
    assessment = RiskAssessment(level=RiskLevel.CRITICAL, dimensions=[RiskDimension.DESTRUCTIVE])
    decision = policy_engine.evaluate(action, assessment)
    assert decision.outcome == PermissionOutcome.DENY
    assert decision.reason_code == DenialReasonCode.HARD_SECURITY_DENY


def test_security_tampering_cannot_be_bypassed_by_grant(policy_engine):
    action = ActionDescriptor(
        tool_name="write_file",
        arguments={"path": "core/security/gate.py"},
        canonical_path="c:/workspace/core/security/gate.py",
    )
    assessment = RiskAssessment(level=RiskLevel.CRITICAL, dimensions=[RiskDimension.SECURITY_TAMPERING])
    # Even if someone forged a grant:
    fake_grant = ApprovalGrant(
        grant_id="fake",
        scope=ApprovalScope.ALWAYS,
        tool_name="write_file",
        created_at=time.time(),
    )
    decision = policy_engine.evaluate(action, assessment, matching_grant=fake_grant)
    # MUST STILL DENY: Hard security deny has absolute precedence!
    assert decision.outcome == PermissionOutcome.DENY
    assert decision.reason_code in (DenialReasonCode.HARD_SECURITY_DENY, DenialReasonCode.SECURITY_POLICY_MODIFICATION)


def test_user_intent_prohibition_denies(policy_engine):
    action = ActionDescriptor(tool_name="run_command", arguments={"command": "drop database users"})
    assessment = RiskAssessment(level=RiskLevel.MEDIUM, dimensions=[RiskDimension.FILESYSTEM_DELETE])
    intent = UserIntent(
        raw_prompt="clean the logs but do not drop database",
        goal_summary="clean logs",
        prohibitions=["drop database"],
    )
    decision = policy_engine.evaluate(action, assessment, user_intent=intent)
    assert decision.outcome == PermissionOutcome.DENY
    assert decision.reason_code == DenialReasonCode.USER_INTENT_PROHIBITED


def test_safe_read_only_is_allowed(policy_engine):
    action = ActionDescriptor(
        tool_name="view_file",
        arguments={"path": "src/App.tsx"},
        is_read_only=True,
    )
    assessment = RiskAssessment(level=RiskLevel.SAFE)
    decision = policy_engine.evaluate(action, assessment)
    assert decision.outcome == PermissionOutcome.ALLOW


def test_matching_grant_allows_high_risk_action(policy_engine):
    action = ActionDescriptor(
        tool_name="run_command",
        arguments={"command": "npm install lodash"},
        action_fingerprint="fp_npm_install",
    )
    assessment = RiskAssessment(level=RiskLevel.MEDIUM, dimensions=[RiskDimension.COMMAND_EXECUTION])
    grant = ApprovalGrant(
        grant_id="grant_npm",
        scope=ApprovalScope.EXACT_ACTION,
        action_fingerprint="fp_npm_install",
        tool_name="run_command",
        max_uses=1,
        remaining_uses=1,
        created_at=time.time(),
    )
    decision = policy_engine.evaluate(action, assessment, matching_grant=grant)
    assert decision.outcome == PermissionOutcome.ALLOW


def test_unapproved_medium_risk_asks_in_interactive_mode(policy_engine):
    action = ActionDescriptor(
        tool_name="run_command",
        arguments={"command": "npm run build"},
    )
    assessment = RiskAssessment(level=RiskLevel.MEDIUM, dimensions=[RiskDimension.COMMAND_EXECUTION])
    decision = policy_engine.evaluate(action, assessment, headless_mode=False)
    assert decision.outcome == PermissionOutcome.ASK
    assert decision.required_scope in (
        ApprovalScope.EXACT_ACTION,
        ApprovalScope.PATH_PREFIX,
        ApprovalScope.ONCE,
        ApprovalScope.ACTION_PATTERN,
        ApprovalScope.COMMAND_PATTERN,
    )


def test_headless_mode_fails_closed(policy_engine):
    # In headless mode without approval grant, medium/high risk must DENY
    action = ActionDescriptor(
        tool_name="run_command",
        arguments={"command": "pip install requests"}
    )
    assessment = RiskAssessment(level=RiskLevel.MEDIUM, dimensions=[RiskDimension.COMMAND_EXECUTION])
    decision = policy_engine.evaluate(action, assessment, headless_mode=True)
    assert decision.outcome == PermissionOutcome.DENY
    assert decision.reason_code == DenialReasonCode.HEADLESS_BLOCKED
