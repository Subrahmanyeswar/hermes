# core/verifier.py
# Tier 2 Verifier for HERMES — the second member of the "Council of Two".
# Uses Mistral 7B Instruct Q4_K_M (different family from Tier 1 Qwen).
# Cross-family verification: different training distributions = different failure modes.
# When T1 and T2 agree, we have stronger evidence the output is correct.
# Mistral is loaded ONLY after Tier 1 has finished and unloaded (keep_alive=0).
# Mistral is unloaded with keep_alive=0 after verification.
# The verifier NEVER rewrites the solution — it only evaluates correctness and safety.

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from models.ollama_client import OllamaClient, OllamaTimeoutError, OllamaConnectionError


# ──────────────────────────────────────────────────────────────────────
# Verification Result
# ──────────────────────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    """
    The structured output of Tier 2 verification.
    Every field has a precise meaning used by the disagreement router.
    """
    agree: bool                          # Does T2 agree the tool call is correct and safe?
    confidence: float                    # How confident is T2? Range: 0.0 to 1.0
    critical_issues: list[str]           # List of specific problems found. Empty if agree=True.
    risk_score: float                    # How dangerous is this action? Range: 0.0 to 1.0
    reasoning: str                       # T2's one-sentence explanation of its decision
    latency_seconds: float = 0.0        # Time taken for this verification call
    model_used: str = ""                 # Which model produced this result
    raw_response: str = ""              # Raw Tier 2 output, stored for debugging

    def __post_init__(self):
        """Clamp confidence and risk_score to valid ranges."""
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.risk_score = max(0.0, min(1.0, self.risk_score))

    @property
    def should_escalate(self) -> bool:
        """
        Returns True if the disagreement router should escalate to Tier 3.
        Escalation conditions (any one is sufficient):
          - agree is False
          - confidence < 0.72
          - risk_score > 0.7 (destructive or dangerous action)
          - critical_issues list is non-empty
        """
        return (
            not self.agree
            or self.confidence < 0.72
            or self.risk_score > 0.7
            or len(self.critical_issues) > 0
        )

    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"agree={self.agree} | confidence={self.confidence:.2f} | "
            f"risk={self.risk_score:.2f} | issues={len(self.critical_issues)} | "
            f"escalate={self.should_escalate}"
        )


# ──────────────────────────────────────────────────────────────────────
# Tier 2 System Prompt
# ──────────────────────────────────────────────────────────────────────

VERIFIER_SYSTEM_PROMPT = """You are a strict code reviewer and safety auditor for an AI coding agent.
You have been given a task, the AI agent's reasoning, the tool it chose to call, and the tool's result.
Your job is to evaluate whether the tool call was correct, safe, and helpful.

You must respond with ONLY valid JSON. No explanation before or after. No markdown fences.
Your entire response must be parseable by json.loads() or it is a failure.

Required JSON format:
{
  "agree": true or false,
  "confidence": 0.85,
  "critical_issues": [],
  "risk_score": 0.1,
  "reasoning": "One sentence explaining your decision."
}

Field definitions:
- agree: true if the tool call is correct for the task, false if it is wrong or dangerous
- confidence: your certainty (0.0 = total uncertainty, 1.0 = completely certain)
- critical_issues: list of specific problems. EMPTY list [] if you agree and see no issues.
- risk_score: how dangerous is this action (0.0 = safe read operation, 1.0 = irreversible destructive action)
- reasoning: exactly one sentence summarising your evaluation

Risk score guidance:
- 0.0-0.2: read operations, listing files, web search
- 0.2-0.4: creating new files, running safe Python scripts
- 0.4-0.6: modifying existing files, running shell commands
- 0.6-0.8: deleting files, git commits, installing packages
- 0.8-1.0: git push, deleting directories, system-wide changes

When to set agree=false:
- The tool chosen is wrong for the task (e.g. bash_exec when write_file was needed)
- The tool parameters contain errors (wrong path, missing content, syntax errors in code)
- The tool result shows an error but the agent did not detect it
- The action is dangerous and should not proceed without user confirmation

