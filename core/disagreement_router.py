# core/disagreement_router.py
# The HERMES Disagreement Router — the core of Speculative Disagreement Routing.
# Reads the VerificationResult from Tier 2 and makes one of three decisions:
#   ACCEPT: T1 and T2 agree with high confidence — proceed with T1's tool call
#   ESCALATE: T1 and T2 disagree, or confidence is low — call Tier 3
#   BLOCK: The action is too dangerous even for Tier 3 — user confirmation required
#
# This is a deterministic, pure-logic component. No LLM calls. No randomness.
# Every routing decision is logged with the exact reason.

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from loguru import logger

from core.verifier import VerificationResult


# ──────────────────────────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────────────────────────

class RoutingDecision(Enum):
    """The three possible outcomes of the disagreement router."""
    ACCEPT = "accept"       # T1 and T2 agree — proceed with T1's tool call
    ESCALATE = "escalate"   # T2 has concerns — call Tier 3 to arbitrate
    BLOCK = "block"         # Too dangerous — require explicit user confirmation


@dataclass
class RouterResult:
    """The complete output of the disagreement router."""
    decision: RoutingDecision
    reason: str                              # Human-readable explanation of the decision
    confidence_threshold_used: float = 0.72  # The threshold that was applied
    tier3_needed: bool = False              # True if Tier 3 call should follow
    requires_user_confirm: bool = False     # True if user must explicitly approve

    def summary(self) -> str:
        return (
            f"decision={self.decision.value} | "
            f"tier3={self.tier3_needed} | "
            f"user_confirm={self.requires_user_confirm} | "
            f"reason={self.reason[:80]}"
        )


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

CONFIDENCE_THRESHOLD: float = 0.72       # Below this -> escalate
HARD_BLOCK_RISK_THRESHOLD: float = 0.9   # Above this -> block entirely (require user)
ESCALATE_RISK_THRESHOLD: float = 0.7     # Above this -> escalate to Tier 3

# Tools that always require escalation regardless of confidence
ALWAYS_ESCALATE_TOOLS: frozenset[str] = frozenset({
    "git_push",
    "github_create_repo",
    "delete_file",
    "install_package",
})

# Tools that always require user confirmation regardless of routing decision
ALWAYS_CONFIRM_TOOLS: frozenset[str] = frozenset({
    "git_push",
    "delete_file",
})


def load_calibrated_threshold(results_path: str = "data/threshold_calibration_results.json") -> float:
    """
    Load the recommended confidence threshold from the calibration results file.
    Falls back to the default CONFIDENCE_THRESHOLD if the file does not exist.
    Call this at application startup to use the data-driven threshold.
    
    Usage in main.py or orchestrator startup:
        from core.disagreement_router import load_calibrated_threshold
        threshold = load_calibrated_threshold()
        router = DisagreementRouter(confidence_threshold=threshold)
    """
    import json
    from pathlib import Path
    
    path = Path(results_path)
    if not path.exists():
        logger.debug(
            f"Calibration results not found at {path}. "
            f"Using default threshold: {CONFIDENCE_THRESHOLD}"
        )
        return CONFIDENCE_THRESHOLD
    
    try:
        with open(path) as f:
            data = json.load(f)
        recommended = float(data.get("recommended_threshold", CONFIDENCE_THRESHOLD))
        logger.info(
            f"Loaded calibrated threshold: {recommended} "
            f"(from {path})"
        )
        return recommended
    except (json.JSONDecodeError, KeyError, ValueError, IOError) as e:
        logger.warning(
            f"Could not load calibrated threshold from {path}: {e}. "
            f"Using default: {CONFIDENCE_THRESHOLD}"
        )
        return CONFIDENCE_THRESHOLD


# ──────────────────────────────────────────────────────────────────────
# Disagreement Router
# ──────────────────────────────────────────────────────────────────────

