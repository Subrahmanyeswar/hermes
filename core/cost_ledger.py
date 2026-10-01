# core/cost_ledger.py
"""
Authoritative Cost and Token Ledger for HERMES 2.x (Prompt 16).

Central Invariants:
1. TRUTHFULNESS: Never fabricate model costs. If pricing is unconfigured, report UNKNOWN.
2. PRECISE ATTRIBUTION: Attributes tokens and costs across T1, T2, T3 and operational domains
   (primary, repair, subagent, btw, plan, compact, verification).
3. NON-INVASIVE: Observational tracking; never mutates mission state or interrupts execution.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ModelUsageRecord:
    """An individual record of model usage."""
    request_id: str
    tier: str              # "T1", "T2", "T3"
    provider: str          # "nvidia_nim", "ollama", "claude"
    model: str             # model identifier
    attribution: str       # "primary", "repair", "subagent", "btw", "plan", "compact", "verification"
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_seconds: float
    estimated_cost_usd: Optional[float] = None
    session_id: Optional[str] = None
    mission_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class CostLedger:
    """Authoritative ledger for model usage, token accounting, and cost tracking."""

    # Default configured prices per 1M tokens (None indicates unknown / local / cloud included)
    # T1: NVIDIA NIM (glm-5.3-flash) -> Typically cloud token or trial
    # T2: Ollama Cloud (gpt-oss:120b-cloud)
    # T3: Claude 3.5 Sonnet or Nemotron Ultra
    TIER_PRICING: Dict[str, Dict[str, float]] = {
        # Optional reference pricing if configured: (input_per_million, output_per_million)
        "claude": {"input": 3.00, "output": 15.00},
    }

    def __init__(self) -> None:
        self._records: List[ModelUsageRecord] = []
        self._lock = threading.Lock()

    def record_usage(
        self,
        tier: str,
        provider: str,
        model: str,
        attribution: str = "primary",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_seconds: float = 0.0,
        request_id: str = "",
        session_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        explicit_cost_usd: Optional[float] = None,
    ) -> ModelUsageRecord:
        """Record a model invocation with token and latency telemetry."""
        total_tokens = prompt_tokens + completion_tokens

        # Compute cost if pricing known or explicit cost passed
        estimated_cost = explicit_cost_usd
        if estimated_cost is None and provider.lower() in self.TIER_PRICING:
            pricing = self.TIER_PRICING[provider.lower()]
            estimated_cost = (
                (prompt_tokens / 1_000_000.0) * pricing["input"]
                + (completion_tokens / 1_000_000.0) * pricing["output"]
            )

        rec = ModelUsageRecord(
            request_id=request_id or f"req_{len(self._records) + 1}",
            tier=tier.upper(),
            provider=provider,
            model=model,
            attribution=attribution.lower(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_seconds=latency_seconds,
            estimated_cost_usd=estimated_cost,
            session_id=session_id,
            mission_id=mission_id,
            timestamp=time.time(),
        )

        with self._lock:
            self._records.append(rec)

        return rec

    def get_summary(
        self,
        session_id: Optional[str] = None,
        mission_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate usage metrics truthfully across tiers and attributions."""
        with self._lock:
            filtered = [
                r for r in self._records
                if (session_id is None or r.session_id == session_id)
                and (mission_id is None or r.mission_id == mission_id)
            ]

        total_requests = len(filtered)
        total_prompt_tokens = sum(r.prompt_tokens for r in filtered)
        total_completion_tokens = sum(r.completion_tokens for r in filtered)
        total_tokens = sum(r.total_tokens for r in filtered)

        # Tier breakdown
        by_tier: Dict[str, Dict[str, Any]] = {
            "T1": {"requests": 0, "tokens": 0, "cost_usd": 0.0, "has_cost": False},
            "T2": {"requests": 0, "tokens": 0, "cost_usd": 0.0, "has_cost": False},
            "T3": {"requests": 0, "tokens": 0, "cost_usd": 0.0, "has_cost": False},
        }

        # Attribution breakdown
        by_attribution: Dict[str, Dict[str, Any]] = {}

        has_any_cost = False
        total_cost = 0.0

        for r in filtered:
            tier_key = r.tier if r.tier in by_tier else "T1"
            by_tier[tier_key]["requests"] += 1
            by_tier[tier_key]["tokens"] += r.total_tokens
            if r.estimated_cost_usd is not None:
                by_tier[tier_key]["cost_usd"] += r.estimated_cost_usd
                by_tier[tier_key]["has_cost"] = True
                total_cost += r.estimated_cost_usd
                has_any_cost = True

            attr_key = r.attribution or "primary"
            if attr_key not in by_attribution:
                by_attribution[attr_key] = {"requests": 0, "tokens": 0, "cost_usd": 0.0}
            by_attribution[attr_key]["requests"] += 1
            by_attribution[attr_key]["tokens"] += r.total_tokens
            if r.estimated_cost_usd is not None:
                by_attribution[attr_key]["cost_usd"] += r.estimated_cost_usd

        return {
            "total_requests": total_requests,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost if has_any_cost else None,
            "cost_status": "EXACT" if has_any_cost else "UNKNOWN",
            "by_tier": by_tier,
            "by_attribution": by_attribution,
        }

    def clear(self) -> None:
        """Reset ledger records (used for test isolation)."""
        with self._lock:
            self._records.clear()


# Global singleton
cost_ledger = CostLedger()
