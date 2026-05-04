#!/usr/bin/env python3
"""
HERMES — Tier 2 Verifier Tests
Tests: VerificationResult dataclass, escalation logic, verify() with mocked Ollama,
       error handling (timeout, connection, malformed JSON), and value clamping.

Run: pytest tests/test_verifier.py -v
"""

import asyncio
import pytest
from unittest.mock import AsyncMock

from core.verifier import Tier2Verifier, VerificationResult
from models.ollama_client import OllamaClient, OllamaTimeoutError, OllamaConnectionError


def make_verifier():
    mock_client = AsyncMock(spec=OllamaClient)
    return Tier2Verifier(ollama_client=mock_client, model="mistral:7b-instruct-q4_K_M")


# ──────────────────────────────────────────────────────────────────────
# Verification Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_agree_true_no_issues():
    verifier = make_verifier()
    verifier.client.generate = AsyncMock(return_value=(
        '{"agree": true, "confidence": 0.95, "critical_issues": [], '
        '"risk_score": 0.2, "reasoning": "Tool call is correct and safe."}'
    ))
    result = await verifier.verify(
        task="Create a file hello.py",
        tier1_reasoning="I will use write_file to create hello.py",
        tool_name="write_file",
        tool_parameters={"path": "hello.py", "content": 'print("hello")'},
        tool_result_output="Written 14 characters to hello.py",
        tool_exit_code=0
    )
    assert result.agree is True
    assert result.confidence == 0.95
    assert result.critical_issues == []
    assert result.risk_score == 0.2
    assert result.should_escalate is False


@pytest.mark.asyncio
async def test_verify_disagree_with_issues():
    verifier = make_verifier()
    verifier.client.generate = AsyncMock(return_value=(
        '{"agree": false, "confidence": 0.85, '
        '"critical_issues": ["Wrong tool used — should be write_file not bash_exec"], '
        '"risk_score": 0.6, "reasoning": "bash_exec is unnecessary for file creation."}'
    ))
    result = await verifier.verify(
        task="Create a file hello.py",
        tier1_reasoning="I will use bash to create the file",
        tool_name="bash_exec",
        tool_parameters={"command": "echo '' > hello.py"},
        tool_result_output="",
        tool_exit_code=0
    )
    assert result.agree is False
    assert len(result.critical_issues) == 1
    assert result.should_escalate is True


@pytest.mark.asyncio
async def test_verify_high_risk_score_triggers_escalation():
    verifier = make_verifier()
    verifier.client.generate = AsyncMock(return_value=(
        '{"agree": true, "confidence": 0.80, "critical_issues": [], '
        '"risk_score": 0.85, "reasoning": "Action is valid but high risk."}'
    ))
    result = await verifier.verify(
        task="Push to GitHub",
        tier1_reasoning="Use git push to upload code",
        tool_name="git_push",
        tool_parameters={"directory": ".", "remote": "origin"},
        tool_result_output="Pushed to origin/main",
        tool_exit_code=0
    )
    assert result.should_escalate is True  # risk_score 0.85 > 0.7


@pytest.mark.asyncio
async def test_verify_low_confidence_triggers_escalation():
    verifier = make_verifier()
    verifier.client.generate = AsyncMock(return_value=(
        '{"agree": true, "confidence": 0.60, "critical_issues": [], '
        '"risk_score": 0.2, "reasoning": "Uncertain about correctness."}'
    ))
    result = await verifier.verify(
        task="Some ambiguous task",
        tier1_reasoning="Not sure which tool",
        tool_name="read_file",
        tool_parameters={"path": "app.py"},
        tool_result_output="content here",
        tool_exit_code=0
    )
    assert result.should_escalate is True  # confidence 0.60 < 0.72


@pytest.mark.asyncio
async def test_verify_handles_timeout_gracefully():
    verifier = make_verifier()
    verifier.client.generate = AsyncMock(side_effect=OllamaTimeoutError("timeout"))
    result = await verifier.verify(
        task="Any task", tier1_reasoning="reason",
        tool_name="write_file", tool_parameters={},
        tool_result_output="", tool_exit_code=0
    )
    assert result.agree is False
    assert result.should_escalate is True
    assert "timed out" in result.critical_issues[0].lower()


@pytest.mark.asyncio
async def test_verify_handles_connection_error_fail_open():
    """When Ollama is unreachable, fail open — proceed with T1's result."""
    verifier = make_verifier()
    verifier.client.generate = AsyncMock(side_effect=OllamaConnectionError("no connection"))
    result = await verifier.verify(
        task="Safe task", tier1_reasoning="reason",
        tool_name="read_file", tool_parameters={},
        tool_result_output="content", tool_exit_code=0
    )
    assert result.agree is True   # Fail open for connection errors
    assert result.confidence == 0.5


@pytest.mark.asyncio
async def test_verify_handles_malformed_json():
    verifier = make_verifier()
    verifier.client.generate = AsyncMock(return_value="this is not json at all")
    result = await verifier.verify(
        task="Any task", tier1_reasoning="reason",
        tool_name="write_file", tool_parameters={},
        tool_result_output="", tool_exit_code=0
    )
    assert "critical_issues" in result.__dict__
    assert result.confidence <= 0.5


@pytest.mark.asyncio
async def test_verify_clamps_values_to_valid_range():
    verifier = make_verifier()
    verifier.client.generate = AsyncMock(return_value=(
        '{"agree": true, "confidence": 1.5, "critical_issues": [], '
        '"risk_score": -0.3, "reasoning": "Values out of range."}'
    ))
    result = await verifier.verify(
        task="Task", tier1_reasoning="reason",
        tool_name="read_file", tool_parameters={},
        tool_result_output="", tool_exit_code=0
    )
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.risk_score <= 1.0


# ──────────────────────────────────────────────────────────────────────
# Unit Tests for VerificationResult
# ──────────────────────────────────────────────────────────────────────

def test_verification_result_should_escalate_logic():
    """Unit test the should_escalate property directly."""
    # All good — no escalation
    r = VerificationResult(agree=True, confidence=0.90, critical_issues=[], risk_score=0.2, reasoning="OK")
    assert r.should_escalate is False

    # Low confidence — escalate
    r = VerificationResult(agree=True, confidence=0.50, critical_issues=[], risk_score=0.2, reasoning="uncertain")
    assert r.should_escalate is True

    # Disagree — escalate
    r = VerificationResult(agree=False, confidence=0.90, critical_issues=["issue"], risk_score=0.2, reasoning="wrong")
    assert r.should_escalate is True

    # High risk — escalate even if agree
    r = VerificationResult(agree=True, confidence=0.95, critical_issues=[], risk_score=0.8, reasoning="risky")
    assert r.should_escalate is True
