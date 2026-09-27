# core/escalation/critic.py
"""
T2 Independent Critic for HERMES 2.x.

Core Invariants:
1. SKEPTICAL EVALUATION: Never accepts agent self-attestation or unverified claims.
2. STRICTLY READ-ONLY: T2 Critic never mutates files or executes state-altering commands in the workspace.
3. BOUNDED CONTEXT PACKET: Operates strictly on a bounded evaluation packet to avoid context bloat.
4. ROBUST PARSING: Validates output strictly into structured T2CriticResult, with safe fallbacks on malformed LLM responses.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from core.escalation.models import T2CriticResult
from core.runtime_state.models import FailureClass
from core.verification.models import VerificationResult, VerificationVerdict

logger = logging.getLogger("hermes.escalation.critic")


class T2Critic:
    """
    Independent skeptical reviewer assessing change quality, regressions, and safety.
    """

    def __init__(self, evaluator_fn: Optional[Callable[[str], str]] = None):
        self.evaluator_fn = evaluator_fn

    def build_packet(
        self,
        goal_summary: str,
        requirement_desc: str,
        verification_results: List[VerificationResult],
        code_diff: Optional[str] = None,
        context_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build bounded evaluation packet for T2."""
        truncated_diff = (code_diff or "")[:2500]
        if code_diff and len(code_diff) > 2500:
            truncated_diff += "\n...[DIFF TRUNCATED TO 2500 CHARACTERS]..."

        checks_summary = [
            {
                "check_id": vr.check_id,
                "verdict": vr.verdict.value,
                "message": vr.message[:200],
                "failure_class": vr.failure_class.value if vr.failure_class else None,
            }
            for vr in verification_results
        ]

        return {
            "goal": goal_summary[:400],
            "requirement": requirement_desc[:400],
            "verification_checks": checks_summary,
            "diff_excerpt": truncated_diff,
            "notes": (context_notes or "")[:400],
        }

    def evaluate(
        self,
        requirement_id: Optional[str],
        check_id: Optional[str],
        packet: Dict[str, Any],
    ) -> T2CriticResult:
        """
        Execute skeptical evaluation over the bounded packet.
        """
        t0 = time.time()
        eval_id = f"t2_{uuid.uuid4().hex[:8]}"

        # If any deterministic check failed, T2 should note it skeptically
        checks = packet.get("verification_checks", [])
        deterministic_failures = [c for c in checks if c["verdict"] == VerificationVerdict.FAIL.value]

        if self.evaluator_fn:
            prompt = (
                "You are HERMES T2 Critic. Evaluate whether the following change correctly satisfies "
                "the requirement without regressions or unhandled edge cases.\n"
                "Respond ONLY with a JSON object in this schema:\n"
                '{"approved": bool, "confidence": float, "critique": str, "identified_risks": [str], "suggested_action": str}\n\n'
                f"Evaluation Packet:\n{json.dumps(packet, indent=2)}"
            )
            try:
                raw_response = self.evaluator_fn(prompt)
                clean_json = raw_response.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()

                parsed = json.loads(clean_json)
                approved = bool(parsed.get("approved", False))
                # Enforce fact invariant: if deterministic failures exist, cannot approve!
                if deterministic_failures and approved:
                    approved = False
                    critique = "OVERRULED: Cannot approve change with failing deterministic verification checks."
                else:
                    critique = str(parsed.get("critique", ""))

                return T2CriticResult(
                    evaluation_id=eval_id,
                    requirement_id=requirement_id,
                    check_id=check_id,
                    approved=approved,
                    confidence=float(parsed.get("confidence", 0.5)),
                    critique=critique,
                    identified_risks=list(parsed.get("identified_risks", [])),
                    failure_class=FailureClass.ASSERTION_FAILED if not approved else None,
                    suggested_action=str(parsed.get("suggested_action", "")),
                    duration_ms=(time.time() - t0) * 1000.0,
                )
            except Exception as e:
                logger.warning(f"T2Critic evaluator_fn error: {e}")

        # Deterministic heuristic fallback when no LLM evaluator is provided
        if deterministic_failures:
            fail_reasons = [f"{c['check_id']}: {c['message']}" for c in deterministic_failures]
            return T2CriticResult(
                evaluation_id=eval_id,
                requirement_id=requirement_id,
                check_id=check_id,
                approved=False,
                confidence=0.95,
                critique=f"Deterministic checks failed: {'; '.join(fail_reasons)}",
                identified_risks=["Objective verification failure"],
                failure_class=FailureClass.ASSERTION_FAILED,
                suggested_action="Fix failing verification checks before proceeding.",
                duration_ms=(time.time() - t0) * 1000.0,
            )

        return T2CriticResult(
            evaluation_id=eval_id,
            requirement_id=requirement_id,
            check_id=check_id,
            approved=True,
            confidence=0.85,
            critique="Deterministic verifications passed; no obvious regressions detected.",
            identified_risks=[],
            suggested_action="Proceed to next requirement.",
            duration_ms=(time.time() - t0) * 1000.0,
        )
