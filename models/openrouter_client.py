# models/openrouter_client.py
# OpenRouter client for HERMES Tier 3 arbitration & fallback generation.
# Uses stealth/ox-alpha via OpenRouter API.
# API key is loaded strictly from OPENROUTER_API_KEY environment variable.
# Lifetime cost cap: $25 enforced before every call.
# All calls logged to SQLite for auditability.
# Never log the API key.

from __future__ import annotations
import os
import time
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

import httpx
from loguru import logger

from models.provider import ModelProvider, NormalizedModelResponse
from config.model_config import (
    TIER3_MODEL,
    OPENROUTER_API_KEY,
    MODEL_TIMEOUT_SECONDS,
    TIER3_PARAMS,
)

# ----------------------------------------------------------------------
# Constants & Defaults
# ----------------------------------------------------------------------

HARD_COST_CAP_USD: float = 25.0        # Lifetime cost cap across project
ALERT_THRESHOLD_USD: float = 15.0      # Warn threshold
DEFAULT_MODEL: str = TIER3_MODEL or "stealth/ox-alpha"
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
COST_DB_PATH: Path = Path("data/tasks.db")

# Estimated fallback cost per million tokens
DEFAULT_INPUT_COST_PER_MTOK: float = 3.0
DEFAULT_OUTPUT_COST_PER_MTOK: float = 15.0


# ----------------------------------------------------------------------
# Tier 3 Response compatibility class
# ----------------------------------------------------------------------

@dataclass
class Tier3Response:
    """Response from a Tier 3 OpenRouter API arbitration call."""
    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    latency_seconds: float
    success: bool
    error: Optional[str] = None


# ----------------------------------------------------------------------
# OpenRouter Provider
# ----------------------------------------------------------------------

