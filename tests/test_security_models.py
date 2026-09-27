# tests/test_security_models.py
"""
Unit tests for Prompt 13 Security & Permission Models, Enums, Fingerprints, and Intent.
"""

import time
import pytest
from core.security.enums import (
    ApprovalScope,
    ContentTrust,
    DenialReasonCode,
    HeadlessBehavior,
    InjectionAttackFamily,
    PermissionOutcome,
    PromptInjectionStatus,
    RiskDimension,
    RiskLevel,
)
from core.security.models import (
    ActionDescriptor,
    ApprovalGrant,
    ApprovalRequest,
    PromptInjectionAssessment,
    RiskAssessment,
    SubagentSecurityContext,
    UserIntent,
)
from core.security.action_fingerprint import compute_action_fingerprint, normalize_path
from core.security.intent import IntentAnalyzer


def test_risk_level_ordering():
    assert RiskLevel.SAFE.rank < RiskLevel.LOW.rank
    assert RiskLevel.LOW.rank < RiskLevel.MEDIUM.rank
    assert RiskLevel.MEDIUM.rank < RiskLevel.HIGH.rank
    assert RiskLevel.HIGH.rank < RiskLevel.CRITICAL.rank


def test_deterministic_action_fingerprint():
    args1 = {"path": "/workspace/src/app.py", "content": "print('hello')", "mode": "w"}
    args2 = {"content": "print('hello')", "mode": "w", "path": "/workspace/src/app.py"}
    
    fp1 = compute_action_fingerprint("write_file", args1, canonical_path="/workspace/src/app.py")
    fp2 = compute_action_fingerprint("write_file", args2, canonical_path="/workspace/src/app.py")
    
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA256 hex


def test_fingerprint_changes_on_argument_mutation():
    args1 = {"path": "/workspace/src/app.py", "content": "print('hello')"}
    args2 = {"path": "/workspace/src/app.py", "content": "print('world')"}
    
    fp1 = compute_action_fingerprint("write_file", args1)
    fp2 = compute_action_fingerprint("write_file", args2)
    
    assert fp1 != fp2


def test_path_normalization():
    p1 = normalize_path("C:\\workspace\\project\\..\\project\\src\\main.py")
    p2 = normalize_path("c:/workspace/project/src/main.py")
    assert p1.replace("\\", "/").lower() == p2.replace("\\", "/").lower()


def test_approval_grant_lifecycle():
    grant = ApprovalGrant(
        grant_id="grant_123",
        scope=ApprovalScope.EXACT_ACTION,
        action_fingerprint="fp_abc",
        tool_name="run_command",
        max_uses=2,
        remaining_uses=2,
        created_at=time.time(),
        expires_at=time.time() + 60.0,
    )
    assert grant.can_apply() is True
    assert grant.consume() is True
    assert grant.remaining_uses == 1
    assert grant.can_apply() is True
    assert grant.consume() is True
    assert grant.remaining_uses == 0
    assert grant.can_apply() is False
    assert grant.consume() is False


def test_approval_grant_expiration():
    grant = ApprovalGrant(
        grant_id="grant_expired",
        scope=ApprovalScope.EXACT_ACTION,
        action_fingerprint="fp_abc",
        tool_name="run_command",
        max_uses=5,
        remaining_uses=5,
        created_at=time.time() - 100.0,
        expires_at=time.time() - 10.0,  # in the past
    )
    assert grant.can_apply() is False


def test_approval_grant_revocation():
    grant = ApprovalGrant(
        grant_id="grant_revoked",
        scope=ApprovalScope.EXACT_ACTION,
        action_fingerprint="fp_abc",
        tool_name="run_command",
        max_uses=5,
        remaining_uses=5,
        revoked=True,
    )
    assert grant.can_apply() is False


def test_intent_analyzer_parsing():
    prompt = "Please build the login page. Do NOT delete any database tables and avoid external network calls."
    intent = IntentAnalyzer.from_user_prompt(prompt)
    assert "build" in intent.goal_summary.lower() or "login" in intent.goal_summary.lower()
    assert any("delete" in p.lower() for p in intent.prohibitions)
    assert any("network" in p.lower() for p in intent.prohibitions)
