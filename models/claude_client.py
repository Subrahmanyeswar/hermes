# models/claude_client.py
# Tier 3 Claude Sonnet 4.6 client for HERMES.
# Called ONLY when Tier 1 and Tier 2 disagree or confidence < 0.72.
# Hard cap: $25 total across entire project lifetime. Enforced before every call.
# API key: read ONLY from ANTHROPIC_API_KEY environment variable.
# Every call logs: model, input_tokens, output_tokens, cost_usd, task_id -> SQLite.
# Never log the API key value anywhere.

import os
import time
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

HARD_COST_CAP_USD: float = 25.0        # Never exceed this total lifetime cost
ALERT_THRESHOLD_USD: float = 15.0      # Warn when this is reached
TIER3_MODEL: str = "claude-sonnet-4-6"
INPUT_COST_PER_MTOK: float = 3.0       # $3 per million input tokens
OUTPUT_COST_PER_MTOK: float = 15.0     # $15 per million output tokens
COST_DB_PATH: Path = Path("data/tasks.db")


# ──────────────────────────────────────────────────────────────────────
# Tier 3 Response
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Tier3Response:
    """Response from a Tier 3 Claude API call."""
    content: str                    # The actual response text
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    latency_seconds: float
    success: bool
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────
# Claude Client
# ──────────────────────────────────────────────────────────────────────

class ClaudeClient:
    """
    Tier 3 Claude Sonnet 4.6 client.
    Called only when T1/T2 disagree. Hard $25 lifetime cost cap.
    API key from ANTHROPIC_API_KEY env var only.
    All calls logged to SQLite for auditability.
    """

    def __init__(self, db_path: Path = COST_DB_PATH):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set — Tier 3 will be unavailable")

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.total_cost = self._load_total_cost()

        logger.info(
            f"Claude client ready | total spent so far: ${self.total_cost:.4f} | "
            f"cap: ${HARD_COST_CAP_USD}"
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
        """
        Insert a cost record into SQLite. Updates self.total_cost.
        Warns if total exceeds ALERT_THRESHOLD_USD. Never raises.
        """
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
        """Calculate cost in USD from token counts."""
        return (
            input_tokens / 1_000_000 * INPUT_COST_PER_MTOK +
            output_tokens / 1_000_000 * OUTPUT_COST_PER_MTOK
        )

    def is_available(self) -> bool:
        """Returns True if API key is set and cost cap not reached."""
        return bool(self.api_key) and self.total_cost < HARD_COST_CAP_USD

    def get_cost_summary(self) -> dict:
        """Returns a summary of cost usage."""
        return {
            "total_spent": self.total_cost,
            "cap": HARD_COST_CAP_USD,
            "remaining": HARD_COST_CAP_USD - self.total_cost,
            "alert_threshold": ALERT_THRESHOLD_USD,
        }

    async def arbitrate(
        self,
        task: str,
        tier1_output: str,
        tier2_issues: list[str],
        tool_result: str,
        escalation_reason: str
    ) -> Tier3Response:
        """
        Ask Claude Sonnet 4.6 to arbitrate between T1 and T2.
        Returns Tier3Response. Never raises.
        """
        # ── Step 1: Check hard cap ────────────────────────────────────
        if not self.is_available():
            if not self.api_key:
                msg = "ANTHROPIC_API_KEY not set in environment"
            else:
                msg = f"Hard cost cap reached (${self.total_cost:.2f} / ${HARD_COST_CAP_USD})"
            logger.error(f"Tier 3 unavailable: {msg}")
            return Tier3Response(
                content=tier1_output,  # Fall back to T1's output
                input_tokens=0, output_tokens=0, cost_usd=0.0,
                model=TIER3_MODEL, latency_seconds=0.0,
                success=False, error=msg
            )

        # ── Step 2: Build the arbitration prompt ──────────────────────
        system_prompt = (
            "You are an expert code reviewer arbitrating between two AI agents. "
            "Agent 1 proposed a tool call. Agent 2 raised concerns. "
            "Your job is to make the final decision. "
            "Respond with your authoritative decision in 2-3 sentences. "
            "Be direct and specific about what should happen next."
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

        # ── Step 3: Call the Anthropic API ────────────────────────────
        start_time = time.monotonic()
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            message = client.messages.create(
                model=TIER3_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt
            )

            latency = time.monotonic() - start_time
            content = message.content[0].text
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            cost = self._calculate_cost(input_tokens, output_tokens)

            self._log_cost(
                model=TIER3_MODEL,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                task_description=task[:200],
                escalation_reason=escalation_reason
            )

            logger.info(
                f"Tier 3 arbitration | cost=${cost:.4f} | total=${self.total_cost:.4f} | "
                f"tokens={input_tokens}+{output_tokens} | latency={latency:.2f}s"
            )

            return Tier3Response(
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                model=TIER3_MODEL,
                latency_seconds=latency,
                success=True
            )

        except Exception as e:
            latency = time.monotonic() - start_time
            logger.error(f"Tier 3 API call failed: {type(e).__name__}: {e}")
            return Tier3Response(
                content=tier1_output,  # Fall back to T1's output on API error
                input_tokens=0, output_tokens=0, cost_usd=0.0,
                model=TIER3_MODEL, latency_seconds=latency,
                success=False, error=str(e)
            )
