# core/escalation/judge.py
"""
T3 Supreme Judge for HERMES 2.x.

Core Invariants:
1. FACT INVARIANT: T3 Judge CANNOT override failed objective facts (failing tests, missing files, broken AST).
2. WORKSPACE CONFINEMENT: T3 Judge is strictly read-only and never mutates workspace files.
3. BOUNDED ARBITRATION: Operates on a compact summary of the dispute, evidence, and critic opinions.
4. BINDING DIRECTIVES: Issues authoritative resolution decisions (APPROVE, REJECT, ESCALATE_TO_USER).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from core.escalation.models import T3JudgeResult
from core.runtime_state.models import DisagreementClass, EscalationDecisionType
from core.verification.models import VerificationResult, VerificationVerdict

logger = logging.getLogger("hermes.escalation.judge")


class T3Judge:
    """
    Authoritative final arbiter for high-risk disputes, persistent disagreements, or stalled repairs.
    """

    def __init__(self, arbiter_fn: Optional[Callable[[str], str]] = None):
        self.arbiter_fn = arbiter_fn

    def arbitrate(
        self,
        requirement_id: Optional[str],
        check_id: Optional[str],
        dispute_summary: str,
        verification_results: List[VerificationResult],
        t2_critique: Optional[str] = None,
        is_critical_requirement: bool = True,
    ) -> T3JudgeResult:
        """
        Deliver a binding judgment on a contested verification or escalation.
        """
        t0 = time.time()
        judgment_id = f"t3_{uuid.uuid4().hex[:8]}"

        # Check for objective factual failures
        has_failed_facts = any(vr.verdict == VerificationVerdict.FAIL for vr in verification_results)

        if self.arbiter_fn:
            prompt = (
                "You are HERMES T3 Judge. Deliver a final, binding arbitration decision on this dispute.\n"
                "CRITICAL INVARIANT: You CANNOT approve or mark passed any requirement where objective verification failed.\n"
                "Respond ONLY with a JSON object in this schema:\n"
                '{"decision": "APPROVE"|"REJECT"|"ESCALATE_TO_USER", "rationale": str, "binding_directives": [str]}\n\n'
                f"Dispute: {dispute_summary}\n"
                f"T2 Critique: {t2_critique or 'None'}\n"
                f"Has Failed Deterministic Facts: {has_failed_facts}\n"
                f"Is Critical Requirement: {is_critical_requirement}"
            )
            try:
                raw_response = self.arbiter_fn(prompt)
                clean_json = raw_response.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()

                parsed = json.loads(clean_json)
                decision_str = str(parsed.get("decision", "REJECT")).upper()
                rationale = str(parsed.get("rationale", ""))
                directives = list(parsed.get("binding_directives", []))

                # ENFORCE FACT INVARIANT:
                # If facts failed and model attempted to APPROVE, strictly override to REJECT
                if has_failed_facts and decision_str == EscalationDecisionType.APPROVE.value:
                    decision = EscalationDecisionType.REJECT
                    rationale = f"OVERRULED BY FACT INVARIANT: T3 Judge cannot approve when objective facts failed. Original rationale: {rationale}"
                    directives.append("Deterministic facts failed; must be repaired by T1.")
                else:
                    decision = EscalationDecisionType(decision_str) if decision_str in EscalationDecisionType._value2member_map_ else EscalationDecisionType.REJECT

                return T3JudgeResult(
                    judgment_id=judgment_id,
                    requirement_id=requirement_id,
                    decision=decision,
                    rationale=rationale,
                    binding_directives=directives,
                    fact_invariant_checked=True,
                    disagreement_class=DisagreementClass.EVIDENCE_INTERPRETATION if t2_critique else None,
                    duration_ms=(time.time() - t0) * 1000.0,
                )
            except Exception as e:
                logger.warning(f"T3Judge arbiter_fn error: {e}")

        # Deterministic heuristic arbitration
        if has_failed_facts:
            # Cannot approve failed facts
            return T3JudgeResult(
                judgment_id=judgment_id,
                requirement_id=requirement_id,
                decision=EscalationDecisionType.REJECT,
                rationale="Binding rejection: Objective verification checks failed. T3 Fact Invariant forbids approving failed evidence.",
                binding_directives=["T1 must repair the failing checks before approval."],
                fact_invariant_checked=True,
                disagreement_class=DisagreementClass.EVIDENCE_INTERPRETATION,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        if t2_critique and "OVERRULED" in t2_critique:
            return T3JudgeResult(
                judgment_id=judgment_id,
                requirement_id=requirement_id,
                decision=EscalationDecisionType.REJECT,
                rationale="Binding rejection upholding T2 Critic's objection.",
                binding_directives=["Address T2 Critic objections."],
                fact_invariant_checked=True,
                duration_ms=(time.time() - t0) * 1000.0,
            )

        return T3JudgeResult(
            judgment_id=judgment_id,
            requirement_id=requirement_id,
            decision=EscalationDecisionType.APPROVE,
            rationale="Objective evidence passed and no persistent disqualifying risk identified.",
            binding_directives=["Requirement approved. Continue execution."],
            fact_invariant_checked=True,
            duration_ms=(time.time() - t0) * 1000.0,
        )
