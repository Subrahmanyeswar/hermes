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
from typing import Optional, Any

from loguru import logger

from core.verifier import VerificationResult
from config.model_config import TIER1_MODEL, TIER2_MODEL, MODEL_KEEP_ALIVE


# ──────────────────────────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────────────────────────

class RoutingDecision(Enum):
    """The three possible outcomes of the disagreement router."""
    ACCEPT = "accept"       # T1 and T2 agree — proceed with T1's tool call
    ESCALATE = "escalate"   # T2 has concerns — call Tier 3 to arbitrate
    BLOCK = "block"         # Too dangerous — require explicit user confirmation


class FailureCategory(Enum):
    """Granular failure classification ensuring only actual verification disagreements reach Tier 3."""
    TOOL_INFRASTRUCTURE_FAILURE = "TOOL_INFRASTRUCTURE_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    VERIFICATION_INFRASTRUCTURE_FAILURE = "VERIFICATION_INFRASTRUCTURE_FAILURE"
    APPLICATION_FAILURE = "APPLICATION_FAILURE"
    SYNTAX_FAILURE = "SYNTAX_FAILURE"
    ARGUMENT_FAILURE = "ARGUMENT_FAILURE"
    SECURITY_DENIAL = "SECURITY_DENIAL"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    PATH_FAILURE = "PATH_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    ACTUAL_VERIFICATION_MISMATCH = "ACTUAL_VERIFICATION_MISMATCH"


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

