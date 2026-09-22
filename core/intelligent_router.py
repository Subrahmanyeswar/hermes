# core/intelligent_router.py
"""
Intelligent Model Routing Engine for HERMES vNext (Phase 11).
Decides when Tier 1 (DeepSeek-R1) should be trusted directly,
when Tier 2 (Qwen3) should conditionally verify, and
when Tier 3 (Ox Alpha) should arbitrate.
T2 and T3 are escalation mechanisms, NOT mandatory pipeline stages.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple

from loguru import logger
from config.model_config import (
    INTELLIGENT_ROUTING_ENABLED,
    T2_CONFIDENCE_THRESHOLD,
    HIGH_RISK_THRESHOLD
)

READ_ONLY_TOOLS = frozenset({
    "read_file",
    "list_directory",
    "file_exists",
    "grep_search",
    "find_by_name",
    "read_url_content",
    "get_symbols",
})

HIGH_RISK_TOOLS = frozenset({
    "delete_file",
    "git_push",
    "git_reset",
    "execute_command",
    "install_package",
})


class RoutingAction(str, Enum):
    ACCEPT_T1 = "ACCEPT_T1"       # T1 trusted directly; bypass T2 and T3
    VERIFY_T1 = "VERIFY_T1"       # Deterministic verification required (AST / schema)
    ESCALATE_T2 = "ESCALATE_T2"   # Escalate to Tier 2 (Qwen3) for independent verification
    ACCEPT_T2 = "ACCEPT_T2"       # T2 agrees with T1; complete without T3
    ESCALATE_T3 = "ESCALATE_T3"   # T1/T2 disagreement; escalate to Tier 3 (Ox Alpha)
    RETRY_T1 = "RETRY_T1"         # Transient failure; retry with T1
    FAIL_SAFE = "FAIL_SAFE"       # Dangerous operation; require manual user confirmation


@dataclass
class RoutingDecision:
    action: RoutingAction
    next_tier: str                # "T1", "T2", "T3", "NONE"
    confidence: float
    risk_score: float
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    escalation_required: bool = False
    verification_required: bool = False
    retry_allowed: bool = True
    decision_latency_ms: float = 0.0


class IntelligentRouter:
    """
    Centralized, multi-signal, deterministic routing engine.
    Executes in <0.05ms without calling a second LLM.
    """

    def __init__(
        self,
        enabled: bool = INTELLIGENT_ROUTING_ENABLED,
        t2_confidence_threshold: float = T2_CONFIDENCE_THRESHOLD,
        high_risk_threshold: float = HIGH_RISK_THRESHOLD
    ):
        self.enabled = enabled
        self.t2_confidence_threshold = t2_confidence_threshold
        self.high_risk_threshold = high_risk_threshold

    def route_t1_result(
        self,
        task_text: str,
        complexity: str = "STANDARD",
        confidence: float = 0.85,
        risk_score: float = 0.20,
        tool_name: str = "read_file",
        verification_result: str = "PASSED",
        attempt_count: int = 1,
        t2_available: bool = True
    ) -> RoutingDecision:
        """
        Evaluate T1 outcome and decide next action:
        - Direct acceptance
        - Deterministic repair
        - Conditional Tier 2 escalation
        - Hard fail-safe / confirmation
        """
        start_time = time.perf_counter()

        if not self.enabled:
            # Fallback legacy routing: always escalate to T2
            return RoutingDecision(
                action=RoutingAction.ESCALATE_T2,
                next_tier="T2",
                confidence=confidence,
                risk_score=risk_score,
                reason="Legacy routing: mandatory Tier 2 pipeline",
                escalation_required=True,
                decision_latency_ms=(time.perf_counter() - start_time) * 1000.0
            )

        # 1. Hard Fail-Safe (Risk >= 0.90 or destructive tool without confirmation)
        if risk_score >= 0.90 or (tool_name in HIGH_RISK_TOOLS and risk_score >= self.high_risk_threshold):
            dur = (time.perf_counter() - start_time) * 1000.0
            return RoutingDecision(
                action=RoutingAction.FAIL_SAFE,
                next_tier="NONE",
                confidence=confidence,
                risk_score=risk_score,
                reason=f"High risk operation (risk={risk_score:.2f}, tool='{tool_name}') requires explicit confirmation",
                escalation_required=False,
                decision_latency_ms=dur
            )

        # 2. Repeated Failures (Attempt count > 2)
        if attempt_count > 2:
            if not t2_available:
                dur = (time.perf_counter() - start_time) * 1000.0
                return RoutingDecision(
                    action=RoutingAction.FAIL_SAFE,
                    next_tier="NONE",
                    confidence=confidence,
                    risk_score=risk_score,
                    reason="Repeated failures and T2 is unavailable; halting safely",
                    escalation_required=False,
                    decision_latency_ms=dur
                )
            dur = (time.perf_counter() - start_time) * 1000.0
            return RoutingDecision(
                action=RoutingAction.ESCALATE_T2,
                next_tier="T2",
                confidence=confidence,
                risk_score=risk_score,
                reason=f"Repeated T1 attempts ({attempt_count}); escalating to T2 for independent verification",
                escalation_required=True,
                decision_latency_ms=dur
            )

        # 3. Simple Read-Only Tools (Cheapest routing)
        if tool_name in READ_ONLY_TOOLS and verification_result != "FAILED":
            dur = (time.perf_counter() - start_time) * 1000.0
            return RoutingDecision(
                action=RoutingAction.ACCEPT_T1,
                next_tier="NONE",
                confidence=confidence,
                risk_score=risk_score,
                reason=f"Read-only tool '{tool_name}' verified safe; bypassing T2 and T3",
                escalation_required=False,
                decision_latency_ms=dur
            )

        # 4. Verification Failed
        if verification_result == "FAILED":
            dur = (time.perf_counter() - start_time) * 1000.0
            if attempt_count < 2:
                return RoutingDecision(
                    action=RoutingAction.RETRY_T1,
                    next_tier="T1",
                    confidence=confidence,
                    risk_score=risk_score,
                    reason="Verification failed; retrying with T1 repair",
                    escalation_required=False,
                    retry_allowed=True,
                    decision_latency_ms=dur
                )
            else:
                return RoutingDecision(
                    action=RoutingAction.ESCALATE_T2,
                    next_tier="T2",
                    confidence=confidence,
                    risk_score=risk_score,
                    reason="Verification failed after retries; escalating to T2",
                    escalation_required=True,
                    decision_latency_ms=dur
                )

        # 5. High Confidence + Low Risk + Verification PASSED -> Direct Acceptance (Bypass T2!)
        if (
            confidence >= self.t2_confidence_threshold
            and risk_score < self.high_risk_threshold
            and verification_result == "PASSED"
        ):
            dur = (time.perf_counter() - start_time) * 1000.0
            return RoutingDecision(
                action=RoutingAction.ACCEPT_T1,
                next_tier="NONE",
                confidence=confidence,
                risk_score=risk_score,
                reason=f"High confidence ({confidence:.2f} >= {self.t2_confidence_threshold}) and low risk ({risk_score:.2f} < {self.high_risk_threshold}) with verified result; bypassing T2 and T3",
                escalation_required=False,
                decision_latency_ms=dur
            )

        # 6. Low Confidence or Elevated Risk -> Escalate to T2
        dur = (time.perf_counter() - start_time) * 1000.0
        if not t2_available:
            # Fallback when T2 is offline
            return RoutingDecision(
                action=RoutingAction.ACCEPT_T1 if verification_result == "PASSED" else RoutingAction.FAIL_SAFE,
                next_tier="NONE",
                confidence=confidence,
                risk_score=risk_score,
                reason="T2 verifier unavailable; falling back to local deterministic verification verdict",
                escalation_required=False,
                decision_latency_ms=dur
            )

        return RoutingDecision(
            action=RoutingAction.ESCALATE_T2,
            next_tier="T2",
            confidence=confidence,
            risk_score=risk_score,
            reason=f"Elevated risk ({risk_score:.2f}) or low confidence ({confidence:.2f} < {self.t2_confidence_threshold}); escalating to T2",
            escalation_required=True,
            decision_latency_ms=dur
        )

    def route_t2_result(
        self,
        t2_agree: bool,
        t2_issues: List[str],
        t2_confidence: float = 0.85,
        risk_score: float = 0.20,
        t3_available: bool = True,
        t3_cost_cap_reached: bool = False
    ) -> RoutingDecision:
        """
        Evaluate T2 verification result:
        - If T1 and T2 agree: ACCEPT_T2 (Complete, no T3!)
        - If T1 and T2 disagree: ESCALATE_T3 (Cloud arbitration under $25 cap)
        """
        start_time = time.perf_counter()

        if t2_agree and not t2_issues:
            dur = (time.perf_counter() - start_time) * 1000.0
            return RoutingDecision(
                action=RoutingAction.ACCEPT_T2,
                next_tier="NONE",
                confidence=t2_confidence,
                risk_score=risk_score,
                reason="Tier 1 and Tier 2 in agreement with 0 critical issues; completing mission without Tier 3",
                escalation_required=False,
                decision_latency_ms=dur
            )

        # Disagreement or critical issues found
        if not t3_available or t3_cost_cap_reached:
            dur = (time.perf_counter() - start_time) * 1000.0
            return RoutingDecision(
                action=RoutingAction.FAIL_SAFE,
                next_tier="NONE",
                confidence=t2_confidence,
                risk_score=risk_score,
                reason="Tier 1/2 disagreement but Tier 3 is unavailable or $25 budget cap reached; halting safely",
                escalation_required=False,
                decision_latency_ms=dur
            )

        dur = (time.perf_counter() - start_time) * 1000.0
        return RoutingDecision(
            action=RoutingAction.ESCALATE_T3,
            next_tier="T3",
            confidence=t2_confidence,
            risk_score=risk_score,
            reason=f"Tier 2 disagreed or reported {len(t2_issues)} critical issue(s); escalating to Tier 3 for arbitration",
            escalation_required=True,
            decision_latency_ms=dur
        )


# Global singleton instance
intelligent_router = IntelligentRouter()
