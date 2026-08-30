# core/verifier.py
# Tier 2 Verifier for HERMES — the second member of the "Council of Two".
# Uses Mistral 7B Instruct Q4_K_M (different family from Tier 1 Qwen).
# Cross-family verification: different training distributions = different failure modes.
# When T1 and T2 agree, we have stronger evidence the output is correct.
# Mistral is loaded ONLY after Tier 1 has finished and unloaded (keep_alive=0).
# Mistral is unloaded with keep_alive=0 after verification.
# The verifier NEVER rewrites the solution — it only evaluates correctness, safety, and quality.

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Any

from loguru import logger

from models.ollama_client import OllamaClient, OllamaTimeoutError, OllamaConnectionError

TIER2_MODEL = "mistral:7b-instruct-q4_K_M"

# ──────────────────────────────────────────────────────────────────────
# Verification Result
# ──────────────────────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    """
    The structured output of Tier 2 verification.
    Every field has a precise meaning used by the disagreement router.
    """
    agree: bool
    confidence: float
    critical_issues: list[str]
    risk_score: float
    reasoning: str = ""
    quality_verdict: str = "NEEDS_IMPROVEMENT"
    quality_findings: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    latency_seconds: float = 0.0
    model_used: str = ""
    raw_response: str = ""

    def __post_init__(self):
        """Clamp confidence and risk_score to valid ranges."""
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.risk_score = max(0.0, min(1.0, self.risk_score))

    @property
    def should_escalate(self) -> bool:
        return (
            not self.agree
            or self.confidence < 0.65
            or self.risk_score > 0.7
            or bool(self.critical_issues)
            or self.quality_verdict in ("SHALLOW", "BLOCKED")
        )

    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"agree={self.agree} | confidence={self.confidence:.2f} | "
            f"risk={self.risk_score:.2f} | issues={len(self.critical_issues)} | "
            f"verdict={self.quality_verdict} | escalate={self.should_escalate}"
        )


# ──────────────────────────────────────────────────────────────────────
# Tier 2 System Prompt & Template
# ──────────────────────────────────────────────────────────────────────

TIER2_SYSTEM_PROMPT = """You are a senior software engineering reviewer.
You assess whether an AI agent's tool call and output satisfy the user's task.

You must respond with ONLY valid JSON in this exact structure:
{
  "agree": true or false,
  "confidence": 0.0 to 1.0,
  "critical_issues": ["issue1", "issue2"],
  "risk_score": 0.0 to 1.0,
  "quality_verdict": "COMPLETE" | "SHALLOW" | "NEEDS_IMPROVEMENT" | "BLOCKED",
  "quality_findings": ["finding1", "finding2"],
  "missing_requirements": ["req1", "req2"]
}

Evaluation criteria:

agree: true if the tool call was correct AND the output is meaningful.
       false if the tool call was wrong, safety-violating, or produced
       trivially insufficient output.

confidence: How confident you are that the task objective was genuinely
            satisfied. Not just that the tool ran. That the TASK was done.
            Low confidence if: file is tiny, content is placeholder,
            features are missing, or requirements are unfulfilled.

critical_issues: List specific problems found.
  Examples:
  - "HTML file is only 8 lines — insufficient for requested implementation"
  - "CSS file contains no animation despite animation being requested"
  - "Component returns empty div — not implemented"
  - "Function body is a TODO stub"

risk_score: 0.0 = safe, 1.0 = dangerous/destructive.

quality_verdict:
  COMPLETE: Implementation fully satisfies the task requirements
  SHALLOW: Implementation exists but is too minimal/placeholder
  NEEDS_IMPROVEMENT: Implementation partially satisfies requirements
  BLOCKED: Cannot proceed — critical issue requires intervention

quality_findings: List what is good or acceptable about the output.

missing_requirements: List specific requirements from the task that
  are NOT satisfied by the current output.

Be strict. A 10-line HTML file for a "premium website" is SHALLOW.
A function stub is NOT implemented. A TODO comment is NOT implementation.

Do not approve based on tool success alone.
Approve based on actual task completion."""

VERIFIER_SYSTEM_PROMPT = TIER2_SYSTEM_PROMPT

TIER2_USER_TEMPLATE = """Review this AI agent action:

ORIGINAL TASK:
{task}

AGENT REASONING:
{reasoning}

TOOL CALLED:
{tool_call}

TOOL RESULT:
{tool_result}