MAX_T3_PER_MISSION: int = 2
MAX_T3_PER_TASK: int = 1


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
        self.t3_fingerprints_seen: set[str] = set()
        self.t3_count_by_mission: dict[str, int] = {}
        self.t3_count_by_task: dict[str, int] = {}

    def classify_failure(self, tool_name: str, issues: list[str], error_message: str = "", reasoning: str = "") -> FailureCategory:
        """Classify failure into one of 11 explicit categories to determine T3 arbitrability."""
        combined = " ".join(issues + [error_message, reasoning]).lower()

        # Security & Permissions
        if any(w in combined for w in ("security:", "security denial", "forbidden", "permission denied")):
            return FailureCategory.SECURITY_DENIAL
        if any(w in combined for w in ("permission required", "needs confirmation", "user approval")):
            return FailureCategory.PERMISSION_REQUIRED

        # Path Failure
        if any(w in combined for w in ("outside workspace", "escapes workspace", "invalid path", "directory traversal")):
            return FailureCategory.PATH_FAILURE

        # Environment & System Missing
        if any(w in combined for w in (
            "missing npm", "command not found", "npm: command not found", "node: not found",
            "browser not installed", "playwright not installed", "exit_code=127", "no such executable"
        )):
            return FailureCategory.ENVIRONMENT_FAILURE

        # Tool Infrastructure Failure
        if any(w in combined for w in (
            "file not found", "no such file", "edit_target_not_found", "cannot find",
            "does not exist", "filenotfounderror", "cannot edit nonexistent", "stale_reason",
            "target file missing", "tool_infrastructure_failure", "infrastructure", "disk i/o", "ioerror", "oserror"
        )):
            return FailureCategory.TOOL_INFRASTRUCTURE_FAILURE

        # Provider Failure
        if any(w in combined for w in ("timeout", "timed out", "connectionerror", "503", "504", "rate limit", "overloaded")):
            return FailureCategory.PROVIDER_FAILURE

        # Argument / Input Failure
        if any(w in combined for w in ("invalid argument", "missing required", "expected_count_mismatch", "expected_occurrences")):
            return FailureCategory.ARGUMENT_FAILURE

        # Syntax Failure
        if any(w in combined for w in ("syntaxerror", "syntax error", "malformed json", "unbalanced")):
            return FailureCategory.SYNTAX_FAILURE

        # Verification Infrastructure
        if any(w in combined for w in ("verifier crashed", "test runner not found", "pytest: command not found")):
            return FailureCategory.VERIFICATION_INFRASTRUCTURE_FAILURE

        # Application Logic Failure
        if any(w in combined for w in ("assertionerror", "test failed", "unit test failure")):
            return FailureCategory.APPLICATION_FAILURE

        return FailureCategory.ACTUAL_VERIFICATION_MISMATCH

    def _is_infrastructure_error(self, issues: list[str], error_message: str = "", reasoning: str = "") -> bool:
        """Check if an error is pure infrastructure/filesystem and should not invoke Tier 3."""
        fail_cat = self.classify_failure("", issues, error_message, reasoning)
        return fail_cat in (
            FailureCategory.TOOL_INFRASTRUCTURE_FAILURE,
            FailureCategory.ENVIRONMENT_FAILURE,
            FailureCategory.PATH_FAILURE,
            FailureCategory.ARGUMENT_FAILURE,
            FailureCategory.SYNTAX_FAILURE,
            FailureCategory.PROVIDER_FAILURE,
            FailureCategory.VERIFICATION_INFRASTRUCTURE_FAILURE,
        )

    def route(
        self,
        verification: VerificationResult,
        tool_name: str,
        mode: str = "auto",
        task_id: str = "",
        mission_id: str = "",
        error_message: str = "",
    ) -> RouterResult:
        """
        Make a routing decision based on verification result.
        Pure logic — no async, no LLM calls.
        """
        import hashlib

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

        # Helper to filter and guard candidate escalations
        def _guarded_escalate(reason: str, requires_confirm: bool = False) -> RouterResult:
            issues = getattr(verification, "critical_issues", [])
            reasoning = getattr(verification, "reasoning", "")

            # 1. Quarantine non-arbitrable infrastructure categories from invoking Tier 3
            fail_cat = self.classify_failure(tool_name, issues, error_message, reasoning)
            if fail_cat in (
                FailureCategory.TOOL_INFRASTRUCTURE_FAILURE,
                FailureCategory.ENVIRONMENT_FAILURE,
                FailureCategory.PATH_FAILURE,
                FailureCategory.PROVIDER_FAILURE,
                FailureCategory.VERIFICATION_INFRASTRUCTURE_FAILURE,
            ):
                logger.info(f"Router: Escalation suppressed for {fail_cat.value} | tool={tool_name}")
                return RouterResult(
                    decision=RoutingDecision.ACCEPT,
                    reason=f"Failure categorized as {fail_cat.value}; quarantined from Tier 3 ({reason[:50]})",
                    tier3_needed=False,
                    requires_user_confirm=False,
                )

            # 2. Fingerprint bounding (max 1 T3 call per failure fingerprint per task)
            if task_id:
                issues_str = "; ".join(issues[:2])
                fp_key = f"{task_id}:{tool_name}:{fail_cat.value}:{issues_str[:80]}"
                fingerprint = hashlib.sha256(fp_key.encode("utf-8")).hexdigest()
                if fingerprint in self.t3_fingerprints_seen:
                    logger.info(f"Router: Escalation suppressed — duplicate failure fingerprint {fingerprint[:8]}")
                    return RouterResult(
                        decision=RoutingDecision.ACCEPT,
                        reason="Escalation suppressed: failure fingerprint already arbitrated by Tier 3",
                        tier3_needed=False,
                        requires_user_confirm=False,
                    )
                self.t3_fingerprints_seen.add(fingerprint)

            # 3. Mission budget check
            if mission_id and self.t3_count_by_mission.get(mission_id, 0) >= MAX_T3_PER_MISSION:
                logger.warning(f"Router: Escalation suppressed — mission T3 budget ({MAX_T3_PER_MISSION}) exhausted")
                return RouterResult(
                    decision=RoutingDecision.ACCEPT,
                    reason=f"Tier 3 budget limit reached for mission (max {MAX_T3_PER_MISSION})",
                    tier3_needed=False,
                    requires_user_confirm=False,
                )

            # 4. Task budget check
            if task_id and self.t3_count_by_task.get(task_id, 0) >= MAX_T3_PER_TASK:
                logger.warning(f"Router: Escalation suppressed — task T3 budget ({MAX_T3_PER_TASK}) exhausted")
                return RouterResult(
                    decision=RoutingDecision.ACCEPT,
                    reason=f"Tier 3 budget limit reached for task (max {MAX_T3_PER_TASK})",
                    tier3_needed=False,
                    requires_user_confirm=False,
                )

            # Register escalation
            if mission_id:
                self.t3_count_by_mission[mission_id] = self.t3_count_by_mission.get(mission_id, 0) + 1
            if task_id:
                self.t3_count_by_task[task_id] = self.t3_count_by_task.get(task_id, 0) + 1
            self.escalate_count += 1

            res = RouterResult(
                decision=RoutingDecision.ESCALATE,
                reason=reason,
                tier3_needed=True,
                requires_user_confirm=requires_confirm,
            )
            logger.info(f"Router: ESCALATE | tool={tool_name} | {res.summary()}")
            return res

        # ── Check 2: Always-escalate tools ────────────────────────────────
        if tool_name in ALWAYS_ESCALATE_TOOLS:
            return _guarded_escalate(
                reason=f"Tool '{tool_name}' always requires Tier 3 review",
                requires_confirm=tool_name in ALWAYS_CONFIRM_TOOLS
            )

        # ── Check 3: T2 explicitly disagrees ──────────────────────────────
        if not verification.agree:
            issues_str = (
                "; ".join(verification.critical_issues[:3])
                if verification.critical_issues
                else "no specific issues given"
            )
            return _guarded_escalate(reason=f"Tier 2 disagreed: {issues_str}")

        # ── Check 4: Critical issues even if agree=True ───────────────────
        actionable_issues = [
            iss for iss in verification.critical_issues
            if not any(kw in iss.lower() for kw in ("unavailable", "timeout", "timed out", "fallback", "n/a", "pending"))
        ]
        if actionable_issues:
            return _guarded_escalate(
                reason=f"Tier 2 found {len(actionable_issues)} critical issue(s) despite agreeing"
            )

        # ── Check 5: Low confidence ───────────────────────────────────────
        if verification.confidence < self.confidence_threshold:
            return _guarded_escalate(
                reason=f"Tier 2 confidence {verification.confidence:.2f} is below threshold {self.confidence_threshold}"
            )

        # ── Check 6: Elevated risk score (below hard block but above escalate) ─
        if verification.risk_score >= ESCALATE_RISK_THRESHOLD:
            return _guarded_escalate(
                reason=f"Risk score {verification.risk_score:.2f} exceeds escalation threshold {ESCALATE_RISK_THRESHOLD}"
            )

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
        tier1_client: Optional[Any] = None,
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
            ollama_client:         Ollama client for T2 scoring
            system_prompt:         The existing system prompt for T1
            tier1_client:          Client for T1 re-generation (defaults to ollama_client)

        Returns:
            Alternative tool call dict if one scores higher, else None
        """
        from core.response_parser import ResponseParser, ParseSuccess

        t1_gen_client = tier1_client or ollama_client

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
            f"Choose a different tool or different parameters.\n\n"
            f"CRITICAL: If you use <think>...</think>, keep your thinking concise (under 5 sentences). "
            f"Respond ONLY with a single valid JSON tool call object."
        )

        try:
            # Generate alternative with T1
            alt_resp = await t1_gen_client.generate(
                model=TIER1_MODEL,
                prompt=alt_prompt,
                system=system_prompt,
                keep_alive=MODEL_KEEP_ALIVE,
                temperature=0.25,   # Slightly higher for exploration
                num_ctx=4096,
                num_predict=2048,
            )
            alt_response = getattr(alt_resp, "text", str(alt_resp))

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

            choice_resp = await ollama_client.generate(
                model=TIER2_MODEL,
                prompt=alt_assessment_prompt,
                system=(
                    "You are a code review expert. "
                    "Evaluate which approach is better. "
                    "Respond with only A or B and one sentence."
                ),
                keep_alive=MODEL_KEEP_ALIVE,
                temperature=0.1,
                num_ctx=2048,
            )
            choice_response = getattr(choice_resp, "text", str(choice_resp))

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
