#!/usr/bin/env python3
"""
HERMES - Disagreement Router Tests
Tests: ACCEPT/ESCALATE/BLOCK decisions, priority ordering, always-escalate tools,
       stats tracking, threshold calibration, and user confirmation requirements.

Run: pytest tests/test_routing.py -v
"""

import pytest

from core.verifier import VerificationResult
from core.disagreement_router import (
    DisagreementRouter, RoutingDecision, RouterResult,
    CONFIDENCE_THRESHOLD, ALWAYS_ESCALATE_TOOLS
)


def make_verification(agree=True, confidence=0.90, issues=None, risk=0.2):
    return VerificationResult(
        agree=agree,
        confidence=confidence,
        critical_issues=issues or [],
        risk_score=risk,
        reasoning="test reasoning"
    )


def make_router():
    return DisagreementRouter(confidence_threshold=CONFIDENCE_THRESHOLD)


# ──────────────────────────────────────────────────────────────────────
# ACCEPT cases
# ──────────────────────────────────────────────────────────────────────

def test_accept_when_agree_high_confidence_low_risk():
    router = make_router()
    v = make_verification(agree=True, confidence=0.95, issues=[], risk=0.1)
    result = router.route(v, tool_name="write_file", mode="auto")
    assert result.decision == RoutingDecision.ACCEPT
    assert result.tier3_needed is False


def test_accept_at_exactly_confidence_threshold():
    router = make_router()
    v = make_verification(agree=True, confidence=0.72, issues=[], risk=0.2)
    result = router.route(v, tool_name="read_file", mode="auto")
    assert result.decision == RoutingDecision.ACCEPT


# ──────────────────────────────────────────────────────────────────────
# ESCALATE cases
# ──────────────────────────────────────────────────────────────────────

def test_escalate_when_agree_is_false():
    router = make_router()
    v = make_verification(agree=False, confidence=0.85, issues=["Wrong tool"], risk=0.2)
    result = router.route(v, tool_name="bash_exec", mode="auto")
    assert result.decision == RoutingDecision.ESCALATE
    assert result.tier3_needed is True


def test_escalate_when_confidence_below_threshold():
    router = make_router()
    v = make_verification(agree=True, confidence=0.60, issues=[], risk=0.2)
    result = router.route(v, tool_name="write_file", mode="auto")
    assert result.decision == RoutingDecision.ESCALATE
    assert "confidence" in result.reason.lower()


def test_escalate_when_critical_issues_present():
    router = make_router()
    v = make_verification(agree=True, confidence=0.90, issues=["Code has syntax error"], risk=0.2)
    result = router.route(v, tool_name="write_file", mode="auto")
    assert result.decision == RoutingDecision.ESCALATE


def test_escalate_when_risk_above_threshold():
    router = make_router()
    v = make_verification(agree=True, confidence=0.90, issues=[], risk=0.75)
    result = router.route(v, tool_name="bash_exec", mode="auto")
    assert result.decision == RoutingDecision.ESCALATE


def test_escalate_for_always_escalate_tools():
    router = make_router()
    for tool in ALWAYS_ESCALATE_TOOLS:
        v = make_verification(agree=True, confidence=0.99, issues=[], risk=0.1)
        result = router.route(v, tool_name=tool, mode="auto")
        assert result.decision == RoutingDecision.ESCALATE, f"Expected escalation for {tool}"


# ──────────────────────────────────────────────────────────────────────
# BLOCK cases
# ──────────────────────────────────────────────────────────────────────

def test_block_when_risk_above_hard_threshold():
    router = make_router()
    v = make_verification(agree=True, confidence=0.99, issues=[], risk=0.95)
    result = router.route(v, tool_name="bash_exec", mode="auto")
    assert result.decision == RoutingDecision.BLOCK
    assert result.requires_user_confirm is True


# ──────────────────────────────────────────────────────────────────────
# Stats tracking
# ──────────────────────────────────────────────────────────────────────

def test_router_tracks_accept_escalate_counts():
    router = make_router()

    # 3 accepts
    for _ in range(3):
        v = make_verification(agree=True, confidence=0.95, issues=[], risk=0.1)
        router.route(v, "read_file")

    # 2 escalates
    for _ in range(2):
        v = make_verification(agree=False, confidence=0.50, issues=["issue"], risk=0.2)
        router.route(v, "write_file")

    stats = router.get_stats()
    assert stats["accept"] == 3
    assert stats["escalate"] == 2
    assert stats["total"] == 5


def test_accept_rate_calculation():
    router = make_router()
    for _ in range(8):
        router.route(make_verification(agree=True, confidence=0.95, issues=[], risk=0.1), "read_file")
    for _ in range(2):
        router.route(make_verification(agree=False, confidence=0.5, issues=["x"], risk=0.2), "bash_exec")

    stats = router.get_stats()
    assert abs(stats["accept_rate"] - 0.8) < 0.01


# ──────────────────────────────────────────────────────────────────────
# Threshold calibration
# ──────────────────────────────────────────────────────────────────────

def test_calibrate_threshold_changes_routing():
    router = make_router()
    v = make_verification(agree=True, confidence=0.75, issues=[], risk=0.1)

    # At default threshold (0.72): should ACCEPT
    result = router.route(v, "read_file")
    assert result.decision == RoutingDecision.ACCEPT

    # Raise threshold to 0.80: same verification should now ESCALATE
    router.calibrate_threshold(0.80)
    result = router.route(v, "read_file")
    assert result.decision == RoutingDecision.ESCALATE


def test_git_push_requires_user_confirmation():
    router = make_router()
    v = make_verification(agree=True, confidence=0.99, issues=[], risk=0.1)
    result = router.route(v, tool_name="git_push", mode="auto")
    assert result.requires_user_confirm is True


# ──────────────────────────────────────────────────────────────────────
# Orchestrator unit tests (mocked, no Ollama required)
# ──────────────────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock, patch
from core.orchestrator import Orchestrator, OrchestratorResult


def test_orchestrator_sanitises_html_injection():
    orch = Orchestrator(mode="auto")
    sanitised = orch._sanitise_input("<script>evil()</script> create a file")
    assert "<script>" not in sanitised
    assert "create a file" in sanitised


def test_orchestrator_parse_tier1_valid_json():
    orch = Orchestrator(mode="auto")
    raw = '{"tool": "write_file", "parameters": {"path": "test.py"}, "reasoning": "ok", "explanation": "done"}'
    parsed = orch._parse_tier1_response(raw)
    assert parsed is not None
    assert parsed["tool"] == "write_file"


def test_orchestrator_parse_tier1_invalid_json():
    orch = Orchestrator(mode="auto")
    parsed = orch._parse_tier1_response("this is not json")
    assert parsed is None


def test_orchestrator_parse_tier1_missing_keys():
    orch = Orchestrator(mode="auto")
    parsed = orch._parse_tier1_response('{"reasoning": "I will do something"}')
    assert parsed is None  # Missing "tool" and "parameters"


def test_orchestrator_set_mode_valid():
    orch = Orchestrator(mode="auto")
    orch.set_mode("safe")
    assert orch.mode == "safe"


def test_orchestrator_set_mode_invalid():
    orch = Orchestrator(mode="auto")
    with pytest.raises(ValueError):
        orch.set_mode("turbo")