Determine whether this action genuinely satisfies the task objectives.
Respond with only the JSON structure specified."""


# ──────────────────────────────────────────────────────────────────────
# Tier 2 Verifier
# ──────────────────────────────────────────────────────────────────────

class Tier2Verifier:
    """
    Tier 2 verification engine using Mistral 7B Instruct.
    Cross-family verification against Tier 1 (Qwen) outputs.
    Never raises exceptions — always returns a VerificationResult.
    """

    def __init__(self, ollama_client: OllamaClient, model: str = TIER2_MODEL):
        self.client = ollama_client
        self.ollama = ollama_client
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
        tool_call_obj = {"tool": tool_name, "parameters": tool_parameters or {}}
        tool_call_str = json.dumps(tool_call_obj, indent=2)[:800]
        result_str = (
            f"exit_code: {tool_exit_code}\n"
            f"success: {tool_exit_code == 0}\n"
            f"output: {(tool_result_output or '')[:400]}"
        )
        return TIER2_USER_TEMPLATE.format(
            task=task[:600],
            reasoning=(tier1_reasoning or "")[:400],
            tool_call=tool_call_str,
            tool_result=result_str,
        )

    async def verify(
        self,
        task: str = "",
        tier1_reasoning: str = "",
        tool_name: str = "",
        tool_parameters: Optional[dict] = None,
        tool_result_output: str = "",
        tool_exit_code: int = 0,
        original_task: str = "",
        tool_call: Optional[dict] = None,
        tool_result: Any = None,
        **kwargs
    ) -> VerificationResult:
        """Verify T1 output using upgraded quality-aware system prompt."""
        start_time = time.monotonic()
        self.verification_count += 1

        effective_task = original_task or task

        if tool_call is not None:
            tool_call_str = json.dumps(tool_call, indent=2)[:800]
        else:
            tool_call_obj = {"tool": tool_name, "parameters": tool_parameters or {}}
            tool_call_str = json.dumps(tool_call_obj, indent=2)[:800]

        if tool_result is not None:
            exit_code = getattr(tool_result, "exit_code", 0)
            success = getattr(tool_result, "success", True)
            output = getattr(tool_result, "output", "")
            result_str = (
                f"exit_code: {exit_code}\n"
                f"success: {success}\n"
                f"output: {(output or '')[:400]}"
            )
        else:
            result_str = (
                f"exit_code: {tool_exit_code}\n"
                f"success: {tool_exit_code == 0}\n"
                f"output: {(tool_result_output or '')[:400]}"
            )

        user_message = TIER2_USER_TEMPLATE.format(
            task=effective_task[:600],
            reasoning=(tier1_reasoning or "")[:400],
            tool_call=tool_call_str,
            tool_result=result_str,
        )

        try:
            raw = await self.ollama.generate(
                model=self.model,
                prompt=user_message,
                system=TIER2_SYSTEM_PROMPT,
                keep_alive=0,
                temperature=0.1,
                num_ctx=4096,
            )
            latency = time.monotonic() - start_time

            # Parse response
            data = None
            try:
                data = json.loads(raw.strip())
            except json.JSONDecodeError:
                match = re.search(r'\{.*?\}', raw, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group())
                    except Exception:
                        data = None
                if not data:
                    data = {
                        "agree": True,
                        "confidence": 0.5,
                        "critical_issues": ["T2 parse failure — defaulting to pass"],
                        "risk_score": 0.3,
                        "quality_verdict": "NEEDS_IMPROVEMENT",
                        "quality_findings": [],
                        "missing_requirements": [],
                    }

            # Determine quality verdict
            quality_verdict = data.get("quality_verdict", "NEEDS_IMPROVEMENT")
            if quality_verdict not in ("COMPLETE", "SHALLOW", "NEEDS_IMPROVEMENT", "BLOCKED"):
                quality_verdict = "NEEDS_IMPROVEMENT"

            result = VerificationResult(
                agree=bool(data.get("agree", True)),
                confidence=float(data.get("confidence", 0.7)),
                critical_issues=list(data.get("critical_issues", [])),
                risk_score=float(data.get("risk_score", 0.3)),
                reasoning=str(data.get("reasoning", "")),
                quality_verdict=quality_verdict,
                quality_findings=list(data.get("quality_findings", [])),
                missing_requirements=list(data.get("missing_requirements", [])),
                latency_seconds=latency,
                model_used=self.model,
                raw_response=raw,
            )

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
                quality_verdict="BLOCKED",
                latency_seconds=latency,
                model_used=self.model,
            )

        except OllamaConnectionError:
            latency = time.monotonic() - start_time
            logger.error("Tier 2 verification failed — Ollama not reachable")
            return VerificationResult(
                agree=True,
                confidence=0.5,
                critical_issues=[],
                risk_score=0.3,
                reasoning="Tier 2 unavailable — proceeding with Tier 1 result (reduced confidence).",
                quality_verdict="NEEDS_IMPROVEMENT",
                latency_seconds=latency,
                model_used=self.model,
            )

        except Exception as e:
            latency = time.monotonic() - start_time
            logger.warning(f"Tier2Verifier.verify error: {e}")
            return VerificationResult(
                agree=True,
                confidence=0.6,
                critical_issues=[],
                risk_score=0.2,
                reasoning=f"Verification error: {str(e)[:100]}",
                quality_verdict="NEEDS_IMPROVEMENT",
                quality_findings=[],
                missing_requirements=[],
                latency_seconds=latency,
                model_used=self.model,
            )