When to set agree=true:
- The tool call correctly addresses the task
- The parameters look correct and complete
- The tool result confirms success (exit_code=0 or file created correctly)
- Any minor issues do not affect the core correctness of the action
"""


# ──────────────────────────────────────────────────────────────────────
# Tier 2 Verifier
# ──────────────────────────────────────────────────────────────────────

class Tier2Verifier:
    """
    Tier 2 verification engine using Mistral 7B Instruct.
    Cross-family verification against Tier 1 (Qwen) outputs.
    Never raises exceptions — always returns a VerificationResult.
    """

    def __init__(self, ollama_client: OllamaClient, model: str = "mistral:7b-instruct-q4_K_M"):
        self.client = ollama_client
        self.model = model
        self.verification_count = 0
        logger.info(f"Tier 2 Verifier initialised | model={model}")

    def _build_verification_prompt(
        self,
        task: str,
        tier1_reasoning: str,
        tool_name: str,
        tool_parameters: dict,
        tool_result_output: str,
        tool_exit_code: int
    ) -> str:
        """Builds the user prompt for Tier 2 verification."""
        return (
            f"TASK: {task}\n\n"
            f"TIER 1 REASONING: {tier1_reasoning[:300]}\n\n"
            f"TOOL CALLED: {tool_name}\n"
            f"TOOL PARAMETERS: {json.dumps(tool_parameters, indent=2)[:500]}\n\n"
            f"TOOL RESULT (exit_code={tool_exit_code}):\n"
            f"{tool_result_output[:800]}\n\n"
            f"Evaluate: is this tool call correct and safe for the given task?"
        )

    async def verify(
        self,
        task: str,
        tier1_reasoning: str,
        tool_name: str,
        tool_parameters: dict,
        tool_result_output: str,
        tool_exit_code: int
    ) -> VerificationResult:
        """
        Verify a Tier 1 tool call using Mistral 7B.
        Returns VerificationResult. Never raises — returns a safe default on error.
        """
        start_time = time.monotonic()
        self.verification_count += 1

        user_prompt = self._build_verification_prompt(
            task, tier1_reasoning, tool_name, tool_parameters,
            tool_result_output, tool_exit_code
        )

        try:
            response = await self.client.generate(
                model=self.model,
                prompt=user_prompt,
                system=VERIFIER_SYSTEM_PROMPT,
                keep_alive=0  # CRITICAL: unload Mistral immediately after verification
            )
            latency = time.monotonic() - start_time
            result = self._parse_verification_response(response, latency)

            logger.info(
                f"Tier 2 verification #{self.verification_count} | "
                f"{result.summary()} | latency={latency:.2f}s"
            )
            return result

        except OllamaTimeoutError:
            latency = time.monotonic() - start_time
            logger.warning(f"Tier 2 verification timed out after {latency:.1f}s — defaulting to escalate")
            return VerificationResult(
                agree=False,
                confidence=0.0,
                critical_issues=["Tier 2 verification timed out"],
                risk_score=0.5,
                reasoning="Verification timed out — escalating to Tier 3 for safety.",
                latency_seconds=latency,
                model_used=self.model
            )

        except OllamaConnectionError:
            latency = time.monotonic() - start_time
            logger.error("Tier 2 verification failed — Ollama not reachable")
            return VerificationResult(
                agree=True,  # Fail open: if T2 is unavailable, proceed with T1's result
                confidence=0.5,
                critical_issues=[],
                risk_score=0.3,
                reasoning="Tier 2 unavailable — proceeding with Tier 1 result (reduced confidence).",
                latency_seconds=latency,
                model_used=self.model
            )

        except Exception as e:
            latency = time.monotonic() - start_time
            logger.error(f"Tier 2 verification unexpected error: {type(e).__name__}: {e}")
            return VerificationResult(
                agree=False,
                confidence=0.0,
                critical_issues=[f"Verification error: {str(e)[:100]}"],
                risk_score=0.5,
                reasoning="Unexpected verification error — escalating for safety.",
                latency_seconds=latency,
                model_used=self.model
            )

    def _parse_verification_response(self, response: str, latency: float) -> VerificationResult:
        """Parse Tier 2 JSON response into VerificationResult."""
        cleaned = response.strip()
        # Strip markdown fences if present
        cleaned = re.sub(r'^```json\s*', '', cleaned)
        cleaned = re.sub(r'^```\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"Tier 2: JSON parse failed: {e} | response={response[:150]!r}")
            # Try to extract agree field from raw text as fallback
            has_agree_true = '"agree": true' in response.lower() or '"agree":true' in response.lower()
            return VerificationResult(
                agree=has_agree_true,
                confidence=0.4,  # Low confidence — parsing failed
                critical_issues=["Tier 2 response was not valid JSON"],
                risk_score=0.3,
                reasoning="Could not parse Tier 2 response as JSON.",
                latency_seconds=latency,
                model_used=self.model,
                raw_response=response[:500]
            )

        return VerificationResult(
            agree=bool(data.get("agree", False)),
            confidence=float(data.get("confidence", 0.5)),
            critical_issues=list(data.get("critical_issues", [])),
            risk_score=float(data.get("risk_score", 0.5)),
            reasoning=str(data.get("reasoning", "No reasoning provided.")),
            latency_seconds=latency,
            model_used=self.model,
            raw_response=cleaned
        )