class DisagreementRouter:
    """
    Deterministic routing engine for Speculative Disagreement Routing.
    Reads VerificationResult from Tier 2 and decides: ACCEPT, ESCALATE, or BLOCK.
    Pure logic — no LLM calls, no randomness, no async.
    """

    def __init__(self, confidence_threshold: float = CONFIDENCE_THRESHOLD):
        self.confidence_threshold = confidence_threshold
        self.accept_count = 0
        self.escalate_count = 0
        self.block_count = 0

    def route(
        self,
        verification: VerificationResult,
        tool_name: str,
        mode: str = "auto"
    ) -> RouterResult:
        """
        Make a routing decision based on verification result.
        Pure logic — no async, no LLM calls.

        Checks are evaluated in strict priority order:
        1. Hard block (risk >= 0.9)
        2. Always-escalate tools
        3. T2 explicitly disagrees
        4. Critical issues present
        5. Low confidence
        6. Elevated risk score
        7. Default: ACCEPT
        """

        # ── Check 1: Hard block (risk too high for autonomous execution) ──
        if verification.risk_score >= HARD_BLOCK_RISK_THRESHOLD:
            self.block_count += 1
            result = RouterResult(
                decision=RoutingDecision.BLOCK,
                reason=f"Risk score {verification.risk_score:.2f} exceeds hard block threshold {HARD_BLOCK_RISK_THRESHOLD}",
                tier3_needed=False,
                requires_user_confirm=True
            )
            logger.warning(f"Router: BLOCK | tool={tool_name} | {result.summary()}")
            return result

        # ── Check 2: Always-escalate tools ────────────────────────────────
        if tool_name in ALWAYS_ESCALATE_TOOLS:
            self.escalate_count += 1
            result = RouterResult(
                decision=RoutingDecision.ESCALATE,
                reason=f"Tool '{tool_name}' always requires Tier 3 review",
                tier3_needed=True,
                requires_user_confirm=tool_name in ALWAYS_CONFIRM_TOOLS
            )
            logger.info(f"Router: ESCALATE (always-escalate tool) | tool={tool_name} | {result.summary()}")
            return result

        # ── Check 3: T2 explicitly disagrees ──────────────────────────────
        if not verification.agree:
            issues_str = (
                "; ".join(verification.critical_issues[:3])
                if verification.critical_issues
                else "no specific issues given"
            )
            self.escalate_count += 1
            result = RouterResult(
                decision=RoutingDecision.ESCALATE,
                reason=f"Tier 2 disagreed: {issues_str}",
                tier3_needed=True,
                requires_user_confirm=False
            )
            logger.info(f"Router: ESCALATE (T2 disagreed) | tool={tool_name} | {result.summary()}")
            return result

        # ── Check 4: Critical issues even if agree=True ───────────────────
        if verification.critical_issues:
            self.escalate_count += 1
            result = RouterResult(
                decision=RoutingDecision.ESCALATE,
                reason=f"Tier 2 found {len(verification.critical_issues)} critical issue(s) despite agreeing",
                tier3_needed=True,
                requires_user_confirm=False
            )
            logger.info(f"Router: ESCALATE (critical issues) | tool={tool_name} | {result.summary()}")
            return result

        # ── Check 5: Low confidence ───────────────────────────────────────
        if verification.confidence < self.confidence_threshold:
            self.escalate_count += 1
            result = RouterResult(
                decision=RoutingDecision.ESCALATE,
                reason=f"Tier 2 confidence {verification.confidence:.2f} is below threshold {self.confidence_threshold}",
                tier3_needed=True,
                requires_user_confirm=False
            )
            logger.info(f"Router: ESCALATE (low confidence) | tool={tool_name} | {result.summary()}")
            return result

        # ── Check 6: Elevated risk score (below hard block but above escalate) ─
        if verification.risk_score >= ESCALATE_RISK_THRESHOLD:
            self.escalate_count += 1
            result = RouterResult(
                decision=RoutingDecision.ESCALATE,
                reason=f"Risk score {verification.risk_score:.2f} exceeds escalation threshold {ESCALATE_RISK_THRESHOLD}",
                tier3_needed=True,
                requires_user_confirm=False
            )
            logger.info(f"Router: ESCALATE (elevated risk) | tool={tool_name} | {result.summary()}")
            return result

        # ── Default: ACCEPT ───────────────────────────────────────────────
        self.accept_count += 1
        result = RouterResult(
            decision=RoutingDecision.ACCEPT,
            reason=f"T2 agrees with confidence {verification.confidence:.2f} and risk {verification.risk_score:.2f}",
            tier3_needed=False,
            requires_user_confirm=False
        )
        logger.debug(f"Router: ACCEPT | tool={tool_name} | {result.summary()}")
        return result

    async def try_alternative_before_escalation(
        self,
        original_task: str,
        original_tool_call: dict,
        verification_result: "VerificationResult",
        ollama_client: "OllamaClient",
        system_prompt: str,
    ) -> Optional[dict]:
        """
        ToT/LATS insight (controlled): Before escalating to T3,
        generate one alternative approach and have T2 score it.
        If the alternative scores higher, use it instead of escalating.

        This avoids T3 cost when the task has a simpler working solution.

        Args:
            original_task:         The user's task description
            original_tool_call:    T1's first tool call attempt
            verification_result:   T2's assessment (which said DISAGREE)
            ollama_client:         Ollama client for T1 re-generation
            system_prompt:         The existing system prompt for T1

        Returns:
            Alternative tool call dict if one scores higher, else None
        """
        from core.response_parser import ResponseParser, ParseSuccess

        logger.info(
            "DisagreementRouter: T2 disagrees — trying alternative "
            "approach before T3 escalation"
        )

        # Build alternative-seeking prompt
        issues = "; ".join(verification_result.critical_issues[:3])
        alt_prompt = (
            f"ALTERNATIVE APPROACH REQUIRED\n\n"
            f"Task: {original_task}\n\n"
            f"Previous approach was: {original_tool_call.get('tool', 'unknown')}\n"
            f"T2 found issues: {issues}\n"
            f"Quality verdict: {verification_result.quality_verdict}\n\n"
            f"Generate a DIFFERENT approach to accomplish this task.\n"
            f"Address the specific issues found.\n"
            f"Choose a different tool or different parameters."
        )

        try:
            # Generate alternative with T1
            alt_response = await ollama_client.generate(
                model="qwen2.5-coder:7b",
                prompt=alt_prompt,
                system=system_prompt,
                keep_alive=0,
                temperature=0.25,   # Slightly higher for exploration
                num_ctx=4096,
            )

            # Parse alternative tool call
            parser = ResponseParser()
            parsed_alt = parser.parse(alt_response)

            if not isinstance(parsed_alt, ParseSuccess):
                logger.debug("DisagreementRouter: alternative parse failed")
                return None

            alt_tool_call = {
                "tool": parsed_alt.tool,
                "parameters": parsed_alt.parameters,
                "reasoning": getattr(parsed_alt, "reasoning", ""),
            }

            # Have T2 score the alternative by comparing both approaches
            alt_assessment_prompt = (
                f"Compare these two approaches for: {original_task}\n\n"
                f"Approach A (original, had issues: {issues}):\n"
                f"Tool: {original_tool_call.get('tool')}\n"
                f"Params: {str(original_tool_call.get('parameters', {}))[:200]}\n\n"
                f"Approach B (alternative):\n"
                f"Tool: {parsed_alt.tool}\n"
                f"Params: {str(parsed_alt.parameters)[:200]}\n\n"
                f"Which approach better addresses the task?\n"
                f"Respond with only: 'A' or 'B' and one sentence why."
            )

            choice_response = await ollama_client.generate(
                model="mistral:7b-instruct",
                prompt=alt_assessment_prompt,
                system=(
                    "You are a code review expert. "
                    "Evaluate which approach is better. "
                    "Respond with only A or B and one sentence."
                ),
                keep_alive=0,
                temperature=0.1,
                num_ctx=2048,
            )

            if choice_response.strip().upper().startswith("B"):
                logger.info(
                    f"DisagreementRouter: alternative approach chosen — "
                    f"tool={parsed_alt.tool} — T3 escalation avoided"
                )
                return alt_tool_call
            else:
                logger.info(
                    "DisagreementRouter: alternative scored worse — "
                    "proceeding with T3 escalation"
                )
                return None

        except Exception as e:
            logger.warning(f"DisagreementRouter.try_alternative: {e}")
            return None

    def get_stats(self) -> dict:
        """Returns routing statistics."""
        total = self.accept_count + self.escalate_count + self.block_count
        return {
            "accept": self.accept_count,
            "escalate": self.escalate_count,
            "block": self.block_count,
            "total": total,
            "accept_rate": self.accept_count / max(1, total),
        }

    def calibrate_threshold(self, new_threshold: float) -> None:
        """Adjust the confidence threshold for escalation decisions."""
        old = self.confidence_threshold
        self.confidence_threshold = max(0.0, min(1.0, new_threshold))
        logger.info(f"Router: confidence threshold changed from {old} to {self.confidence_threshold}")
