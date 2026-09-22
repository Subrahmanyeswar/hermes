"""
Unit and Integration Tests for Phase 11 Intelligent Model Routing Engine.
Tests all 12 test matrix cases:
Case 1: Low risk + High confidence + Verified -> ACCEPT_T1
Case 2: Low risk + Low confidence -> ESCALATE_T2
Case 3: High risk + High confidence -> FAIL_SAFE / Strong verification
Case 4: High risk + Low confidence -> FAIL_SAFE
Case 5: T1/T2 agreement -> ACCEPT_T2 (No T3)
Case 6: T1/T2 disagreement -> ESCALATE_T3
Case 7: T2 unavailable -> Safe fallback
Case 8: T3 unavailable / cap reached -> Safe fallback
Case 9: T1 transient failure -> RETRY_T1
Case 10: T1 repeated failure -> ESCALATE_T2
Case 11: Verification failed -> RETRY_T1 / ESCALATE_T2
Case 12: Read-only deterministic task -> ACCEPT_T1
"""
import pytest
from core.intelligent_router import (
    RoutingAction,
    RoutingDecision,
    IntelligentRouter
)


@pytest.fixture
def router():
    return IntelligentRouter(enabled=True, t2_confidence_threshold=0.70, high_risk_threshold=0.60)


def test_case_1_low_risk_high_confidence_passed(router):
    """Case 1: Low risk, high T1 confidence, verification passed -> ACCEPT_T1 directly (0 T2/T3 calls)."""
    decision = router.route_t1_result(
        task_text="Add helper method to utils.py",
        complexity="STANDARD",
        confidence=0.88,
        risk_score=0.15,
        tool_name="write_file",
        verification_result="PASSED"
    )
    assert decision.action == RoutingAction.ACCEPT_T1
    assert decision.next_tier == "NONE"
    assert decision.escalation_required is False


def test_case_2_low_risk_low_confidence(router):
    """Case 2: Low risk, low T1 confidence (< 0.70) -> ESCALATE_T2 for independent verification."""
    decision = router.route_t1_result(
        task_text="Refactor complex regex logic in parser.py",
        complexity="STANDARD",
        confidence=0.52,
        risk_score=0.20,
        tool_name="write_file",
        verification_result="PASSED"
    )
    assert decision.action == RoutingAction.ESCALATE_T2
    assert decision.next_tier == "T2"
    assert decision.escalation_required is True


def test_case_3_high_risk_high_confidence(router):
    """Case 3: High risk destructive command (> 0.90 risk) -> FAIL_SAFE / confirmation required."""
    decision = router.route_t1_result(
        task_text="Force clean git repository and delete uncommitted files",
        complexity="COMPLEX",
        confidence=0.95,
        risk_score=0.92,
        tool_name="delete_file",
        verification_result="PASSED"
    )
    assert decision.action == RoutingAction.FAIL_SAFE
    assert decision.next_tier == "NONE"


def test_case_4_high_risk_low_confidence(router):
    """Case 4: High risk, low confidence -> FAIL_SAFE / confirmation."""
    decision = router.route_t1_result(
        task_text="Execute raw shell script to drop database table",
        complexity="COMPLEX",
        confidence=0.45,
        risk_score=0.95,
        tool_name="execute_command",
        verification_result="PASSED"
    )
    assert decision.action == RoutingAction.FAIL_SAFE


def test_case_5_t1_t2_agreement(router):
    """Case 5: T1 and T2 agree with 0 issues -> ACCEPT_T2 (Complete, No T3 call)."""
    decision = router.route_t2_result(
        t2_agree=True,
        t2_issues=[],
        t2_confidence=0.90,
        risk_score=0.25
    )
    assert decision.action == RoutingAction.ACCEPT_T2
    assert decision.next_tier == "NONE"
    assert decision.escalation_required is False


def test_case_6_t1_t2_disagreement(router):
    """Case 6: T1 and T2 disagree -> ESCALATE_T3 for cloud arbitration under $25 cap."""
    decision = router.route_t2_result(
        t2_agree=False,
        t2_issues=["T1 logic introduces off-by-one boundary error in pagination loop"],
        t2_confidence=0.80,
        risk_score=0.40
    )
    assert decision.action == RoutingAction.ESCALATE_T3
    assert decision.next_tier == "T3"
    assert decision.escalation_required is True


def test_case_7_t2_unavailable_fallback(router):
    """Case 7: T2 unavailable -> Safe fallback to local verified result."""
    decision = router.route_t1_result(
        task_text="Update docstring",
        confidence=0.65,
        risk_score=0.20,
        verification_result="PASSED",
        t2_available=False
    )
    assert decision.action == RoutingAction.ACCEPT_T1
    assert decision.next_tier == "NONE"


def test_case_8_t3_unavailable_fallback(router):
    """Case 8: T3 unavailable / cost cap reached -> Safe FAIL_SAFE fallback."""
    decision = router.route_t2_result(
        t2_agree=False,
        t2_issues=["Syntax defect"],
        t3_available=False
    )
    assert decision.action == RoutingAction.FAIL_SAFE
    assert decision.next_tier == "NONE"


def test_case_9_t1_transient_failure(router):
    """Case 9: First verification failure -> RETRY_T1."""
    decision = router.route_t1_result(
        task_text="Implement feature",
        attempt_count=1,
        verification_result="FAILED"
    )
    assert decision.action == RoutingAction.RETRY_T1
    assert decision.next_tier == "T1"


def test_case_10_t1_repeated_failure(router):
    """Case 10: Repeated failure (attempt > 2) -> ESCALATE_T2."""
    decision = router.route_t1_result(
        task_text="Implement feature",
        attempt_count=3,
        verification_result="PASSED"
    )
    assert decision.action == RoutingAction.ESCALATE_T2
    assert decision.next_tier == "T2"


def test_case_11_verification_failure_after_retries(router):
    """Case 11: Verification failed after multiple attempts -> ESCALATE_T2."""
    decision = router.route_t1_result(
        task_text="Implement feature",
        attempt_count=2,
        verification_result="FAILED"
    )
    assert decision.action == RoutingAction.ESCALATE_T2
    assert decision.next_tier == "T2"


def test_case_12_read_only_deterministic_task(router):
    """Case 12: Read-only tool execution -> ACCEPT_T1 directly (0 T2/T3 calls)."""
    decision = router.route_t1_result(
        task_text="Read project README.md",
        tool_name="read_file",
        confidence=0.75,
        risk_score=0.05,
        verification_result="PASSED"
    )
    assert decision.action == RoutingAction.ACCEPT_T1
    assert decision.next_tier == "NONE"
    assert decision.decision_latency_ms < 1.0  # Sub-millisecond evaluation!