class OpenRouterClient(ModelProvider):
    """
    Tier 3 OpenRouter Provider for HERMES.
    Provides standard generation and arbitration endpoints.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        db_path: Path = COST_DB_PATH,
        timeout_seconds: int = MODEL_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "") or OPENROUTER_API_KEY
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not set — Tier 3 will be unavailable")
        
        self.timeout_seconds = timeout_seconds
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.total_cost = self._load_total_cost()

        logger.info(
            f"OpenRouter client ready | model={DEFAULT_MODEL} | "
            f"total spent: ${self.total_cost:.4f} | cap: ${HARD_COST_CAP_USD}"
        )

    def _init_db(self) -> None:
        """Create the api_costs table if it does not exist."""
        import contextlib
        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_costs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT DEFAULT (datetime('now')),
                        model TEXT NOT NULL,
                        input_tokens INTEGER,
                        output_tokens INTEGER,
                        cost_usd REAL,
                        task_description TEXT,
                        escalation_reason TEXT
                    )
                """)

    def _load_total_cost(self) -> float:
        """Load the total cost from SQLite."""
        try:
            import contextlib
            with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
                row = conn.execute("SELECT SUM(cost_usd) FROM api_costs").fetchone()
                return float(row[0] or 0.0)
        except Exception:
            return 0.0

    def _log_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        task_description: str,
        escalation_reason: str
    ) -> None:
        """Log cost to database and warn on budget alert."""
        try:
            import contextlib
            with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
                with conn:
                    conn.execute(
                        """INSERT INTO api_costs
                           (model, input_tokens, output_tokens, cost_usd, task_description, escalation_reason)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (model, input_tokens, output_tokens, cost_usd,
                         task_description[:200], escalation_reason[:200])
                    )

            self.total_cost += cost_usd
            logger.info(
                f"Cost logged: ${cost_usd:.4f} | total: ${self.total_cost:.4f} / "
                f"${HARD_COST_CAP_USD} | model={model}"
            )

            if self.total_cost >= ALERT_THRESHOLD_USD:
                logger.warning(
                    f"COST ALERT: ${self.total_cost:.2f} spent — approaching "
                    f"hard cap of ${HARD_COST_CAP_USD}"
                )
        except Exception as e:
            logger.error(f"Failed to log cost to SQLite: {type(e).__name__}: {e}")

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD."""
        return (
            (input_tokens / 1_000_000 * DEFAULT_INPUT_COST_PER_MTOK) +
            (output_tokens / 1_000_000 * DEFAULT_OUTPUT_COST_PER_MTOK)
        )

    def is_available(self) -> bool:
        """Check if API key is present and budget is not exceeded."""
        return bool(self.api_key) and self.total_cost < HARD_COST_CAP_USD

    def get_cost_summary(self) -> dict[str, Any]:
        """Return summary of current spending and caps."""
        return {
            "total_spent": self.total_cost,
            "cap": HARD_COST_CAP_USD,
            "remaining": max(0.0, HARD_COST_CAP_USD - self.total_cost),
            "alert_threshold": ALERT_THRESHOLD_USD,
        }

    async def generate(
        self,
        model: str = "",
        prompt: str = "",
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> NormalizedModelResponse:
        """
        Send completion request to OpenRouter chat completions API.
        Returns NormalizedModelResponse.
        """
        active_model = model or DEFAULT_MODEL
        if not self.is_available():
            err_msg = "OpenRouter unavailable: API key not set or cost cap reached"
            logger.error(err_msg)
            return NormalizedModelResponse(
                text="",
                model=active_model,
                provider="openrouter",
                error=err_msg,
                success=False
            )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": active_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://hermes.local",
            "X-Title": "HERMES Agentic Orchestrator",
            "Content-Type": "application/json"
        }

        url = f"{OPENROUTER_BASE_URL}/chat/completions"
        start_time = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds)) as client:
                response = await client.post(url, json=payload, headers=headers)

            latency = time.monotonic() - start_time
            latency_ms = latency * 1000.0

            if response.status_code == 404 and ("glm-5.3-flash" in response.text or active_model == "stealth/ox-alpha"):
                logger.info(f"OpenRouter upstream redirected {active_model} -> z-ai/glm-5.3-flash. Retrying with active endpoint...")
                payload["model"] = "z-ai/glm-5.3-flash"
                active_model = "z-ai/glm-5.3-flash"
                async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds)) as client:
                    response = await client.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                err_text = f"OpenRouter API returned HTTP {response.status_code}: {response.text[:300]}"
                logger.error(err_text)
                return NormalizedModelResponse(
                    text="",
                    model=active_model,
                    provider="openrouter",
                    latency_ms=latency_ms,
                    error=err_text,
                    success=False
                )

            data = response.json()
            choices = data.get("choices", [])
            msg_obj = choices[0].get("message", {}) if choices else {}
            content = msg_obj.get("content") or ""
            usage = data.get("usage", {}) or {}
            input_tokens = usage.get("prompt_tokens") or (len(prompt) // 4)
            output_tokens = usage.get("completion_tokens") or (len(content) // 4)
            total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)
            
            cost = self._calculate_cost(input_tokens, output_tokens)
            self._log_cost(active_model, input_tokens, output_tokens, cost, prompt[:200], "generate")

            # Non-invasive telemetry recording
            try:
                from core.telemetry import telemetry, ModelCallTelemetry, ContextBreakdown
                ctx = ContextBreakdown(
                    system_prompt_chars=len(system),
                    user_prompt_chars=len(prompt),
                    total_input_chars=len(system) + len(prompt),
                    exact_input_tokens=input_tokens,
                )
                mc = ModelCallTelemetry(
                    model=active_model,
                    provider="openrouter",
                    stage="Tier 3 Generation",
                    start_time_monotonic=start_time,
                    end_time_monotonic=start_time + latency,
                    total_latency_ms=latency_ms,
                    prompt_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    context=ctx,
                    cost_usd=cost,
                    success=True,
                )
                with telemetry._global_lock:
                    for req in telemetry._active_requests.values():
                        mc.request_id = req.request_id
                        req.model_calls.append(mc)
                        break
            except Exception:
                pass

            return NormalizedModelResponse(
                text=content,
                model=active_model,
                provider="openrouter",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                cost_usd=cost,
                raw_response=json.dumps(data),
                success=True
            )

        except Exception as exc:
            latency = time.monotonic() - start_time
            logger.error(f"OpenRouter generation exception: {exc}")
            return NormalizedModelResponse(
                text="",
                model=active_model,
                provider="openrouter",
                latency_ms=latency * 1000.0,
                error=str(exc),
                success=False
            )

    async def arbitrate(
        self,
        task: str,
        tier1_output: str,
        tier2_issues: list[str],
        tool_result: str,
        escalation_reason: str
    ) -> Tier3Response:
        """
        Arbitrate between Tier 1 proposal and Tier 2 concerns using stealth/ox-alpha.
        Returns Tier3Response for full drop-in compatibility.
        """
        if not self.is_available():
            if not self.api_key:
                msg = "OPENROUTER_API_KEY not set in environment"
            else:
                msg = f"Hard cost cap reached (${self.total_cost:.2f} / ${HARD_COST_CAP_USD})"
            logger.error(f"Tier 3 unavailable: {msg}")
            return Tier3Response(
                content=tier1_output,
                input_tokens=0, output_tokens=0, cost_usd=0.0,
                model=DEFAULT_MODEL, latency_seconds=0.0,
                success=False, error=msg
            )

        system_prompt = (
            "You are an expert code reviewer arbitrating between two AI agents in HERMES. "
            "Agent 1 proposed a tool call. Agent 2 raised verification concerns. "
            "Your job is to make the authoritative final decision. "
            "Respond with your decision in 2-3 sentences. "
            "Be direct and specific about what action should proceed or be modified."
        )

        user_prompt = (
            f"TASK: {task}\n\n"
            f"AGENT 1 OUTPUT:\n{tier1_output[:600]}\n\n"
            f"AGENT 2 CONCERNS:\n" +
            "\n".join(f"- {issue}" for issue in tier2_issues) + "\n\n"
            f"TOOL RESULT:\n{tool_result[:400]}\n\n"
            f"ESCALATION REASON: {escalation_reason}\n\n"
            f"What is your final decision? Should the action proceed, be modified, or be rejected?"
        )

        start_time = time.monotonic()
        res = await self.generate(
            model=DEFAULT_MODEL,
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.0,
            max_tokens=512
        )
        latency = time.monotonic() - start_time

        if not res.success:
            logger.warning(f"OpenRouter arbitration failed, falling back to T1 output: {res.error}")
            return Tier3Response(
                content=tier1_output,
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
                cost_usd=res.cost_usd,
                model=DEFAULT_MODEL,
                latency_seconds=latency,
                success=False,
                error=res.error
            )

        return Tier3Response(
            content=res.text,
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
            cost_usd=res.cost_usd,
            model=DEFAULT_MODEL,
            latency_seconds=latency,
            success=True
        )
